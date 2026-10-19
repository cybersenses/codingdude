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

import shutil
import subprocess
from pathlib import Path

# LocalAppData is the standard install location on Windows; resolve it
# from the environment so no user-specific path is baked into the source.
_FALLBACK_CMD = (
    Path.home() / 'AppData' / 'Local' / 'codegraph' / 'current' / 'bin' / 'codegraph.CMD'
)


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
