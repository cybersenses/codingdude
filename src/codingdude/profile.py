"""On-demand cProfile evidence (ticket #158, R47).

One seam, `run_profile`, mirrors `mutation.run_mutation`: subprocess
`python -m cProfile`, fails closed with a readable `error` dict, and a
`profile_code` agent tool exposes it. In-process profiling would tie the
worker's event loop to the profiled code and share our env — out of scope.
"""
from __future__ import annotations

import io
import pstats
from pathlib import Path

from .tools import resolve_workdir_file

_TOP_N = 15
_DEFAULT_TIMEOUT = 120


async def run_profile(
    workdir: str | Path, rel_path: str, entry: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict:
    """Profile `rel_path` (optionally calling `entry()`) under cProfile.

    Returns {"file", "entry", "top_functions": [{function, calls,
    total_s, cumulative_s}]} or {"error": ...} — never raises.
    """
    root = Path(workdir).resolve()
    target = resolve_workdir_file(root, rel_path)
    if target is None:
        return {"error": f"file not found in workdir: {rel_path}"}

    import sys as _sys

    if entry is not None:
        driver = (
            "import cProfile, runpy, sys\n"
            "ns = runpy.run_path(sys.argv[1])\n"
            "prof = cProfile.Profile()\n"
            "prof.enable()\n"
            f"ns[{entry!r}]()\n"
            "prof.disable()\n"
            "prof.dump_stats(sys.argv[2])\n"
        )
        argv = [_sys.executable, "-c", driver, str(target), str(_stats_path(target))]
    else:
        argv = [
            _sys.executable, "-m", "cProfile", "-o", str(_stats_path(target)),
            str(target),
        ]

    from .tools import run_captured

    captured = await run_captured(argv, cwd=root, timeout=timeout)
    stats_file = _stats_path(target)
    try:
        if captured is None:
            return {"error": f"profile run timed out after {timeout}s"}
        if captured.code == -1:
            return {"error": captured.stderr.strip() or "cProfile failed to spawn"}
        if captured.code != 0:
            return {"error": captured.stderr.strip()[-800:] or f"exit {captured.code}"}
        return {
            "file": rel_path,
            "entry": entry,
            "top_functions": _top_functions(stats_file),
        }
    finally:
        stats_file.unlink(missing_ok=True)


def _stats_path(target: Path) -> Path:
    return target.with_name(target.name + ".cprofile-stats")


def _top_functions(stats_file: Path) -> list[dict]:
    stats = pstats.Stats(str(stats_file), stream=io.StringIO())
    raw = getattr(stats, "stats")  # noqa: B009 — untyped in typeshed
    rows = sorted(
        raw.items(), key=lambda kv: kv[1][3], reverse=True,
    )[:_TOP_N]
    return [
        {
            "function": f"{filename}:{line}({name})",
            "calls": call_count,
            "total_s": round(total, 4),
            "cumulative_s": round(cumulative, 4),
        }
        for (filename, line, name), (call_count, _rc, total, cumulative, _callers)
        in rows
    ]


def build_profile_toolset(workdir: Path):
    """The `profile_code` tool: on-demand cProfile of a workdir file (#158)."""
    from pydantic_ai import ModelRetry
    from pydantic_ai.toolsets import FunctionToolset

    async def profile_code(path: str, entry: str | None = None) -> str:
        """Profile a Python file in the project with cProfile and report the
        hottest functions by cumulative time.

        Use for "why is this slow" questions. `entry` optionally names a
        zero-argument function in the file to run; omit it to execute the
        whole file top-to-bottom.
        """
        result = await run_profile(workdir, path, entry)
        if "error" in result:
            raise ModelRetry(f"profile failed: {result['error']}")
        lines = [f"profile of {result['file']} (entry={result['entry']}):"]
        for fn in result["top_functions"]:
            lines.append(
                f"  {fn['cumulative_s']:8.3f}s cum  {fn['total_s']:8.3f}s tot"
                f"  {fn['calls']:>7}x  {fn['function']}"
            )
        return "\n".join(lines)

    return FunctionToolset([profile_code])
