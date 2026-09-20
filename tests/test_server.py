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
    workdir.mkdir(parents=True, exist_ok=True)  # server rejects nonexistent dirs now
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


def test_render_capture_persists_to_db_and_appears_in_renders(server, tmp_path):
    """R1 gap closed: a render written during a run is recorded in the DB
    (with captured_at provenance) and merged into /sessions/{id}/renders."""
    app, base = server
    workdir = tmp_path / 'proj-render'
    workdir.mkdir()
    session_id = create_session(base, workdir)
    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'make a screenshot', 'model': 'codingdude-test:echo'},
        headers=auth(),
        timeout=30,
    )
    run_id = r.json()['run_id']
    collect_sse(base, run_id)

    # Simulate the capture hook firing mid-run (same event the shell hook emits).
    png = workdir / 'shot.png'
    png.write_bytes(b'\x89PNG fake')

    app.state.channels.get(run_id)  # channel may be reaped post-terminal; fine
    from codingdude.db import Database

    db = Database.connect(tmp_path / 'home')
    db.record_render(
        session_id, 'shot.png', bytes_=png.stat().st_size, mtime=int(png.stat().st_mtime),
    )

    data = httpx.get(
        f'{base}/sessions/{session_id}/renders', headers=auth(), timeout=10
    ).json()
    render = next(r for r in data['renders'] if r['path'] == 'shot.png')
    assert render['captured_at']
    assert render['bytes'] == png.stat().st_size


def test_sse_reattach_mid_run(server, tmp_path):
    """R2 gap closed (live transport E2E): drop the SSE stream mid-run,
    confirm /alive is still true, reattach, and still receive the terminal
    event — the reconnect path the browser relies on."""
    app, base = server
    workdir = tmp_path / 'proj-reattach'
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

    # First consumer connects, then deliberately drops without a terminal event.
    stream = httpx.stream(
        'GET', f'{base}/runs/{run_id}/events', headers=auth(), timeout=10
    )
    with stream as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith('data: '):
                break  # saw the first event; now abandon the connection

    # Probe says the run is still alive → the UI should reattach, not conclude.
    alive = httpx.get(f'{base}/runs/{run_id}/alive', headers=auth(), timeout=10)
    assert alive.json() == {'alive': True}

    # Reattach: a second consumer gets the stream and receives the terminal
    # event once the run ends (cancelled below mid-sleep).
    def cancel_soon() -> None:
        time.sleep(1)
        httpx.delete(f'{base}/runs/{run_id}', headers=auth(), timeout=10)

    import threading as _threading

    _threading.Thread(target=cancel_soon).start()
    events = []
    with httpx.stream(
        'GET', f'{base}/runs/{run_id}/events', headers=auth(), timeout=20
    ) as resp:
        for line in resp.iter_lines():
            if line.startswith('data: '):
                event = json.loads(line.removeprefix('data: '))
                events.append(event)
                if event.get('type') in TERMINAL_EVENTS:
                    break
    assert events, 'reattached stream produced no events'
    assert events[-1]['type'] == 'RUN_CANCELLED'


def test_review_route_delegates_to_worker_subprocess(server, tmp_path):
    """ADR-0002: POST /sessions/{id}/review runs the review in a worker
    subprocess, never an Engine inside the server process."""
    import httpx

    app, base = server
    home = tmp_path / 'home'
    (home / 'config.toml').write_text(
        '[models]\nsubagent = "codingdude-test:echo"\n', encoding='utf-8'
    )
    w = tmp_path / 'proj'
    w.mkdir()
    r = httpx.post(
        f'{base}/sessions', json={'workdir': str(w)}, headers=auth(), timeout=10
    )
    session_id = r.json()['session_id']
    r = httpx.post(
        f'{base}/sessions/{session_id}/review', headers=auth(), timeout=120
    )
    assert r.status_code == 200, r.text
    assert 'worker-echo-ok' in r.json()['findings']


def test_worker_exit_reaps_channel_and_settles_late_consumer(server, tmp_path):
    """R31: when a worker exits, the server must notice, reap the channel, and
    give any waiting consumer a terminal event — the UI must never wait on a
    dead run (live symptom: 'still working' for 300s+ after the worker died)."""
    import time as _t

    app, base = server
    workdir = tmp_path / 'proj Reaper'
    workdir.mkdir()
    session_id = create_session(base, workdir)
    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'say hi', 'model': 'codingdude-test:echo'},
        headers=auth(),
        timeout=30,
    )
    r.json()['run_id']  # worker pid not needed; reap is server-side
    deadline = _t.time() + 30
    active = None
    while _t.time() < deadline:
        active = httpx.get(f'{base}/runs/active', headers=auth(), timeout=10).json()
        if not active:
            break
        _t.sleep(0.3)
    assert active == [], f'channel not reaped after worker exit: {active}'


def test_sse_broadcast_two_consumers_both_get_terminal(server, tmp_path):
    """R31: two attached consumers (two tabs) must BOTH see the full stream.
    A single-consumer queue let one tab steal RUN_FINISHED and leave the
    other tab's UI 'still working' forever."""
    app, base = server
    workdir = tmp_path / 'proj broadcast'
    workdir.mkdir()
    session_id = create_session(base, workdir)
    r = httpx.post(
        f'{base}/sessions/{session_id}/runs',
        json={'prompt': 'say hi', 'model': 'codingdude-test:echo'},
        headers=auth(),
        timeout=30,
    )
    run_id = r.json()['run_id']

    import threading

    results: list[list[dict]] = [[], []]

    def consume(slot: int) -> None:
        results[slot] = collect_sse(base, run_id, timeout=30)

    threads = [threading.Thread(target=consume, args=(i,)) for i in range(2)]
    for th in threads:
        th.start()
        time.sleep(0.3)  # stagger attaches so the second joins mid-stream
    for th in threads:
        th.join(timeout=45)
        assert not th.is_alive()

    for events in results:
        types = [e['type'] for e in events]
        assert 'RUN_STARTED' in types, types
        assert types[-1] == 'RUN_FINISHED', types


def test_active_runs_excludes_terminal_delivered_runs(server):
    """A worker draining its post-run tail is alive but the run is over: the
    UI must not show the stop button for a run whose terminal already landed
    (live symptom: stop button flickering ~2min after 'finished')."""
    import subprocess as sp

    from codingdude.server import RunChannel

    app, base = server
    ch = RunChannel('run-tail', 'sess-tail', app.state.channels)
    ch.worker = sp.Popen(['python', '-c', 'import time; time.sleep(60)'])
    app.state.channels['run-tail'] = ch
    ch.push({'type': 'RUN_FINISHED'})
    try:
        active = httpx.get(f'{base}/runs/active', headers=auth(), timeout=10).json()
        assert 'run-tail' not in [a['run_id'] for a in active]
    finally:
        ch.worker.kill()
        ch.worker.wait()


def test_server_boot_reconciles_orphaned_runs(tmp_path):
    """R31: runs still 'running' in the DB when the server starts are marked
    'interrupted' at boot — a bounced run gets a deterministic end state."""
    from codingdude.db import Database

    home = tmp_path / 'home'
    db = Database.connect(home)
    sid = db.create_session(tmp_path / 'work')
    db.record_run_start('ghostRun', sid, pid=1)
    app = create_app(home=home, token='test-token', allow_testclient=True)
    del app
    db2 = Database.connect(home)
    assert db2.get_run('ghostRun')['status'] == 'interrupted'


def test_session_runs_endpoint_lists_recent_runs(server, tmp_path):
    """#77: run-output view data source — recent runs, newest first."""
    app, base = server
    sid = create_session(base, tmp_path / 'work')
    app.state.db.record_run_start('runX', sid, pid=7)
    r = httpx.get(f'{base}/sessions/{sid}/runs', headers=auth(), timeout=10)
    assert r.status_code == 200
    runs = r.json()
    assert [x['run_id'] for x in runs] == ['runX']
    assert runs[0]['status'] == 'running'
    assert runs[0]['worker_pid'] == 7
