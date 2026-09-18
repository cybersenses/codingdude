"""R28 Phase 1 (#55): ProcessRegistry — visibility-only shell-process tracking.

Seams under test:
- ProcessRegistry: register/finish/snapshot, trace events, DB persistence
- run_captured(registry=...): lifecycle recorded; background-spawner flagged
- build_shell_toolset(registry=...): the shell tool records what it spawns
- GET /sessions/{id}/processes: HITL visibility endpoint
"""
import sys
import textwrap

import pytest

from codingdude.db import Database
from codingdude.processes import ProcessRegistry


def test_registry_records_lifecycle_and_emits_events():
    events = []
    reg = ProcessRegistry(on_event=events.append)
    reg.register(123, 'echo hi')
    reg.finish(123, status='exited', exit_code=0)
    snap = reg.snapshot()
    assert snap[0]['pid'] == 123
    assert snap[0]['command'] == 'echo hi'
    assert snap[0]['status'] == 'exited'
    assert snap[0]['exit_code'] == 0
    assert [e['type'] for e in events] == ['PROCESS_STARTED', 'PROCESS_EXITED']


def test_registry_persists_to_db(tmp_path):
    db = Database.connect(tmp_path / 'home')
    sid = db.create_session(tmp_path)
    reg = ProcessRegistry(db=db, session_id=sid)
    reg.register(7, 'sleep 5')
    reg.finish(7, status='exited', exit_code=0, background=True)
    rows = db.list_processes(sid)
    assert rows[0]['pid'] == 7
    assert rows[0]['command'] == 'sleep 5'
    assert rows[0]['status'] == 'exited'
    assert rows[0]['background'] is True


@pytest.mark.asyncio
async def test_run_captured_records_lifecycle(tmp_path):
    from codingdude.tools import run_captured

    events = []
    reg = ProcessRegistry(on_event=events.append)
    cap = await run_captured(
        [sys.executable, '-c', 'print("hi")'], cwd=tmp_path, timeout=10,
        registry=reg,
    )
    assert cap is not None and cap.code == 0
    assert [e['type'] for e in events] == ['PROCESS_STARTED', 'PROCESS_EXITED']
    assert events[0]['command'] == ' '.join(
        [sys.executable, '-c', 'print("hi")'])
    assert events[1]['exit_code'] == 0
    assert events[1]['background'] is False


# Same grandchild scenario as test_run_captured.py: a child that spawns a
# detached grandchild holding the pipes is a background spawner — the
# registry must flag it so HITL knows an orphan was created.
GRANDCHILD_SCRIPT = textwrap.dedent('''
    import subprocess, sys
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    print("parent done")
''')


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows pipe inheritance')
@pytest.mark.asyncio
async def test_run_captured_flags_background_spawner(tmp_path):
    from codingdude.tools import run_captured

    script = tmp_path / '_grandchild_parent.py'
    script.write_text(GRANDCHILD_SCRIPT)
    reg = ProcessRegistry()
    cap = await run_captured(
        [sys.executable, str(script)], cwd=tmp_path, timeout=5, registry=reg,
    )
    assert cap is not None
    snap = reg.snapshot()
    assert snap[0]['background'] is True


@pytest.mark.asyncio
async def test_shell_tool_registers_process(tmp_path):
    from codingdude.approvals import ApprovalPolicy
    from codingdude.tools import build_shell_toolset

    tmp_path.mkdir(parents=True, exist_ok=True)
    events = []
    reg = ProcessRegistry(on_event=events.append)
    toolset = build_shell_toolset(
        tmp_path, ApprovalPolicy(yolo=True), registry=reg,
    )
    out = await toolset.tools['shell'].function('echo hello')
    assert 'exit code: 0' in out
    assert [e['type'] for e in events] == ['PROCESS_STARTED', 'PROCESS_EXITED']


def test_stale_running_rows_reconcile_with_pid_liveness(tmp_path):
    """A process whose worker died before mark_exited stays 'running' in the
    DB forever (observed: footer showed a phantom live process, pid dead).
    list_processes must reconcile status with actual pid liveness."""
    import subprocess
    import time

    from codingdude.processes import _pid_alive

    db = Database.connect(tmp_path / 'home')
    sid = db.create_session(tmp_path)

    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    time.sleep(0.3)
    assert _pid_alive(proc.pid)
    proc.kill()
    proc.wait()
    assert not _pid_alive(proc.pid)

    db.record_process(
        sid, pid=proc.pid, command='wedged', started_at='t', status='running'
    )
    rows = db.list_processes(sid)
    assert rows[0]['status'] != 'running'
    # persisted, not just papered over in the response
    assert db.list_processes(sid)[0]['status'] == rows[0]['status']


def test_server_exposes_session_processes(tmp_path):
    """HITL visibility: the server lists recorded processes for a session."""
    from fastapi.testclient import TestClient

    from codingdude.server import create_app

    home = tmp_path / 'home'
    app = create_app(home=home, token='t', allow_testclient=True)
    client = TestClient(app)
    sid = client.post(
        '/sessions', json={'workdir': str(tmp_path)},
        headers={'Authorization': 'Bearer t'},
    ).json()['session_id']

    db = Database.connect(home)
    reg = ProcessRegistry(db=db, session_id=sid)
    reg.register(42, 'npm run dev')
    reg.finish(42, status='exited', exit_code=1)

    r = client.get(
        f'/sessions/{sid}/processes',
        headers={'Authorization': 'Bearer t'},
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]['pid'] == 42
    assert rows[0]['command'] == 'npm run dev'
