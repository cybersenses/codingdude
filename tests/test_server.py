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


def test_passwordless_local_auth_grants_session(server):
    app, base = server
    # No cookie -> unauthorized.
    assert httpx.get(f'{base}/sessions?workdir=/', timeout=5).status_code == 401
    # A same-origin local browser gets a session with no secret at all.
    r = httpx.post(f'{base}/auth/local', headers={'sec-fetch-site': 'same-origin'}, timeout=5)
    assert r.status_code == 200
    cookie = r.cookies.get('cd_session')
    assert cookie
    # The issued cookie authorizes normal endpoints.
    r2 = httpx.get(
        f'{base}/sessions?workdir=/', cookies={'cd_session': cookie}, timeout=5
    )
    assert r2.status_code == 200


def test_passwordless_grant_rejects_cross_site_and_rebinding(server):
    app, base = server
    # Cross-site fetch (CSRF vector).
    r = httpx.post(
        f'{base}/auth/local', headers={'sec-fetch-site': 'cross-site'}, timeout=5
    )
    assert r.status_code == 403
    # Foreign Origin claiming same-origin.
    r = httpx.post(
        f'{base}/auth/local',
        headers={'sec-fetch-site': 'same-origin', 'origin': 'https://evil.example'},
        timeout=5,
    )
    assert r.status_code == 403
    # DNS rebinding: attacker domain resolving to 127.0.0.1.
    r = httpx.post(
        f'{base}/auth/local',
        headers={'sec-fetch-site': 'same-origin', 'host': 'evil.example'},
        timeout=5,
    )
    assert r.status_code == 403
    # No Sec-Fetch attestation (old browser or non-browser client).
    r = httpx.post(f'{base}/auth/local', timeout=5)
    assert r.status_code == 403


def test_passwordless_grant_allows_typed_url(server):
    app, base = server
    r = httpx.post(f'{base}/auth/local', headers={'sec-fetch-site': 'none'}, timeout=5)
    assert r.status_code == 200


def test_token_stable_across_restarts(tmp_path):
    from codingdude.server import load_or_create_token

    home = tmp_path / 'home'
    t1 = load_or_create_token(home)
    t2 = load_or_create_token(home)
    assert t1 == t2
    assert (home / 'server-token').read_text(encoding='utf-8').strip() == t1


def test_second_run_supersedes_live_run_for_session(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'proj5'
    workdir.mkdir()
    session_id = create_session(base, workdir)
    r1 = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'first', 'model': 'codingdude-test:sleep'},
        headers=auth(),
        timeout=30,
    ).json()['run_id']
    time.sleep(3)
    # A second run for the same session must cancel the first worker.
    r2 = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'resume', 'model': 'codingdude-test:echo'},
        headers=auth(),
        timeout=30,
    ).json()['run_id']
    assert r2 != r1
    events = collect_sse(base, r1, timeout=15)
    assert events[-1]['type'] == 'RUN_CANCELLED'


def test_session_list_includes_context_fields(server, tmp_path):
    app, base = server
    workdir = tmp_path / 'ctx-proj'
    workdir.mkdir()
    session_id = create_session(base, workdir)
    app.state.db.update_session_context(session_id, 96_000, 200_000)
    r = httpx.get(
        f'{base}/sessions', params={'workdir': str(workdir)},
        headers=auth(), timeout=10,
    )
    assert r.status_code == 200
    row = r.json()[0]
    assert row['context_tokens'] == 96_000
    assert row['context_limit'] == 200_000


def test_run_alive_watchdog_probe(server, tmp_path):
    """/runs/{id}/alive (R2): true while the worker runs, false afterwards.

    A reconnecting UI uses this to choose between reattaching the stream and
    concluding the run finished while it was detached.
    """
    app, base = server
    workdir = tmp_path / 'proj-alive'
    workdir.mkdir()
    session_id = create_session(base, workdir)
    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'ponder', 'model': 'codingdude-test:sleep'},
        headers=auth(),
        timeout=30,
    )
    run_id = r.json()['run_id']
    time.sleep(3)
    alive = httpx.get(f'{base}/runs/{run_id}/alive', headers=auth(), timeout=10)
    assert alive.status_code == 200
    assert alive.json() == {'alive': True}

    app.state.channels[run_id].worker.kill()
    app.state.channels[run_id].worker.wait(timeout=10)
    dead = httpx.get(f'{base}/runs/{run_id}/alive', headers=auth(), timeout=10)
    assert dead.json() == {'alive': False}

    unknown = httpx.get(f'{base}/runs/no-such-run/alive', headers=auth(), timeout=10)
    assert unknown.json() == {'alive': False}


def test_session_notes_and_keep_endpoints(server, tmp_path):
    app, base = server
    session_id = create_session(base, tmp_path / 'proj')
    h = auth()

    r = httpx.post(
        f'{base}/sessions/{session_id}/keep', json={'keep': True}, headers=h, timeout=10
    )
    assert r.status_code == 200
    sessions = httpx.get(
        f'{base}/sessions', params={'workdir': str(tmp_path / 'proj')},
        headers=h, timeout=10,
    ).json()
    assert sessions[0]['keep_for_evals'] is True

    r = httpx.post(
        f'{base}/sessions/{session_id}/notes',
        json={'content': 'off the rails', 'run_id': 'r1', 'offset_s': 4.5},
        headers=h, timeout=10,
    )
    assert r.status_code == 200
    notes = httpx.get(
        f'{base}/sessions/{session_id}/notes', headers=h, timeout=10
    ).json()
    assert len(notes) == 1
    assert notes[0]['content'] == 'off the rails'
    assert notes[0]['offset_s'] == 4.5
