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
"""Projects: named workdir registry, no cross-project bleeding."""

import time
from pathlib import Path

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


def test_project_crud_flow(client, tmp_path):
    c, token = client
    h = {'Authorization': f'Bearer {token}'}
    proj = tmp_path / 'alpha'
    proj.mkdir()
    r = c.post('/projects', json={'name': 'Alpha', 'workdir': str(proj)}, headers=h)
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


def test_projects_recent_first(client, tmp_path):
    """The most recently active project must come first (resume-to-latest)."""
    c, token = client
    h = _auth(token)
    a = str(tmp_path / 'aaa')
    b = str(tmp_path / 'zzz')
    Path(a).mkdir()
    Path(b).mkdir()
    c.post('/projects', json={'name': 'AAA', 'workdir': a}, headers=h)
    c.post('/projects', json={'name': 'ZZZ', 'workdir': b}, headers=h)
    # Activity only in AAA (alphabetically first — must now sort first).
    c.post('/sessions', json={'workdir': a}, headers=h)
    time.sleep(0.05)
    r = c.get('/projects', headers=h)
    names = [p['name'] for p in r.json()]
    assert names.index('AAA') < names.index('ZZZ')
    # With activity in ZZZ instead, ZZZ must outrank AAA despite its name.
    c.post('/sessions', json={'workdir': b}, headers=h)
    r = c.get('/projects', headers=h)
    names = [p['name'] for p in r.json()]
    assert names.index('ZZZ') < names.index('AAA')


def test_project_with_nonexistent_workdir_rejected(client, tmp_path):
    """A typo'd path (e.g. 'G:Ai-Dev\\Godot' — missing backslash after the
    drive) must 422, not silently register a garbage workdir that later
    resolves against the server CWD and scaffolds nowhere (#steraids)."""
    c, token = client
    h = _auth(token)
    r = c.post('/projects', json={'name': 'X', 'workdir': str(tmp_path / 'nope')}, headers=h)
    assert r.status_code == 422
    assert 'no such directory' in r.json()['detail']


def test_project_with_drive_relative_workdir_rejected(client):
    """`G:Ai-Dev\\X` (backslash dropped after the drive) must 422 before the
    existence check — the engine may have already scaffolded the phantom
    CWD-relative dir, which would make the existence check pass (#108)."""
    c, token = client
    h = _auth(token)
    r = c.post('/projects', json={'name': 'X', 'workdir': 'G:Ai-Dev\\Godot-Steroids'}, headers=h)
    assert r.status_code == 422
    assert 'drive-relative' in r.json()['detail']


def test_session_with_drive_relative_workdir_rejected(client):
    c, token = client
    h = _auth(token)
    r = c.post('/sessions', json={'workdir': 'G:Ai-Dev\\Godot-Steroids'}, headers=h)
    assert r.status_code == 422
    assert 'drive-relative' in r.json()['detail']


def test_session_with_nonexistent_workdir_rejected(client, tmp_path):
    c, token = client
    h = _auth(token)
    r = c.post('/sessions', json={'workdir': str(tmp_path / 'missing')}, headers=h)
    assert r.status_code == 422
    assert 'no such directory' in r.json()['detail']


def test_add_project_scaffolds_and_reports_codegraph(client, tmp_path, monkeypatch):
    """Adding a project must set up the base structure immediately — not on
    the first run — and surface whether the codegraph index booted."""
    import codingdude.server as server_mod

    c, token = client
    h = {'Authorization': f'Bearer {token}'}
    proj = tmp_path / 'bravo'
    proj.mkdir()
    monkeypatch.setattr(
        server_mod, '_project_codegraph_boot', lambda wd: {'status': 'failed', 'reason': 'no cli'})
    r = c.post('/projects', json={'name': 'Bravo', 'workdir': str(proj)}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body['codegraph'] == {'status': 'failed', 'reason': 'no cli'}
    assert (proj / 'reference' / 'checklists').is_dir()
    assert (proj / 'reference' / 'research').is_dir()
    assert (proj / 'ROADMAP.md').exists()
    assert (proj / 'CONTEXT.md').exists()
    # failure is reported, never raised
    assert body['scaffold']['errors'] == []


def test_project_codegraph_boot_reports_and_never_raises(tmp_path):
    """The helper's own contract: failure → {'status': 'failed', ...}, never raised."""
    from codingdude.server import _project_codegraph_boot

    def boom(workdir, timeout=300):
        raise RuntimeError('no cli')

    out = _project_codegraph_boot(tmp_path, boot=boom)
    assert out == {'status': 'failed', 'reason': 'RuntimeError: no cli'}

    ok = _project_codegraph_boot(tmp_path, boot=lambda wd, timeout=300: {'status': 'ok', 'reason': None})
    assert ok['status'] == 'ok'
