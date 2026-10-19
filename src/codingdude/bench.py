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
"""A/B micro-benchmark evidence (ticket #160, R47).

One seam, `run_bench`, per design decision #16: in-process timing inside a
*subprocess* (never the worker's event loop), no external benchmark
binaries. Candidates are zero-argument callables in one module, run with
the same repeat/inner budget; `best_s` is the comparison metric (least
scheduler noise). Fails closed like `mutation.run_mutation`.
"""
from __future__ import annotations

import json
from pathlib import Path

from .tools import resolve_workdir_file

_DEFAULT_REPEAT = 5
_DEFAULT_INNER = 50

# Runs in the subprocess: import the target module, time each entry with
# perf_counter loops, print one JSON object. Print (not exit-code) carries
# the payload so real crashes still surface as non-zero exits.
_DRIVER = (
    "import importlib.util, json, sys, time\n"
    "spec = importlib.util.spec_from_file_location('_bench_target', sys.argv[1])\n"
    "mod = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(mod)\n"
    "repeat, inner = int(sys.argv[2]), int(sys.argv[3])\n"
    "out = {}\n"
    "for name in sys.argv[4:]:\n"
    "    fn = getattr(mod, name)\n"
    "    times = []\n"
    "    for _ in range(repeat):\n"
    "        t0 = time.perf_counter()\n"
    "        for _ in range(inner):\n"
    "            fn()\n"
    "        times.append((time.perf_counter() - t0) / inner)\n"
    "    out[name] = {'best_s': min(times), 'mean_s': sum(times) / len(times)}\n"
    "print(json.dumps(out))\n"
)


async def run_bench(
    workdir: str | Path, rel_path: str, entries: list[str],
    repeat: int = _DEFAULT_REPEAT, inner: int = _DEFAULT_INNER,
    timeout: int = 120,
) -> dict:
    """Benchmark zero-arg callables `entries` from `rel_path` head-to-head.

    Returns {"candidates": [{entry, best_s, mean_s}], "winner"} or
    {"error": ...} — never raises. `winner` is the fastest `best_s`.
    """
    root = Path(workdir).resolve()
    target = resolve_workdir_file(root, rel_path)
    if target is None:
        return {"error": f"file not found in workdir: {rel_path}"}
    if not entries:
        return {"error": "no candidate entries given"}

    import sys as _sys

    argv = [
        _sys.executable, "-c", _DRIVER, str(target), str(max(1, repeat)),
        str(max(1, inner)), *entries,
    ]

    from .tools import run_captured

    captured = await run_captured(argv, cwd=root, timeout=timeout)
    if captured is None:
        return {"error": f"benchmark timed out after {timeout}s"}
    if captured.code == -1:
        return {"error": captured.stderr.strip() or "benchmark failed to spawn"}
    if captured.code != 0:
        return {"error": captured.stderr.strip()[-800:] or f"exit {captured.code}"}
    try:
        timings = json.loads(captured.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": "benchmark produced no parsable output"}
    missing = [name for name in entries if name not in timings]
    if missing:
        return {"error": f"unknown entries in {rel_path}: {', '.join(missing)}"}

    candidates = [
        {"entry": name, **timings[name]} for name in entries
    ]
    winner = min(candidates, key=lambda row: row["best_s"])["entry"]
    return {"file": rel_path, "candidates": candidates, "winner": winner}


def build_bench_toolset(workdir: Path):
    """The `compare_benchmark` tool: A/B timing evidence (#160, R47)."""
    from pydantic_ai import ModelRetry
    from pydantic_ai.toolsets import FunctionToolset

    async def compare_benchmark(path: str, entries: list[str]) -> str:
        """Benchmark two or more zero-argument functions from one Python
        file head-to-head and report which is fastest.

        Each function is called repeatedly with identical budget; `best_s`
        per call is the comparison metric. Use to settle algorithm choices
        with numbers instead of guessing.
        """
        result = await run_bench(workdir, path, entries)
        if "error" in result:
            raise ModelRetry(f"benchmark failed: {result['error']}")
        lines = [f"benchmark of {result['file']} — winner: {result['winner']}"]
        for row in sorted(result["candidates"], key=lambda r: r["best_s"]):
            lines.append(
                f"  {row['best_s'] * 1e6:10.1f}us best  "
                f"{row['mean_s'] * 1e6:10.1f}us mean  {row['entry']}"
            )
        return "\n".join(lines)

    return FunctionToolset([compare_benchmark])
