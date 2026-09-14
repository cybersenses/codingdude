"""run_captured: shared subprocess capture helper (subprocess-runner dedup)."""
import sys
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
