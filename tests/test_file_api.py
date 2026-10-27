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
"""R34 #69: server file API on the shared agent rails.

The frontend's file endpoints must behave like the agent's file tools:
workdir-contained paths, atomic writes (uuid temp + os.replace), and
mtime-based staleness so a human editor can't clobber changes that landed
after they opened the file.
"""

import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from codingdude.server import create_app


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    app = create_app(home=tmp_path / 'home', token='test-token')
    sock = __import__('socket').socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error')
    uvicorn_server = uvicorn.Server(config)
    import threading

    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    app.state.port = port
    for _ in range(50):
        try:
            httpx.get(f'http://127.0.0.1:{port}/health', timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    yield app, f'http://127.0.0.1:{port}'
    uvicorn_server.should_exit = True
    thread.join(timeout=5)


def auth():
    return {'Authorization': 'Bearer test-token'}


def make_session(base, workdir: Path) -> str:
    r = httpx.post(
        f'{base}/sessions', json={'workdir': str(workdir)}, headers=auth(), timeout=10
    )
    assert r.status_code == 200
    return r.json()['session_id']


def test_get_file_returns_mtime_and_content(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    (workdir / 'app.py').write_text('x = 1\n', encoding='utf-8')
    session_id = make_session(base, workdir)
    r = httpx.get(
        f'{base}/sessions/{session_id}/file',
        params={'path': 'app.py'}, headers=auth(), timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body['content'] == 'x = 1\n'
    assert body['mtime'] == (workdir / 'app.py').stat().st_mtime_ns


def test_save_with_stale_mtime_conflicts(server, tmp_path):
    """A human editing an old copy must not silently clobber a newer write."""
    app, base = server
    workdir = tmp_path / 'proj-stale'
    workdir.mkdir()
    target = workdir / 'app.py'
    target.write_text('v1\n', encoding='utf-8')
    session_id = make_session(base, workdir)
    read = httpx.get(
        f'{base}/sessions/{session_id}/file',
        params={'path': 'app.py'}, headers=auth(), timeout=10,
    ).json()
    # The file changes underneath the editor (agent or another writer).
    time.sleep(0.05)
    target.write_text('v2 from elsewhere\n', encoding='utf-8')
    r = httpx.put(
        f'{base}/sessions/{session_id}/file',
        json={'path': 'app.py', 'content': 'stale edit\n',
              'expected_mtime': read['mtime']},
        headers=auth(), timeout=10,
    )
    assert r.status_code == 409
    assert target.read_text(encoding='utf-8') == 'v2 from elsewhere\n'


def test_save_with_current_mtime_succeeds(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj-fresh'
    (workdir / 'src').mkdir(parents=True)
    target = workdir / 'src' / 'mod.py'
    target.write_text('a = 1\n', encoding='utf-8')
    session_id = make_session(base, workdir)
    read = httpx.get(
        f'{base}/sessions/{session_id}/file',
        params={'path': 'src/mod.py'}, headers=auth(), timeout=10,
    ).json()
    r = httpx.put(
        f'{base}/sessions/{session_id}/file',
        json={'path': 'src/mod.py', 'content': 'a = 2\n',
              'expected_mtime': read['mtime']},
        headers=auth(), timeout=10,
    )
    assert r.status_code == 200
    assert target.read_text(encoding='utf-8') == 'a = 2\n'
    # Atomic write rails: no temp litter left behind.
    assert not list(workdir.rglob('*.codingdude-tmp'))


def test_path_escape_rejected(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj-esc'
    workdir.mkdir()
    session_id = make_session(base, workdir)
    r = httpx.get(
        f'{base}/sessions/{session_id}/file',
        params={'path': '../outside.txt'}, headers=auth(), timeout=10,
    )
    assert r.status_code == 400


def test_diff_against_head(server, tmp_path):
    """#71: diff endpoint returns the git HEAD baseline + on-disk content."""
    import subprocess

    app, base = server
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    (workdir / 'a.txt').write_text('v1\n', encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=workdir, check=True)
    subprocess.run(['git', 'add', '.'], cwd=workdir, check=True)
    env = dict(**__import__('os').environ)
    env.update({'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})
    subprocess.run(['git', 'commit', '-qm', 'init'], cwd=workdir, check=True, env=env)
    (workdir / 'a.txt').write_text('v2\n', encoding='utf-8')
    (workdir / 'new.txt').write_text('brand new\n', encoding='utf-8')

    sid = make_session(base, workdir)
    r = httpx.get(f'{base}/sessions/{sid}/file_diff', params={'path': 'a.txt'},
                  headers=auth(), timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body['base'] == 'v1\n'
    assert body['content'] == 'v2\n'

    r = httpx.get(f'{base}/sessions/{sid}/file_diff', params={'path': 'new.txt'},
                  headers=auth(), timeout=10)
    assert r.status_code == 200
    assert r.json()['base'] == ''

    r = httpx.get(f'{base}/sessions/{sid}/file_diff', params={'path': '../escape'},
                  headers=auth(), timeout=10)
    assert r.status_code == 400


def test_callgraph_endpoint(server, tmp_path):
    """#94 (R42): user-facing call graph of a workdir file."""
    app, base = server
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    (workdir / 'm.py').write_text('def a():\n    pass\n\ndef b():\n    a()\n', encoding='utf-8')
    sid = make_session(base, workdir)
    r = httpx.get(
        f'{base}/sessions/{sid}/callgraph',
        params={'path': 'm.py'}, headers=auth(), timeout=10,
    )
    assert r.status_code == 200
    g = r.json()
    assert {n['name'] for n in g['nodes']} == {'a', 'b'}
    assert ['b', 'a'] in [list(e) for e in g['edges']]


def test_callgraph_endpoint_rejects_escape(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    sid = make_session(base, workdir)
    r = httpx.get(
        f'{base}/sessions/{sid}/callgraph',
        params={'path': '../outside.py'}, headers=auth(), timeout=10,
    )
    assert r.status_code == 400


def test_callgraph_endpoint_non_utf8_returns_422(server, tmp_path):
    """#99: a non-UTF-8 file must yield a readable 422, not a 500."""
    app, base = server
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    (workdir / 'legacy.py').write_bytes(b'x = "\xff\xfe"\n')
    sid = make_session(base, workdir)
    r = httpx.get(
        f'{base}/sessions/{sid}/callgraph',
        params={'path': 'legacy.py'}, headers=auth(), timeout=10,
    )
    assert r.status_code == 422
    assert 'legacy.py' in r.json()['detail']


def test_checklists_endpoints(server, tmp_path):
    """#93 (R41): distilled checklists are user-invokable actions."""
    app, base = server
    r = httpx.get(f'{base}/checklists', headers=auth(), timeout=10)
    assert r.status_code == 200
    items = r.json()['checklists']
    qa = next(c for c in items if c['name'] == 'qa-testing')
    assert qa['title'] == 'QA & Testing'
    assert 'building test suites' in qa['use_when']

    r = httpx.get(f'{base}/checklists/qa-testing', headers=auth(), timeout=10)
    assert r.status_code == 200
    assert '# QA & Testing Checklist' in r.json()['markdown']

    r = httpx.get(f'{base}/checklists/no-such-thing', headers=auth(), timeout=10)
    assert r.status_code == 404


def test_checklists_served_from_bundled_data(server, monkeypatch):
    """#267 (R73): the checklist endpoints read the bundled package data —
    NOT a repo-root reference/checklists, which only exists on machines
    where scaffold ran (CI symptom: empty list → StopIteration)."""
    import codingdude.server as server_mod

    app, base = server
    fake = [('zeta-probe.md', '# Zeta Probe Checklist\n\nUse when: probing.\n')]
    monkeypatch.setattr(server_mod, '_bundled_checklists', lambda: fake)

    r = httpx.get(f'{base}/checklists', headers=auth(), timeout=10)
    assert r.status_code == 200
    names = [c['name'] for c in r.json()['checklists']]
    assert names == ['zeta-probe']

    r = httpx.get(f'{base}/checklists/zeta-probe', headers=auth(), timeout=10)
    assert r.status_code == 200
    assert 'Zeta Probe' in r.json()['markdown']

    # Unknown names 404 — derived from the same loader, so a bundled-only
    # install can never be probed into arbitrary file reads.
    r = httpx.get(f'{base}/checklists/qa-testing', headers=auth(), timeout=10)
    assert r.status_code == 404


def test_archmap_endpoint(server, tmp_path):
    """#101 (R43): module-level architecture map — files as nodes, imports as edges."""
    app, base = server
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    (workdir / 'main.py').write_text('import helper\n', encoding='utf-8')
    (workdir / 'helper.py').write_text('X = 1\n', encoding='utf-8')
    sid = make_session(base, workdir)
    r = httpx.get(f'{base}/sessions/{sid}/archmap', headers=auth(), timeout=10)
    assert r.status_code == 200
    g = r.json()
    assert {n['id'] for n in g['nodes']} == {'main.py', 'helper.py'}
    assert ['main.py', 'helper.py'] in [list(e) for e in g['edges']]


def test_structure_endpoint(server, tmp_path):
    """#95 (R42): project structure overview for humans."""
    app, base = server
    workdir = tmp_path / 'proj'
    (workdir / 'src').mkdir(parents=True)
    (workdir / 'src' / 'm.py').write_text(
        'class A:\n    def go(self):\n        pass\n\ndef top():\n    pass\n', encoding='utf-8')
    sid = make_session(base, workdir)
    r = httpx.get(f'{base}/sessions/{sid}/structure', headers=auth(), timeout=10)
    assert r.status_code == 200
    files = r.json()['files']
    m = next(f for f in files if f['path'] == 'src/m.py')
    assert any(s['kind'] == 'class' and s['name'] == 'A' for s in m['symbols'])
    assert any(s['kind'] == 'function' and s['name'] == 'top' for s in m['symbols'])
