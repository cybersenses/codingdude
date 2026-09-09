"""Projects: named workdir registry, no cross-project bleeding."""

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


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def test_project_crud_flow(client):
    c, token = client
    h = {'Authorization': f'Bearer {token}'}
    r = c.post('/projects', json={'name': 'Alpha', 'workdir': 'C:/proj/alpha'}, headers=h)
    assert r.status_code == 200
    r = c.get('/projects', headers=h)
    assert any(p['name'] == 'Alpha' for p in r.json())

    r = c.delete('/projects/1', headers=h)
    assert r.json()['deleted'] is True


def test_sessions_are_keyed_by_workdir(client, tmp_path):
    c, token = client
    h = {'Authorization': f'Bearer {token}'}
    alpha = tmp_path / 'alpha'
    beta = tmp_path / 'beta'
    alpha.mkdir()
    beta.mkdir()

    sa = c.post('/sessions', json={'workdir': str(alpha)}, headers=h).json()['session_id']
    sb = c.post('/sessions', json={'workdir': str(beta)}, headers=h).json()['session_id']

    la = [s['session_id'] for s in c.get(f'/sessions?workdir={alpha}', headers=h).json()]
    lb = [s['session_id'] for s in c.get(f'/sessions?workdir={beta}', headers=h).json()]
    assert sa in la and sb not in la
    assert sb in lb and sa not in lb
