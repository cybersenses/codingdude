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
"""R28 Phase 2: kill/poll tools over the Phase 1 ProcessRegistry.

Ownership rule: the agent may only kill PIDs it registered. stdin-write is
deliberately absent — run_captured holds no stdin handle; it lands with the
Phase 3 PTY sessions (#57).
"""
import asyncio
import sys
import time

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


def test_shell_toolset_exposes_session_write_read_tools():
    reg = ProcessRegistry()
    toolset = build_shell_toolset(_tmp_path(), policy=_AllowAll(),
                                  registry=reg)
    names = set(toolset.tools)
    assert {'process_write', 'process_read'} <= names


def test_process_write_read_tool_roundtrip():
    async def go():
        reg = ProcessRegistry()
        toolset = build_shell_toolset(_tmp_path(), policy=_AllowAll(),
                                      registry=reg)
        write = _tool(toolset, 'process_write')
        read = _tool(toolset, 'process_read')
        session = reg.start_session(
            [sys.executable, '-u', '-c',
             "import sys\nfor line in sys.stdin:\n"
             "    print('got:' + line.strip(), flush=True)\n"],
            cwd=_tmp_path())
        out = write(str(session.pid), 'ping\n')
        assert 'wrote' in out.lower()
        seen = ''
        deadline = time.time() + 5
        while 'got:ping' not in seen and time.time() < deadline:
            seen += read(str(session.pid))
            time.sleep(0.05)
        assert 'got:ping' in seen
        session.terminate()
    asyncio.run(go())


class _AllowAll:
    def decide(self, command):
        return 'allow'
