"""R28 Phase 2: kill/poll tools over the Phase 1 ProcessRegistry.

Ownership rule: the agent may only kill PIDs it registered. stdin-write is
deliberately absent — run_captured holds no stdin handle; it lands with the
Phase 3 PTY sessions (#57).
"""
import asyncio
import sys

from codingdude.processes import ProcessRegistry
from codingdude.tools import build_shell_toolset


def _tool(toolset, name):
    return toolset.tools[name].function


async def _sleeperproc():
    return await asyncio.create_subprocess_exec(
        sys.executable, '-c', 'import time; time.sleep(30)',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)


def test_kill_terminates_registered_process():
    async def go():
        reg = ProcessRegistry()
        proc = await _sleeperproc()
        reg.register(proc.pid, 'sleeper')
        msg = reg.kill(proc.pid)
        await proc.wait()
        assert proc.returncode is not None
        assert 'kill' in msg.lower()
    asyncio.run(go())


def test_kill_refuses_unregistered_pid():
    reg = ProcessRegistry()
    msg = reg.kill(999999)
    assert 'not' in msg.lower() or 'unknown' in msg.lower()


def test_poll_reports_liveness():
    async def go():
        reg = ProcessRegistry()
        proc = await _sleeperproc()
        reg.register(proc.pid, 'sleeper')
        live = reg.poll(proc.pid)
        assert live is not None and live['status'] == 'running'
        proc.kill()
        await proc.wait()
        dead = reg.poll(proc.pid)
        assert dead is not None and dead['status'] != 'running'
    asyncio.run(go())


def test_poll_unknown_pid_is_none():
    reg = ProcessRegistry()
    assert reg.poll(999999) is None


def test_shell_toolset_exposes_process_tools():
    reg = ProcessRegistry()
    toolset = build_shell_toolset(_tmp_path(), policy=_AllowAll(),
                                  registry=reg)
    names = set(toolset.tools)
    assert {'process_list', 'process_kill', 'process_poll'} <= names


def test_process_kill_tool_kills_and_reports():
    class AllowAll:
        def decide(self, command):
            return 'allow'

    async def go():
        reg = ProcessRegistry()
        toolset = build_shell_toolset(_tmp_path(), policy=AllowAll(),
                                      registry=reg)
        kill = _tool(toolset, 'process_kill')
        proc = await _sleeperproc()
        reg.register(proc.pid, 'sleeper')
        out = kill(str(proc.pid))
        await proc.wait()
        assert proc.returncode is not None
        assert str(proc.pid) in out
    asyncio.run(go())


def _tmp_path():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


class _AllowAll:
    def decide(self, command):
        return 'allow'
