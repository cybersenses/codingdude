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
"""Codegraph auto-bootstrap: make sure the workdir has a codegraph index
before a run starts, so the agent never has a broken navigation tool.

Best-effort: any failure is swallowed (returned as None) — a missing index
must never block a run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# LocalAppData is the standard install location on Windows; resolve it
# from the environment so no user-specific path is baked into the source.
_FALLBACK_CMD = (
    Path.home() / 'AppData' / 'Local' / 'codegraph' / 'current' / 'bin' / 'codegraph.CMD'
)


_SKIP_DIRS = {
    '.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache',
    '.pytest_cache', '.codegraph', '.codingdude', 'dist',
}


def index_is_stale(workdir: Path) -> bool:
    """#203: is the codegraph index older than the newest source file?

    A wedged/long-lived daemon keeps serving whatever index it booted with;
    if any project source file is newer than the newest index file, the
    graph is stale and `codegraph init` should re-run before the agent
    navigates with it. Cheap directory scan, no subprocess.
    """
    workdir = Path(workdir)
    index_dir = workdir / '.codegraph'
    if not index_dir.exists() or not any(index_dir.iterdir()):
        return False  # missing/empty is boot_codegraph's problem, not staleness
    try:
        index_newest = max(f.stat().st_mtime for f in index_dir.rglob('*') if f.is_file())
    except OSError:
        return True  # unreadable index — assume stale so boot re-inits
    for dirpath, dirnames, filenames in os.walk(workdir):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if not name.endswith(('.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.go', '.rs', '.java', '.rb', '.php', '.cs', '.c', '.cpp', '.h')):
                continue
            try:
                if os.stat(os.path.join(dirpath, name)).st_mtime > index_newest:
                    return True
            except OSError:
                continue
    return False


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
) -> tuple[bool, str]:
    """Run `codegraph init` for the workdir; (False, reason) on any failure."""
    cli = cli_path or find_codegraph_cli()
    if not cli:
        return False, 'codegraph CLI not found'
    try:
        proc = runner(['cmd', '/c', cli, 'init', str(workdir)], cwd=workdir,
                      timeout=timeout)
    except (subprocess.TimeoutExpired, TimeoutError):
        return False, f'codegraph init timed out after {timeout}s'
    except Exception as exc:  # best-effort: never block a run on bootstrap failure
        return False, f'{type(exc).__name__}: {exc}'
    output = getattr(proc, 'stdout', None) or ''
    rc = getattr(proc, 'returncode', 0)
    if rc != 0:
        return False, f'codegraph init exit {rc}'
    return True, str(output)


def _has_healthy_index(workdir: Path) -> bool:
    """An index exists *and* is non-empty (partial/corrupt dirs re-init)."""
    index_dir = workdir / '.codegraph'
    return index_dir.exists() and any(index_dir.iterdir())


def boot_codegraph(
    workdir: Path,
    runner=subprocess.run,
    cli_path: str | None = None,
    timeout: int = 300,
) -> dict:
    """Bootstrap the workdir's codegraph index with a visible outcome.

    Returns {'status': 'ok'|'skipped'|'failed', 'reason': str|None} so the
    engine can emit a CODEGRAPH_BOOT event and, on failure, hint the model
    instead of leaving it to blind-retry broken tools (#33).
    """
    if _has_healthy_index(workdir):
        # #203: a present-but-stale index (sources newer than the index)
        # self-heals here — the daemon would otherwise serve a stale graph.
        if index_is_stale(workdir):
            ok, detail = _run_codegraph_init(workdir, runner, cli_path, timeout)
            if ok:
                return {'status': 'ok', 'reason': 'index was stale; re-initialized'}
            return {'status': 'failed', 'reason': f'stale index refresh failed: {detail}'}
        return {'status': 'skipped', 'reason': None}
    ok, detail = _run_codegraph_init(workdir, runner, cli_path, timeout)
    if ok:
        return {'status': 'ok', 'reason': None}
    return {'status': 'failed', 'reason': detail}


def boot_hint(status: dict) -> str | None:
    """One-line system-prompt hint when boot failed, so the model doesn't
    retry codegraph tools that will keep failing. None when usable."""
    if status.get('status') != 'failed':
        return None
    reason = status.get('reason') or 'unknown reason'
    return (
        f'Note: codegraph is unavailable in this project ({reason}). '
        'Do NOT call codegraph tools or retry indexing — navigate with '
        'read/grep instead.'
    )


def ensure_codegraph_index(
    workdir: Path,
    runner=subprocess.run,
    cli_path: str | None = None,
    timeout: int = 300,
) -> str | None:
    """Run `codegraph init` when the workdir has no `.codegraph` index.

    Returns the CLI output, None when skipped or on any failure.
    `runner` is injectable for tests. Prefer `boot_codegraph` (status dict).
    """
    if _has_healthy_index(workdir):
        return None
    ok, detail = _run_codegraph_init(workdir, runner, cli_path, timeout)
    return detail if ok else None


def refresh_codegraph_index(
    workdir: Path,
    runner=subprocess.run,
    cli_path: str | None = None,
    timeout: int = 120,
) -> str | None:
    """Re-run `codegraph init` even when an index exists (R14 mid-run
    refresh): long sessions must not navigate stale code. Best-effort —
    None on any failure, never raises."""
    ok, detail = _run_codegraph_init(workdir, runner, cli_path, timeout)
    return detail if ok else None
