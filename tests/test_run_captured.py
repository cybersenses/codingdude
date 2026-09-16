"""run_captured: shared subprocess capture helper (subprocess-runner dedup)."""
import sys
import textwrap
import time
from pathlib import Path

import pytest

from codingdude.tools import run_captured


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
