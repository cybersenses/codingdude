"""HTTP seam: real server + worker subprocess, token auth, SSE, cancellation."""

import json
import socket
import threading
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
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error')
    uvicorn_server = uvicorn.Server(config)
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


def auth(version='o'):
    return {'Authorization': 'Bearer test-token'}


def create_session(base, workdir: Path) -> str:
    r = httpx.post(
        f'{base}/sessions', json={'workdir': str(workdir)}, headers=auth(), timeout=10
    )
    assert r.status_code == 200, r.text
    return r.json()['session_id']


def collect_sse(base, run_id, timeout=30) -> list[dict]:
    events = []
    with httpx.stream(
        'GET', f'{base}/runs/{run_id}/events', headers=auth(), timeout=timeout
    ) as r:
        for line in r.iter_lines():
            if line.startswith('data: '):
                event = json.loads(line.removeprefix('data: '))
                events.append(event)
                if event.get('type') in ('RUN_FINISHED', 'RUN_ERROR', 'RUN_CANCELLED'):
                    return events
    return events


def test_health_and_auth_rejected(server):
    app, base = server
    assert httpx.get(f'{base}/health', timeout=5).status_code == 200
    # no token
    assert httpx.get(f'{base}/sessions?workdir=/', timeout=5).status_code == 401
    # wrong token
    r = httpx.get(
        f'{base}/sessions?workdir=/', headers={'Authorization': 'Bearer nope'}, timeout=5
    )
    assert r.status_code == 401


def test_session_create_list_resume(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    session_id = create_session(base, workdir)

    listed = httpx.get(
        f'{base}/sessions', params={'workdir': str(workdir)}, headers=auth(), timeout=10
    ).json()
    assert session_id in [s['session_id'] for s in listed]
    assert httpx.get(
        f'{base}/sessions/{session_id}/messages', headers=auth(), timeout=10
    ).status_code == 200


def test_run_streams_ag_ui_events(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj2'
    workdir.mkdir()
    session_id = create_session(base, workdir)

    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'say hi', 'model': 'codingdude-test:echo'},
        headers=auth(),
        timeout=30,
    )
    assert r.status_code == 200, r.text
    run_id = r.json()['run_id']

    events = collect_sse(base, run_id)
    types = [e['type'] for e in events]
    assert 'RUN_STARTED' in types
    assert 'RUN_FINISHED' in types
    contents = ''.join(
        e.get('delta', '') for e in events if e['type'] == 'TEXT_MESSAGE_CONTENT'
    )
    assert 'worker-echo-ok' in contents
    # The worker shares the DB, so the session has the full exchange now.
    messages = httpx.get(
        f'{base}/sessions/{session_id}/messages', headers=auth(), timeout=10
    ).json()
    assert len(messages) >= 2


def test_cancel_kills_worker(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj3'
    workdir.mkdir()
    session_id = create_session(base, workdir)
    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'ponder', 'model': 'codingdude-test:sleep'},
        headers=auth(),
        timeout=30,
    )
    run_id = r.json()['run_id']
    # Give the worker time to connect, then cancel.
    time.sleep(3)
    r = httpx.delete(f'{base}/runs/{run_id}', headers=auth(), timeout=10)
    assert r.status_code == 200
    events = collect_sse(base, run_id, timeout=10)
    assert events[-1]['type'] == 'RUN_CANCELLED'
    # Server is still alive afterwards.
    assert httpx.get(f'{base}/health', timeout=5).status_code == 200
