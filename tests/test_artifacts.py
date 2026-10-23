# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
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


def test_dismiss_retires_a_pending_card(store):
    artifact_id = store.emit_choice_card('Which?', options=['a', 'b'])
    store.dismiss(artifact_id)
    assert store.list()[0]['status'] == 'dismissed'
    assert store.feedback(artifact_id) is None  # dismissed, not answered
    with pytest.raises(ValueError, match='dismissed'):
        store.respond(artifact_id, {'pick': 'a'})


def test_dismiss_unknown_artifact_id(store):
    with pytest.raises(KeyError, match='no artifact'):
        store.dismiss('missing')


def test_dismiss_pending_is_session_scoped(db, store):
    answered_id = store.emit_choice_card('answered?', options=['a'])
    store.respond(answered_id, {'pick': 'a'})
    pending_id = store.emit_spec_block('spec', 'draft')
    other = ArtifactStore(db, db.create_session(Path.cwd(), title='other'))
    other.emit_choice_card('other?', options=['a'])

    assert store.dismiss_pending() == 1
    assert {a['id']: a['status'] for a in store.list()} == {
        answered_id: 'answered',
        pending_id: 'dismissed',
    }
    assert other.list()[0]['status'] == 'pending'


def test_watch_yields_snapshot_then_deltas(store):
    choice_id = store.emit_choice_card('Which?', options=['a', 'b'])
    events = store.watch(poll_seconds=0.01)
    snapshot = next(events)
    assert snapshot['event'] == 'snapshot'
    assert [a['id'] for a in snapshot['artifacts']] == [choice_id]

    spec_id = store.emit_spec_block('spec', 'draft')
    delta = next(events)
    assert delta == {'event': 'emitted', 'artifact': delta['artifact']}
    assert delta['artifact']['id'] == spec_id

    store.respond(choice_id, {'pick': 'a'})
    delta = next(events)
    assert delta['event'] == 'answered'
    assert delta['artifact']['id'] == choice_id
    assert delta['artifact']['status'] == 'answered'
    events.close()


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

        # R58: a stale card is retired, not answered, and cannot come back.
        stale_id = store.emit_choice_card('stale?', options=['a', 'b'])
        assert c.post(f'/artifacts/{stale_id}/dismiss', headers=h).json() == {'ok': True}
        assert c.post(f'/artifacts/{stale_id}/dismiss', headers=h).status_code == 422
        assert c.post('/artifacts/nope/dismiss', headers=h).status_code == 404

        listed = c.get(f'/sessions/{sid}/artifacts', headers=h).json()
        assert {a['id']: a['status'] for a in listed} == {
            stale_id: 'dismissed',
            spec_id: 'answered',
            choice_id: 'answered',
        }

        # The SSE endpoint itself is wired as a StreamingResponse over
        # store.watch(); the generator is covered by test_watch_*, and a
        # TestClient stream read blocks on the infinite tail, so we don't
        # exercise it end-to-end here.


def test_start_run_dismisses_previous_runs_cards(tmp_path, monkeypatch):
    """R58: a new run can never consume an answer meant for a dead one."""
    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))

    class _FakeWorker:
        pid = 4242
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            pass

    monkeypatch.setattr('codingdude.server.subprocess.Popen', lambda *a, **k: _FakeWorker())
    app = create_app(home=tmp_path / 'home', token='test-token', allow_testclient=True)
    app.state.port = 8000
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        h = {'Authorization': f'Bearer {app.state.token}'}
        wd = tmp_path / 'proj'
        wd.mkdir()
        sid = c.post('/sessions', json={'workdir': str(wd)}, headers=h).json()['session_id']
        store = ArtifactStore(Database.connect(tmp_path / 'home'), sid)
        stale_id = store.emit_choice_card('from the dead run?', options=['a', 'b'])

        assert c.post(
            f'/sessions/{sid}/runs', json={'prompt': 'go'}, headers=h
        ).status_code == 200
        assert {a['id']: a['status'] for a in store.list()} == {stale_id: 'dismissed'}


# ---- artifact history: auto-captured Q&A and decisions ----

def test_record_qa_round_trip(store):
    artifact_id = store.record_qa(
        [{'question': 'Which database?', 'options': ['postgres', 'sqlite']}],
        {'0': 'postgres'},
    )
    listed = store.list()
    assert listed[0]['kind'] == 'qa'
    assert listed[0]['status'] == 'answered'
    assert listed[0]['payload']['questions'][0]['question'] == 'Which database?'
    assert listed[0]['payload']['answers'] == {'0': 'postgres'}
    assert store.feedback(artifact_id) == {'0': 'postgres'}


def test_record_decision_round_trip(store):
    artifact_id = store.record_decision('Use SQLite', 'single-user, no server')
    listed = store.list()
    assert listed[0]['kind'] == 'decision'
    assert listed[0]['status'] == 'answered'
    assert listed[0]['title'] == 'Use SQLite'
    assert listed[0]['payload'] == {'title': 'Use SQLite', 'body': 'single-user, no server'}
    assert store.feedback(artifact_id) is not None


def test_roadmap_decision_mirrors_artifact(db):
    from codingdude.roadmap import RoadmapStore, build_roadmap_toolset
    session = db.create_session(Path.cwd(), title='mirror')
    store = RoadmapStore(db)
    toolset = build_roadmap_toolset(store, str(Path.cwd()), session_id=session)
    import asyncio
    result = asyncio.run(toolset.tools['record_decision'].function('ADR: pick X', 'why not Y'))
    assert 'recorded' in result
    artifacts = ArtifactStore(db, session).list()
    assert len(artifacts) == 1
    assert artifacts[0]['kind'] == 'decision'
    assert artifacts[0]['title'] == 'ADR: pick X'


def test_roadmap_decision_no_session_no_artifact(db):
    import asyncio

    from codingdude.roadmap import RoadmapStore, build_roadmap_toolset
    store = RoadmapStore(db)
    toolset = build_roadmap_toolset(store, str(Path.cwd()))
    asyncio.run(toolset.tools['record_decision'].function('ADR: pick X'))
    assert db._conn.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0] == 0
