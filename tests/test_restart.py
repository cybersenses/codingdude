"""Read-only tests for the self-restart helper.

These deliberately NEVER call bounce()/trigger_restart() — that would kill the
test runner's server. They exercise discovery and the relaunch command only.
"""

import json
import os

from codingdude import restart


def test_status_is_read_only_and_returns_json(capsys):
    rc = restart.main(['--status'])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['port'] == 8765
    assert 'healthy' in payload
    assert 'relaunch' in payload


def test_relaunch_argv_runs_serve_on_the_port():
    cmd = restart.relaunch_argv(8765)
    assert cmd[-3:] == ['serve', '--port', '8765']
    assert cmd[0]


def test_list_processes_sees_this_process():
    procs = restart.list_processes()
    assert any(p['pid'] == os.getpid() for p in procs)


def test_find_server_processes_returns_pid_dicts():
    # Discovery must never raise; a running server is found by listening port or
    # by the `serve` command line (so this may be non-empty while the agent runs).
    procs = restart.find_server_processes(port=8765)
    assert isinstance(procs, list)
    for proc in procs:
        assert isinstance(proc.get('pid'), int)
