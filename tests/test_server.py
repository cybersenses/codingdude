"""HTTP seam: real server + worker subprocess, token auth, SSE, cancellation."""

import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from codingdude.events import TERMINAL_EVENTS
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
                if event.get('type') in TERMINAL_EVENTS:
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


def test_worker_crash_leaves_session_resumable(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj4'
    workdir.mkdir()
    session_id = create_session(base, workdir)

    # First run completes and persists.
    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'say hi', 'model': 'codingdude-test:echo'},
        headers=auth(),
        timeout=30,
    )
    collect_sse(base, r.json()['run_id'])

    # Second run: hard-kill the worker mid-flight (a crash, not a cancel).
    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'ponder', 'model': 'codingdude-test:sleep'},
        headers=auth(),
        timeout=30,
    )
    run_id = r.json()['run_id']
    time.sleep(3)
    worker = app.state.channels[run_id].worker
    worker.kill()
    worker.wait(timeout=10)

    # The Session survives with its prior turns; server stays healthy.
    messages = httpx.get(
        f'{base}/sessions/{session_id}/messages', headers=auth(), timeout=10
    )
    assert messages.status_code == 200
    assert len(messages.json()) >= 2
    assert httpx.get(f'{base}/health', timeout=5).status_code == 200


def test_interactive_approval_roundtrip(server, tmp_path):
    """Gate → GATE_REQUEST over SSE → approve → run completes."""
    import time as _t

    app, base = server
    workdir = tmp_path / 'proj5'
    workdir.mkdir()
    session_id = create_session(base, workdir)
    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'run the gated thing', 'model': 'codingdude-test:gated'},
        headers=auth(),
        timeout=30,
    )
    run_id = r.json()['run_id']

    seen = []
    decision_sent = {'done': False}
    with httpx.stream(
        'GET', f'{base}/runs/{run_id}/events', headers=auth(), timeout=30
    ) as resp:
        for line in resp.iter_lines():
            if not line.startswith('data: '):
                continue
            event = json.loads(line.removeprefix('data: '))
            seen.append(event)
            if event['type'] == 'GATE_REQUEST' and not decision_sent['done']:
                _t.sleep(0.2)  # let the worker settle into its wait
                rr = httpx.post(
                    f'{base}/runs/{run_id}/approve',
                    json={'decision': 'approve'},
                    headers=auth(),
                    timeout=10,
                )
                assert rr.status_code == 200, rr.text
                decision_sent['done'] = True
            if event['type'] in TERMINAL_EVENTS:
                break

    types = [e['type'] for e in seen]
    assert 'GATE_REQUEST' in types
    assert types[-1] == 'RUN_FINISHED'
    contents = ''.join(e.get('delta', '') for e in seen if e['type'] == 'TEXT_MESSAGE_CONTENT')
    assert 'gated-ran' in contents
