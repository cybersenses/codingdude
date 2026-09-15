"""Codegraph auto-bootstrap: make sure the workdir has a codegraph index
before a run starts, so the agent never has a broken navigation tool.

Best-effort: any failure is swallowed (returned as None) — a missing index
must never block a run.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_FALLBACK_CMD = Path(r'C:\Users\norma\AppData\Local\codegraph\current\bin\codegraph.CMD')


def find_codegraph_cli() -> str | None:
    """Locate the codegraph CLI (PATH first, then the known Windows shim)."""
    found = shutil.which('codegraph') or shutil.which('codegraph.cmd')
    if found:
        return found
    return str(_FALLBACK_CMD) if _FALLBACK_CMD.exists() else None


def _run_codegraph_init(
    workdir: Path,
    runner=subprocess.run,
    cli_path: str | None = None,
    timeout: int = 300,
) -> str | None:
    """Run `codegraph init` for the workdir; None on any failure (best-effort)."""
    cli = cli_path or find_codegraph_cli()
    if not cli:
        return None
    try:
        proc = runner(['cmd', '/c', cli, 'init', str(workdir)], cwd=workdir,
                      timeout=timeout)
    except Exception:  # best-effort: never block a run on bootstrap failure
        return None
    output = getattr(proc, 'stdout', None) or ''
    if getattr(proc, 'returncode', 0) != 0:
        return None
    return str(output)


def ensure_codegraph_index(
    workdir: Path,
    runner=subprocess.run,
    cli_path: str | None = None,
    timeout: int = 300,
) -> str | None:
    """Run `codegraph init` when the workdir has no `.codegraph` index.

    Returns the CLI output, None when skipped or on any failure.
    `runner` is injectable for tests.
    """
    if (workdir / '.codegraph').exists():
        return None
    return _run_codegraph_init(workdir, runner, cli_path, timeout)


def refresh_codegraph_index(
    workdir: Path,
    runner=subprocess.run,
    cli_path: str | None = None,
    timeout: int = 120,
) -> str | None:
    """Re-run `codegraph init` even when an index exists (R14 mid-run
    refresh): long sessions must not navigate stale code. Best-effort —
    None on any failure, never raises."""
    return _run_codegraph_init(workdir, runner, cli_path, timeout)
