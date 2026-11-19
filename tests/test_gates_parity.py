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
"""The local gate and CI must check the same thing, and pytest must be bounded.

Two defects this pins (#368):

* `gates.bat` linted ``src tests tools`` while CI linted ``src tests bench.py``,
  so a ``bench.py`` edit passed locally and failed CI — a manufactured re-run.
* Nothing bounded a single test, so one hung test burned the whole 30-minute
  job cap instead of failing in two minutes naming itself.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ruff_targets(path: Path) -> set[str]:
    """The path arguments of the one `ruff check` invocation in a gate script."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"ruff check ([^|&\n\r]+)", text)
    assert match, f"no 'ruff check' invocation in {path.name}"
    return set(match.group(1).split())


def test_local_gate_and_ci_lint_the_same_targets() -> None:
    local = _ruff_targets(ROOT / "gates.bat")
    ci = _ruff_targets(ROOT / ".github" / "workflows" / "ci.yml")

    assert local == ci, (
        "gates.bat and CI lint different targets "
        f"(local only: {sorted(local - ci)}, CI only: {sorted(ci - local)})"
    )
    # Both directories were missing from one side or the other at some point.
    assert {"tools", "bench.py"} <= local


def test_no_live_doc_restates_a_different_ruff_target_set() -> None:
    """Mentioning the lint command is fine; mentioning a *different* one is drift.

    code-design.md is deliberately excluded: it is a historical journal whose
    "gates this round" lines record the command that actually ran at the time,
    so rewriting them would falsify the record rather than fix a drift.
    """
    local = _ruff_targets(ROOT / "gates.bat")
    live_docs = ("CONTRIBUTING.md", "README.md", "docs/TECHNICAL-DESIGN-MANUAL.md")

    for name in live_docs:
        path = ROOT / name
        if not path.exists():
            continue
        for captured in re.findall(r"ruff check ([`\w./ -]*)", path.read_text(encoding="utf-8")):
            restated = {t.strip("`") for t in captured.split() if t.strip("`")}
            if not restated:
                continue  # a bare `ruff check` mention states no target set
            assert restated == local, f"{name} restates the ruff targets as {sorted(restated)}"


def test_pytest_is_bounded_so_one_hang_cannot_burn_the_job_cap() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    timeout = pyproject["tool"]["pytest"]["ini_options"].get("timeout")
    assert isinstance(timeout, int) and timeout > 0, "pytest has no per-test timeout"

    dev = " ".join(pyproject["dependency-groups"]["dev"])
    assert "pytest-timeout" in dev, "pytest-timeout is not declared, so the setting is inert"
