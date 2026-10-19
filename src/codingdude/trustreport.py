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
"""Trust-my-tests report (ticket #103).

Static evidence tying a source file to the tests that exercise it, so a human
can see whether generated code has test backup before trusting it. Coverage
numbers are deliberately out of scope here: coverage != correctness (research
doc human-code-comprehension.md) — the actionable signal is *which tests name
this module* and whether any of them are property tests.
"""
from __future__ import annotations

import re
from pathlib import Path

_HYPOTHESIS_RE = re.compile(r"^\s*(from hypothesis|import hypothesis)", re.MULTILINE)


def _module_names(rel_path: str) -> list[str]:
    """Dotted module names that a test would import for this source file."""
    p = Path(rel_path)
    parts = list(p.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    names: list[str] = [".".join(parts[i:]) for i in range(len(parts))]
    return [n for n in names if n and not n.endswith(".py")]


def _references_module(text: str, names: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", text) for name in names)


def build_trust_report(workdir: str, rel_path: str) -> dict[str, object]:
    """Report test evidence for one source file, scoped to the workdir."""
    root = Path(workdir).resolve()
    target = (root / rel_path).resolve()
    if not target.is_file() or root not in target.parents:
        return {"error": f"file not found in workdir: {rel_path}"}

    rel = target.relative_to(root).as_posix()
    names = _module_names(rel)
    referencing: list[str] = []
    property_files: list[str] = []

    # Mutation evidence (#156): surface the cache if one exists for this
    # file — never run tests from a report path (a GET must stay fast).
    from .mutation import mutation_cache_evidence

    cached = mutation_cache_evidence(root, rel)
    mutation: dict[str, object] | None = (
        cached if cached.get("available") and cached.get("total") else None
    )

    for test_file in sorted((root / "tests").rglob("test_*.py")):
        try:
            text = test_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not _references_module(text, names):
            continue
        rel_test = test_file.relative_to(root).as_posix()
        referencing.append(rel_test)
        if _HYPOTHESIS_RE.search(text):
            property_files.append(rel_test)

    report: dict[str, object] = {
        "file": rel,
        "referencing_tests": referencing,
        "property_test_files": property_files,
    }
    if mutation is not None:
        report["mutation"] = mutation
    return report
