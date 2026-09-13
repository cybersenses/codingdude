"""R6 tracer: living-artifact channel — store, agent tools, server endpoints."""

import re
from pathlib import Path

import pytest

from codingdude.artifacts import ArtifactStore, build_artifacts_toolset
from codingdude.db import Database
from codingdude.server import create_app


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database.connect(tmp_path / 'home')


@pytest.fixture
def session(db: Database) -> str:
    return db.create_session(Path.cwd(), title='artifacts')


@pytest.fixture
def store(db: Database, session: str) -> ArtifactStore:
    return ArtifactStore(db, session)


def test_choice_card_round_trip(store):
    artifact_id = store.emit_choice_card(
        'Which layout?', options=['stacked', 'split'], description='pick one'
    )
    assert store.feedback(artifact_id) is None  # pending
    store.respond(artifact_id, {'pick': 'split'})
    feedback = store.feedback(artifact_id)
    assert feedback == {'pick': 'split'}
    listed = store.list()
    assert listed[0]['kind'] == 'choice'
    assert listed[0]['status'] == 'answered'
    assert listed[0]['title'] == 'Which layout?'


def test_spec_block_round_trip(store):
    artifact_id = store.emit_spec_block('auth spec', 'Users log in via OAuth.')
    assert store.feedback(artifact_id) is None
    store.respond(artifact_id, {'content': 'Users log in via OAuth + TOTP.'})
    assert store.feedback(artifact_id) == {'content': 'Users log in via OAuth + TOTP.'}


def test_respond_rejects_pick_not_in_options(store):
    artifact_id = store.emit_choice_card('Which?', options=['a', 'b'])
    with pytest.raises(ValueError, match='not one of'):
        store.respond(artifact_id, {'pick': 'c'})


def test_respond_rejects_wrong_payload_shape(store):
    artifact_id = store.emit_choice_card('Which?', options=['a', 'b'])
    with pytest.raises(ValueError, match='pick'):
        store.respond(artifact_id, {'content': 'nope'})


def test_unknown_artifact_id(store):
    with pytest.raises(KeyError, match='no artifact'):
        store.feedback('missing')
    with pytest.raises(KeyError, match='no artifact'):
        store.respond('missing', {'pick': 'a'})


async def test_toolset_emit_and_feedback(db, session):
    toolset = build_artifacts_toolset(db, session)
    tools = toolset.tools

    out = tools['emit_choice_card'].function(
        'Which layout?', options=['stacked', 'split'], description=''
    )
    artifact_id = re.search(r'id=([A-Za-z0-9_-]+)', out).group(1)
    pending = tools['get_artifact_feedback'].function(artifact_id)
    assert 'pending' in pending

    store = ArtifactStore(db, session)
    store.respond(artifact_id, {'pick': 'stacked'})
    answered = tools['get_artifact_feedback'].function(artifact_id)
    assert 'stacked' in answered


def test_artifact_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    app = create_app(home=tmp_path / 'home', token='test-token', allow_testclient=True)
    app.state.port = 8000
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        token = app.state.token
        h = {'Authorization': f'Bearer {token}'}
        wd = tmp_path / 'proj'
        wd.mkdir()
        sid = c.post('/sessions', json={'workdir': str(wd)}, headers=h).json()['session_id']

        assert c.get(f'/sessions/{sid}/artifacts', headers=h).json() == []

        from codingdude.artifacts import ArtifactStore
        from codingdude.db import Database

        store = ArtifactStore(Database.connect(tmp_path / 'home'), sid)
        choice_id = store.emit_choice_card('Which?', options=['a', 'b'])
        spec_id = store.emit_spec_block('spec', 'draft text')

        listed = c.get(f'/sessions/{sid}/artifacts', headers=h).json()
        assert [a['id'] for a in listed] == [spec_id, choice_id]  # newest first
        assert listed[1]['payload']['options'] == ['a', 'b']

        assert c.post(
            f'/artifacts/{choice_id}/respond', json={'pick': 'b'}, headers=h
        ).json() == {'ok': True}
        assert c.post(
            f'/artifacts/{choice_id}/respond', json={'pick': 'zzz'}, headers=h
        ).status_code == 422
        assert c.post(
            f'/artifacts/{spec_id}/respond', json={'content': 'edited'}, headers=h
        ).json() == {'ok': True}
        assert c.post(
            f'/artifacts/{choice_id}/respond', json={'pick': 'a'}
        ).status_code == 401

        listed = c.get(f'/sessions/{sid}/artifacts', headers=h).json()
        assert all(a['status'] == 'answered' for a in listed)
