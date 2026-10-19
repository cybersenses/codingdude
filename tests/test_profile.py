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
"""Tests for the on-demand cProfile tool (ticket #158, R47)."""

import textwrap
from pathlib import Path

import pytest

from codingdude.profile import build_profile_toolset, run_profile


def _write_script(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    script = root / "slowmod.py"
    script.write_text(
        textwrap.dedent(
            """
            def hot(n):
                total = 0
                for i in range(n):
                    total += i * i
                return total


            def main():
                hot(20000)
            """
        ),
        encoding="utf-8",
    )
    return script


async def test_run_profile_reports_hot_functions(tmp_path: Path) -> None:
    _write_script(tmp_path)
    result = await run_profile(tmp_path, "slowmod.py", "main", timeout=120)
    assert "error" not in result
    assert result["file"] == "slowmod.py"
    assert result["entry"] == "main"
    names = [fn["function"] for fn in result["top_functions"]]
    assert any("hot" in name for name in names), names
    assert all(fn["cumulative_s"] >= 0 for fn in result["top_functions"])


async def test_run_profile_module_entry_runs_whole_file(tmp_path: Path) -> None:
    root = tmp_path
    root.mkdir(parents=True, exist_ok=True)
    script = root / "app.py"
    script.write_text("value = 1 + 1\n", encoding="utf-8")
    result = await run_profile(root, "app.py", None, timeout=120)
    assert "error" not in result
    assert result["entry"] is None


async def test_run_profile_missing_file_fails_closed(tmp_path: Path) -> None:
    result = await run_profile(tmp_path, "nope.py", None, timeout=120)
    assert "error" in result
    assert "nope.py" in result["error"]


async def test_run_profile_path_escape_fails_closed(tmp_path: Path) -> None:
    result = await run_profile(tmp_path, "../outside.py", None, timeout=120)
    assert "error" in result


async def test_toolset_lists_profile_code(tmp_path: Path) -> None:
    toolset = build_profile_toolset(tmp_path)
    assert "profile_code" in toolset.tools


async def test_toolset_tool_returns_error_message_on_bad_path(tmp_path: Path) -> None:
    """Bad path must fail with a readable message, never a raw traceback."""
    from pydantic_ai import ModelRetry

    toolset = build_profile_toolset(tmp_path)
    with pytest.raises(ModelRetry, match="missing.py"):
        await toolset.tools["profile_code"].function(path="missing.py", entry=None)
