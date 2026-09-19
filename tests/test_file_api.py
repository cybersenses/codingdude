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
