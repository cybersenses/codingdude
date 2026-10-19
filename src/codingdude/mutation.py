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
"""Mutation-testing evidence (ticket #156, R47).

Two modes, per the user decision:
1. Targeted — `mutation_cache_evidence` reads a mutmut `.mutmut-cache` scoped to
   one source file; `build_trust_report` surfaces it when present (never runs
   tests itself — a GET endpoint must not take minutes).
2. On-demand — `run_mutation` executes mutmut for one file (or the project),
   and the `run_mutation_suite` agent tool exposes the full-project run.

mutmut 3.x refuses to run on native Windows (boxed/mutmut#397), so we pin
mutmut 2.x as a dev dependency and force UTF-8 IO (cp1252 cannot encode
mutmut's emoji output).
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

_MUTMUT_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

# mutmut 2.x Mutant.status values grouped for the evidence summary.
_KILLED = ("ok_killed",)
_SURVIVED = ("bad_survived", "ok_suspicious")
_TIMEOUT = ("bad_timeout",)


def _cache_path(workdir: Path) -> Path:
    return workdir / ".mutmut-cache"


def mutation_cache_evidence(workdir: str | Path, rel_path: str | None = None) -> dict:
    """Summarise mutmut's cache, optionally scoped to one file.

    Read-only: reports whatever the last `mutmut run` left behind, so callers
    can surface evidence without paying the runtime cost.
    """
    root = Path(workdir).resolve()
    cache = _cache_path(root)
    if not cache.is_file():
        return {"available": False, "reason": "no .mutmut-cache — run mutation tests first"}

    try:
        db = sqlite3.connect(f"file:{cache}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return {"available": False, "reason": f"cannot open cache: {exc}"}

    query = (
        "SELECT sf.filename, ln.line_number, ln.line, m.status "
        "FROM Mutant m JOIN Line ln ON m.line = ln.id "
        "JOIN SourceFile sf ON ln.sourcefile = sf.id"
    )
    params: tuple = ()
    if rel_path is not None:
        target = (root / rel_path).resolve()
        if not target.is_file() or root not in target.parents:
            return {"available": False, "reason": f"file not found in workdir: {rel_path}"}
        rel = target.relative_to(root).as_posix()
        query += " WHERE sf.filename LIKE ?"
        params = (f"%{rel.replace('/', os.sep).replace(os.sep, '%')}%",)

    try:
        rows = db.execute(query, params).fetchall()
    finally:
        db.close()

    surviving: list[dict] = []
    counts = {"killed": 0, "survived": 0, "timeout": 0, "untested": 0}
    for filename, line_number, line_text, status in rows:
        if status in _KILLED:
            counts["killed"] += 1
        elif status in _SURVIVED:
            counts["survived"] += 1
            if len(surviving) < 20:
                surviving.append(
                    {"file": filename, "line": line_number, "text": line_text.strip()}
                )
        elif status in _TIMEOUT:
            counts["timeout"] += 1
        else:
            counts["untested"] += 1
    return {
        "available": True,
        "file": rel_path,
        "total": len(rows),
        **counts,
        "surviving_locations": surviving,
    }


async def run_mutation(workdir: str | Path, rel_path: str | None = None, timeout: int = 1800) -> dict:
    """Run mutmut (targeted to `rel_path` when given) and return the evidence.

    Fails closed: every failure mode returns a readable `error` dict rather
    than raising, so callers (agent tool, trustreport) can decide.
    """
    root = Path(workdir).resolve()
    if not (root / "tests").is_dir():
        return {"error": f"no tests/ directory in {root}"}

    from .tools import run_captured

    argv = [sys.executable, "-m", "mutmut", "run"]
    if rel_path is not None:
        argv += ["--paths-to-mutate", rel_path]

    captured = await run_captured(argv, cwd=root, timeout=timeout, env=_MUTMUT_ENV)
    if captured is None:
        return {"error": f"mutation run timed out after {timeout}s (partial results in cache)"}
    if captured.code == -1:
        return {"error": captured.stderr.strip() or "mutmut failed to spawn"}

    rel = rel_path
    if rel is not None:
        target = (root / rel).resolve()
        if root in target.parents:
            rel = target.relative_to(root).as_posix()
    evidence = mutation_cache_evidence(root, rel)
    if not evidence.get("available"):
        return {"error": str(evidence.get("reason", "mutation run produced no evidence"))}
    evidence["mutmut_output_tail"] = "\n".join(
        line.encode("ascii", "replace").decode("ascii")
        for line in captured.stdout.strip().splitlines()[-5:]
    )
    return evidence


def build_mutation_toolset(workdir: Path):
    """The `run_mutation_suite` tool: on-demand full (or per-file) mutation
    run for the current workdir (#156, R47)."""
    from pydantic_ai import ModelRetry
    from pydantic_ai.toolsets import FunctionToolset

    async def run_mutation_suite(path: str | None = None) -> str:
        """Run mutation tests and report kill-rate evidence.

        Mutates the code (all project sources, or one file via `path`) and
        checks whether the test suite catches the mutants. Surviving mutants
        point at test gaps. Slow: minutes, not seconds.
        Args:
            path: optional file to mutate, relative to the workdir.
        """
        result = await run_mutation(workdir, path)
        if "error" in result:
            raise ModelRetry(f"mutation run failed: {result['error']}")
        killed = result["killed"]
        total = result["total"]
        rate = f"{(killed / total * 100):.0f}%" if total else "n/a"
        lines = [
            f"mutation run: {killed}/{total} killed ({rate}), "
            f"{result['survived']} survived, {result['timeout']} timeout."
        ]
        for loc in result["surviving_locations"]:
            lines.append(f"survived {loc['file']}:{loc['line']}: {loc['text']}")
        return "\n".join(lines)

    return FunctionToolset([run_mutation_suite])
