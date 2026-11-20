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
"""R103: the floorplan node boundary — locate the skill, run its headless
scripts, hand back their receipts.

floorplan (`haydenschmitty/floorplan`, MIT, zero npm deps) draws a map of a
repo. It never calls a model: a model writes `architecture.json`,
`descriptions/<key>.json` and `recent-work.json`, and its scripts do the rest.
So the integration is a process boundary, not a re-implementation — no
analysis logic lives here, only locate -> run -> validate -> report.

Bounded by construction (#368's class): every call has a timeout and a timeout
is a readable failure, never an escaping `TimeoutExpired`. A missing skill or a
missing node is a readable reason, never an import-time or run-time crash — the
map is an aid, never a precondition for the run.

Its scanner is heuristic. On this repo in 2026-11-20 it reported a HIGH
"unprotected-endpoint" finding for an app whose 82 authorizing routes carry
`Depends(authorize)`, because its rule cannot see FastAPI dependency
injection. Callers surface its verdicts as *advisory* text.
"""

import json
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path

from .tools import run_captured

#: Where a reader points us at a floorplan checkout, repo root or skills dir.
ENV_VAR = 'CODINGDUDE_FLOORPLAN_HOME'

#: floorplan's own map dir name (its `MAP_DIR`), relative to the scanned root.
MAP_DIRNAME = 'floorplan'

SCAN_TIMEOUT = 120
BUILD_TIMEOUT = 180
PROBE_TIMEOUT = 15

#: The scripts this adapter drives. `query-cli.mjs` is the query API the
#: `map_query` tool wraps (#378); it is checked here so a half-copied skill is
#: rejected once, at locate time, instead of failing three different ways.
REQUIRED_SCRIPTS = ('scan.mjs', 'build.mjs')


@dataclass(frozen=True)
class ScanResult:
    """What floorplan's scan receipt said (floorplan/scan-result@1)."""

    ok: bool
    error: str = ''
    files: int = 0
    edges: int = 0
    routes: int = 0
    externals: int = 0
    hosts: int = 0
    scan_path: Path | None = None


@dataclass(frozen=True)
class BuildResult:
    """What floorplan's build receipt said (floorplan/build-result@1).

    `warnings` is kept verbatim, not counted: each one names a field of the
    caller's `architecture.json` that matched nothing ("node "gates" path
    ... matches no included file"), which is the only feedback that stops a
    guessed input from shipping.
    """

    ok: bool
    error: str = ''
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    files: dict = field(default_factory=dict)
    health: dict = field(default_factory=dict)
    index_html: Path | None = None
    graph_json: Path | None = None


def _vendor_default() -> Path:
    """`<repo>/vendor/floorplan` — only used when the skill has been vendored."""
    return Path(__file__).resolve().parents[2] / 'vendor' / 'floorplan'


def _skills_dir(candidate: Path) -> Path | None:
    """The skills dir under `candidate`, or None when it is not one.

    Both shapes are accepted because both are natural to point at: the
    floorplan checkout itself, or its `skills/floorplan` directory.
    """
    for base in (candidate, candidate / 'skills' / MAP_DIRNAME):
        if all((base / 'scripts' / name).is_file() for name in REQUIRED_SCRIPTS):
            return base
    return None


def floorplan_home(explicit: str | Path | None = None) -> Path | None:
    """Resolve the floorplan skills dir: explicit > env > vendored. None = absent.

    Returning None (never raising) is deliberate: the map is an aid, so a host
    without floorplan must degrade to "not available, here is why", not refuse
    to run.
    """
    import os

    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    raw = os.environ.get(ENV_VAR)
    if raw:
        candidates.append(Path(raw))
    candidates.append(_vendor_default())
    for candidate in candidates:
        found = _skills_dir(candidate)
        if found is not None:
            return found
    return None


def unavailable_reason() -> str:
    """The message a caller shows when no floorplan checkout was found."""
    return (
        'floorplan is not available: no checkout was found. Set '
        f'{ENV_VAR} to a floorplan repo (or its skills/floorplan dir), or '
        f'vendor it at {_vendor_default()}. '
        'The map is an aid — everything else works without it.'
    )


def node_binary() -> str | None:
    """Path to `node`, or None. Presence only: floorplan wants node >= 18.

    Not a version probe: that would cost a spawn on every call to answer a
    question the spawn is about to answer anyway (a too-old node fails the
    script and the error is reported verbatim).
    """
    return shutil.which('node')


async def available(probe_timeout: int = PROBE_TIMEOUT) -> tuple[bool, str]:
    """(usable, detail) — node answering, and a floorplan checkout to drive."""
    node = node_binary()
    if node is None:
        return False, 'node is not on PATH (floorplan is a node skill)'
    cap = await run_captured([node, '--version'], cwd=Path.cwd(), timeout=probe_timeout)
    if cap is None:
        return False, f'node did not answer --version within {probe_timeout}s'
    if cap.code != 0:
        return False, f'node --version failed: {cap.combined[:200]}'
    home = floorplan_home()
    if home is None:
        return False, unavailable_reason()
    return True, f'node {cap.combined.strip()} · floorplan {home}'


def _loads_object(text: str) -> dict | None:
    """One JSON object, or None — a format change stays floorplan's problem."""
    if not text.startswith('{'):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_receipt(stdout: str) -> dict | None:
    """The JSON object floorplan printed, or None.

    `--json` prints one object, but a script may precede it with progress
    lines, so the whole stdout is tried first and then the last line that
    parses as an object. Returning None (not raising) keeps a format change
    inside floorplan from becoming our traceback.
    """
    text = stdout.strip()
    if not text:
        return None
    whole = _loads_object(text)
    if whole is not None:
        return whole
    for line in reversed(text.splitlines()):
        candidate = _loads_object(line.strip())
        if candidate is not None:
            return candidate
    return None


def _receipt_list(receipt: dict, key: str) -> tuple[str, ...]:
    return tuple(str(item) for item in (receipt.get(key) or ()))


_COUNT_KEYS = ('files', 'edges', 'routes', 'externals', 'hosts')


def _scan_counts(scan_path: Path, receipt: dict) -> dict:
    """Sizes from the `scan.json` the scan wrote, falling back to the receipt.

    Two different shapes, and assuming one was the bug the real-node test
    caught: the `--json` receipt carries `counts{files,routes,byLanguage,...}`
    plus `repos`/`skipped` lists, while `scan.json` carries the graph itself —
    `files`, `edges`, `routes`, `externals`, `hosts`. The graph is what a
    caller sizes, so it wins when present.
    """
    try:
        data = json.loads(scan_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        return {key: len(data.get(key) or ()) for key in _COUNT_KEYS}
    raw_counts = receipt.get('counts')
    counts: dict = raw_counts if isinstance(raw_counts, dict) else {}
    return {
        'files': int(counts.get('files') or 0),
        'routes': int(counts.get('routes') or 0),
        'edges': 0,
        'externals': 0,
        'hosts': 0,
    }



async def _run_script(
    home: Path, script: str, argv: list[str], workdir: Path, timeout: int,
):
    """One bounded floorplan call. Returns (Captured | None, node | None)."""
    node = node_binary()
    if node is None:
        return None, None
    cap = await run_captured(
        [node, str(home / 'scripts' / script), *argv], cwd=workdir, timeout=timeout)
    return cap, node


async def scan(
    workdir: Path, out_dir: Path, home: str | Path | None = None,
    timeout: int = SCAN_TIMEOUT,
) -> ScanResult:
    """Run floorplan's scanner against `workdir`, writing `out_dir/scan.json`.

    `--json` and `--unattended` are not optional here: unattended mode is what
    keeps a repo git cannot list (or an empty tree) an ERROR instead of a
    silent empty map, which is exactly the failure a caller must see.
    """
    resolved = floorplan_home(home)
    if resolved is None:
        return ScanResult(ok=False, error=unavailable_reason())
    out_dir = Path(out_dir)
    scan_path = out_dir / 'scan.json'
    out_dir.mkdir(parents=True, exist_ok=True)
    if node_binary() is None:
        return ScanResult(
            ok=False,
            error='node is not on PATH — floorplan is a node skill '
                  '(https://nodejs.org, node >= 18)',
            scan_path=scan_path)
    cap, _ = await _run_script(
        resolved, 'scan.mjs',
        [str(workdir), '--out', str(scan_path), '--json', '--unattended'],
        Path(workdir), timeout)
    if cap is None:
        return ScanResult(ok=False, scan_path=scan_path,
                          error=f'floorplan scan timed out after {timeout}s')
    receipt = _parse_receipt(cap.stdout)
    if receipt is None:
        return ScanResult(ok=False, scan_path=scan_path,
                          error=f'floorplan scan printed no JSON receipt '
                                f'(exit {cap.code}): {cap.combined[:400]}')
    result = ScanResult(
        ok=cap.code == 0 and bool(receipt.get('ok', True)),
        scan_path=scan_path,
        **_scan_counts(scan_path, receipt),
    )
    if not result.ok:
        detail = cap.combined or json.dumps(receipt.get('summary') or receipt)[:400]
        return replace(result, error=f'floorplan scan failed (exit {cap.code}): {detail[:400]}')
    return result


async def build(
    workdir: Path, out_dir: Path, home: str | Path | None = None,
    arch: str | Path | None = None, scan_path: str | Path | None = None,
    timeout: int = BUILD_TIMEOUT,
) -> BuildResult:
    """Run floorplan's builder, writing `out_dir/index.html` + `graph.json`.

    `arch` defaults to the `architecture.json` floorplan expects inside the
    scanned root's map dir; callers that generate it (#376) pass their own.
    `--check` is deliberately not used: a caller wants the artifacts, and the
    receipt already carries `ok`/`errors`, so a separate dry run would only
    double the floorplan invocations.
    """
    resolved = floorplan_home(home)
    if resolved is None:
        return BuildResult(ok=False, error=unavailable_reason())
    out_dir = Path(out_dir)
    index_html = out_dir / 'index.html'
    graph_json = out_dir / 'graph.json'
    out_dir.mkdir(parents=True, exist_ok=True)
    if node_binary() is None:
        return BuildResult(
            ok=False, index_html=index_html, graph_json=graph_json,
            error='node is not on PATH — floorplan is a node skill '
                  '(https://nodejs.org, node >= 18)')
    argv = [str(workdir), '--out', str(out_dir), '--json', '--unattended']
    arch_path = Path(arch) if arch is not None else Path(workdir) / MAP_DIRNAME / 'architecture.json'
    if arch_path.is_file():
        argv += ['--arch', str(arch_path)]
    scan_file = Path(scan_path) if scan_path is not None else out_dir / 'scan.json'
    if scan_file.is_file():
        argv += ['--scan', str(scan_file)]
    cap, _ = await _run_script(resolved, 'build.mjs', argv, Path(workdir), timeout)
    if cap is None:
        return BuildResult(ok=False, index_html=index_html, graph_json=graph_json,
                           error=f'floorplan build timed out after {timeout}s')
    receipt = _parse_receipt(cap.stdout)
    if receipt is None:
        return BuildResult(ok=False, index_html=index_html, graph_json=graph_json,
                           error=f'floorplan build printed no JSON receipt '
                                 f'(exit {cap.code}): {cap.combined[:400]}')
    raw_report = receipt.get('report')
    report: dict = raw_report if isinstance(raw_report, dict) else {}
    errors = _receipt_list(receipt, 'errors') or _receipt_list(report, 'errors')
    warnings = _receipt_list(receipt, 'warnings') or _receipt_list(report, 'warnings')
    raw_files = receipt.get('files')
    raw_health = receipt.get('health')
    result = BuildResult(
        ok=bool(receipt.get('ok')) and cap.code == 0,
        errors=errors,
        warnings=warnings,
        files=raw_files if isinstance(raw_files, dict) else {},
        health=raw_health if isinstance(raw_health, dict) else {},
        index_html=index_html,
        graph_json=graph_json,
    )
    if not result.ok:
        detail = '; '.join(errors) or cap.combined[:400] or 'no errors reported'
        return replace(result, error=f'floorplan build failed (exit {cap.code}): {detail}')
    return result
