"""CFG endpoint (#154): GET /sessions/{sid}/cfg — basic-block graph for HITL."""

import pytest

from codingdude.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    app = create_app(home=tmp_path / 'home', token='test-token', allow_testclient=True)
    app.state.port = 8000
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, app.state.token


@pytest.fixture
def session_id(client, tmp_path):
    c, token = client
    (tmp_path / 'work').mkdir()
    r = c.post(
        '/sessions', json={'workdir': str(tmp_path / 'work')},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert r.status_code == 200
    return r.json()['session_id']


def _get(client, session_id, **params):
    c, token = client
    return c.get(
        f'/sessions/{session_id}/cfg',
        params=params,
        headers={'Authorization': f'Bearer {token}'},
    )


def test_cfg_lists_functions(client, session_id, tmp_path):
    (tmp_path / 'work' / 'flow.py').write_text(
        "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
    )
    r = _get(client, session_id, path='flow.py')
    assert r.status_code == 200
    assert r.json()['functions'] == ['alpha', 'beta']


def test_cfg_returns_blocks_and_edges(client, session_id, tmp_path):
    (tmp_path / 'work' / 'flow.py').write_text(
        "def f(x):\n    if x:\n        return 1\n    return 2\n    dead = 3\n"
    )
    r = _get(client, session_id, path='flow.py', function='f')
    body = r.json()
    assert r.status_code == 200
    assert body['function'] == 'f'
    assert body['blocks'] and body['edges']
    assert any(not b['reachable'] for b in body['blocks'])


def test_cfg_bad_function_422(client, session_id, tmp_path):
    (tmp_path / 'work' / 'flow.py').write_text("def f():\n    return 1\n")
    assert _get(client, session_id, path='flow.py', function='nope').status_code == 422


def test_cfg_path_escape_400(client, session_id):
    assert _get(client, session_id, path='../evil.py').status_code == 400
