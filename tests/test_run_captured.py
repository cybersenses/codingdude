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
"""run_captured: shared subprocess capture helper (subprocess-runner dedup)."""
import asyncio
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from codingdude.processes import ProcessRegistry
from codingdude.tools import run_captured


def _alive(pid: int) -> bool:
    """True if `pid` is still a live process (test helper)."""
    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, 0, pid)  # QUERY_LIMITED
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.mark.asyncio
async def test_run_captured_captures_code_and_output(tmp_path: Path):
    cap = await run_captured(
        [sys.executable, '-c', 'print("hello")'], cwd=tmp_path, timeout=30)
    assert cap is not None
    assert cap.code == 0
    assert 'hello' in cap.stdout


@pytest.mark.asyncio
async def test_run_captured_timeout_kills_and_returns_none(tmp_path: Path):
    cap = await run_captured(
        [sys.executable, '-c', 'import time; time.sleep(30)'],
        cwd=tmp_path, timeout=2)
    assert cap is None


@pytest.mark.asyncio
async def test_run_captured_combined_strips(tmp_path: Path):
    cap = await run_captured(
        [sys.executable, '-c', 'print("out")'], cwd=tmp_path, timeout=30)
    assert cap is not None
    assert cap.combined == 'out'


# R21 (#34): a grandchild that inherits stdout/stderr keeps the pipes open
# after the parent exits, so communicate() blocks to the full timeout and
# run_captured reports a false timeout, losing the parent's real output.
GRANDCHILD_SCRIPT = textwrap.dedent('''
    import subprocess, sys, time
    # grandchild inherits stdout and sleeps well past the timeout
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"])
    print("parent done")
''')

# Windows-only defect (handle inheritance); grandchild sleep > timeout so a
# regression waits instead of returning promptly.
@pytest.mark.skipif(sys.platform != 'win32', reason='Windows pipe inheritance')
@pytest.mark.asyncio
async def test_run_captured_returns_when_parent_exits_despite_grandchild(
        tmp_path: Path):
    script = tmp_path / '_grandchild_parent.py'
    script.write_text(GRANDCHILD_SCRIPT)
    t0 = time.monotonic()
    cap = await run_captured([sys.executable, str(script)], cwd=tmp_path,
                             timeout=5)
    elapsed = time.monotonic() - t0
    assert cap is not None, 'parent completion lost to grandchild-held pipe'
    assert cap.code == 0
    assert 'parent done' in cap.stdout
    assert elapsed < 4, f'blocked {elapsed:.1f}s past parent exit'


# R30 #61: cancelling run_captured (claims-retry wait_for) must kill the
# spawned process — otherwise bash + grandchildren survive, hold the pipes,
# and the worker's Proactor loop can never close (worker exit hang).
@pytest.mark.asyncio
async def test_run_captured_cancellation_kills_child(tmp_path: Path):
    registry = ProcessRegistry(on_event=None)
    task = asyncio.create_task(run_captured(
        [sys.executable, '-c', 'import time; time.sleep(30)'],
        cwd=tmp_path, timeout=60, registry=registry))
    await asyncio.sleep(0.5)
    pids = [r['pid'] for r in registry.snapshot()]
    assert pids, 'child was never registered'
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.3)
    assert not any(_alive(p) for p in pids), (
        'cancelled run_captured left its child alive — this orphans the '
        'process tree and hangs worker shutdown on Windows')


# R30 #61: the timeout path must kill the whole tree, not just the direct
# child — a surviving grandchild keeps the pipes open and wedges shutdown.
@pytest.mark.asyncio
async def test_run_captured_timeout_kills_grandchild_tree(tmp_path: Path):
    marker = tmp_path / 'gc.pid'
    gc_marker = marker.as_posix()  # backslash paths break inside the child's -c source
    parent = textwrap.dedent(f'''
        import subprocess, sys, time
        code = "import os; open({gc_marker!r}, 'w').write(str(os.getpid())); import time; time.sleep(30)"
        subprocess.Popen([sys.executable, "-c", code])

        def marker_exists():
            try:
                open({gc_marker!r})
                return True
            except OSError:
                return False

        deadline = time.time() + 10
        while not marker_exists() and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(30)
    ''')
    script = tmp_path / '_tree_parent.py'
    script.write_text(parent)
    cap = await run_captured([sys.executable, str(script)],
                             cwd=tmp_path, timeout=5)
    assert cap is None
    gc_pid = int(marker.read_text().strip())
    await asyncio.sleep(0.3)
    assert not _alive(gc_pid), (
        'timeout killed the direct child but the grandchild tree survived')


async def test_run_captured_missing_binary_returns_readable_error(tmp_path: Path):
    """#146: a spawn failure (missing binary) surfaces as tool output, not
    an exception that kills the run."""
    cap = await run_captured(['definitely-not-a-real-binary-xyz'],
                             cwd=tmp_path, timeout=10)
    assert cap is not None
    assert cap.code == -1
    assert 'definitely-not-a-real-binary-xyz' in cap.stderr or \
        'FileNotFoundError' in cap.stderr


async def test_run_captured_spawn_oserror_returns_readable_error(
    tmp_path: Path, monkeypatch,
):
    """#146: OSError at spawn (e.g. WinError 206, command line too long)
    becomes a Captured with the OS message, not a raised exception."""
    import codingdude.tools as tools_mod

    async def boom(*a, **kw):
        raise OSError(206, 'The filename or extension is too long')

    monkeypatch.setattr(tools_mod.asyncio, 'create_subprocess_exec', boom)
    cap = await run_captured(['git', 'status'], cwd=tmp_path, timeout=10)
    assert cap is not None
    assert cap.code == -1
    assert 'too long' in cap.stderr
