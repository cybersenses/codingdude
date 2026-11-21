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
"""R103: the floorplan boundary — locate floorplan, run its headless scripts,
hand back their receipts.

floorplan (`haydenschmitty/floorplan`, MIT, zero npm deps) draws a map of a
repo. It never calls a model: a model writes `architecture.json`,
`descriptions/<key>.json` and `recent-work.json`, and its scripts do the rest.
So the integration is a process boundary, not a re-implementation — no
analysis logic lives here, only locate -> run -> validate -> report.

Bounded by construction (#368's class): every call has a timeout and a timeout
is a readable failure, never an escaping `TimeoutExpired`. A missing copy or a
missing node is a readable reason, never an import-time or run-time crash — the
map is an aid, never a precondition for the run.

The payload ships with the repo (`vendor/floorplan`, pinned; see its
`VENDORED.md`), so this is a core capability with no configuration step: the
resolution order below is explicit > env > vendored, never "absent by default".

Its scanner is heuristic. On this repo in 2026-11-20 it reported a HIGH
"unprotected-endpoint" finding for an app whose 82 authorizing routes carry
`Depends(authorize)`, because its rule cannot see FastAPI dependency
injection. Callers surface its verdicts as *advisory* text.

**Where the map lives (decision #107).** Under the config home, not in the
project: `map_dir()` is `<config home>/maps/<slug>-<hash8>/`, keyed on the
resolved workdir. Upstream co-locates everything in `<root>/floorplan/` and
gitignores the whole folder, but a derived 3 MB page has no business inside
someone's repository — and with `--out` given, floorplan does not touch the
scanned root at all (`build.mjs:44` short-circuits, `scan.mjs:229` skips its own
gitignore). All four inputs (`architecture.json`, `descriptions/`,
`recent-work.json`, `scan.json`) are read from the out dir, so the map dir is
self-contained and moving it moves everything.
"""

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from .tools import _replace_with_retry, run_captured

#: Where a reader points us at a floorplan checkout, repo root or skills dir.
ENV_VAR = 'CODINGDUDE_FLOORPLAN_HOME'

#: Upstream's *packaging* directory name (`skills/floorplan`). It is not where a
#: build lands — see `map_dir()`. One constant, one meaning: this one describes
#: only the shape a checkout may arrive in.
SKILL_DIRNAME = 'floorplan'

#: Where every workdir's map dir lives, under the config home (decision #107).
MAPS_DIRNAME = 'maps'

SCAN_TIMEOUT = 120
BUILD_TIMEOUT = 180
PROBE_TIMEOUT = 15

#: Said once, because four call sites reported it: the dependency floorplan
#: needs and the reader does not have. `tests/test_floorplan.py` asserts this
#: string appears exactly once in this module.
NODE_MISSING = (
    'node is not on PATH — floorplan needs Node 18 or newer (https://nodejs.org)'
)

#: How old a build lock must be before it is presumed dead (#379). Both bounded
#: runs plus a margin, so a lock older than the longest possible build cannot
#: be live; honouring it would wedge the map until someone deleted a file.
LOCK_STALE_AFTER = SCAN_TIMEOUT + BUILD_TIMEOUT + 60

#: The scripts this adapter drives, and the only ones that must exist for the
#: copy to count as usable: a half-copied payload is rejected once, at locate
#: time, instead of failing three different ways.
#:
#: `query.mjs` is deliberately absent: `build.mjs` generates it into the map
#: output dir from `assets/query-cli.mjs`, so it exists only after a build. The
#: `map_query` tool (#378) reads it from there — requiring it here would reject
#: every fresh copy.
REQUIRED_SCRIPTS = ('scan.mjs', 'build.mjs')

#: The one input `build.mjs` cannot do without — floorplan has no default. Named
#: here so the author in `floorplan_inputs` and this module's default share one spelling.
ARCH_NAME = 'architecture.json'

#: `<map dir>/build.json` — the last settled build (#379).
#:
#: The build route returns the receipt when the pair settles inside its budget
#: and 202 when it does not; the file is what lets the polling reader say *why*
#: a build failed either way.
RECEIPT_NAME = 'build.json'

#: `<map dir>/graph.json` — the built graph, and the test for "a map exists".
#: `query.mjs` reads it from beside itself, so the two live or die together.
GRAPH_NAME = 'graph.json'

#: `<map dir>/query.mjs` — generated *by* the builder (`build.mjs:655`), which
#: is why `REQUIRED_SCRIPTS` does not list it: it only exists after a build.
QUERY_CLI = 'query.mjs'

#: One bounded call: a graph query is index-like, not analysis.
QUERY_TIMEOUT = 30

#: The verbs `query.mjs` answers, in its own spelling. Answered here so a typo
#: costs no subprocess, and so the error can list what is available.
QUERY_VERBS = ('overview', 'find', 'show', 'path')

#: `show` on a large node prints a lot; this is the tool-output discipline the
#: other tools follow, announced rather than silent when it bites.
QUERY_MAX_CHARS = 20_000


# --- #381: the exported copy the frame serves -------------------------------

#: `<map dir>/index.export.html` — floorplan's own *exported* copy of the map.
#:
#: `serve.mjs --export` re-serialises the built page with `meta.exported` set,
#: which is upstream's switch for "no Ask bar, no requests for Claude or Codex,
#: no links into this computer" (`serve.mjs:52-80`). The frame needs exactly
#: that: floorplan's Ask bar shells out to a `claude` or `codex` CLI this
#: adapter never runs, so served as built it renders a permanently disabled
#: control reading "Asking is unavailable" across the bottom of the diagram.
EXPORT_NAME = 'index.export.html'

#: What the sidecar is called. Same suffix `tools._atomic_write` uses (R24 #38),
#: so "a file we are mid-way through" has one spelling in this codebase.
EXPORT_TEMP_SUFFIX = '.codingdude-tmp'

#: What travels in that copy. `health` is left out on purpose: floorplan's
#: health scan is heuristic and flags a HIGH "unprotected-endpoint" on routes
#: that do carry `Depends(authorize)` (see this module's docstring), so showing
#: it in our own panel would present a verdict we know to be wrong as ours.
EXPORT_INCLUDE = 'flows,notes,recent'

#: `build.mjs` generates `serve.mjs` into the map dir (beside `query.mjs`), and
#: `--export` is the path through it that writes the copy and exits without
#: starting a server — the same code its Export button takes, so there is no
#: second implementation of the transform to keep in step.
EXPORT_SCRIPT = 'serve.mjs'
EXPORT_TIMEOUT = 60


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


@dataclass(frozen=True)
class QueryResult:
    """The answer to one map query: floorplan's JSON, or the sentence why not.

    `ok` is about *our* call (did the CLI answer), not about the graph's
    contents: a verb whose query matched nothing is a successful query with an
    empty result, and reporting it as a failure would teach a caller to retry
    something that is working.
    """

    ok: bool
    text: str = ''


def _vendor_default() -> Path:
    """`<repo>/vendor/floorplan` — the pinned copy this repo ships."""
    return Path(__file__).resolve().parents[2] / 'vendor' / 'floorplan'


def _floorplan_dir(candidate: Path) -> Path | None:
    """The directory holding floorplan's scripts under `candidate`, or None.

    Both shapes are accepted because both are natural to point at: the
    floorplan checkout itself, or the `skills/floorplan` directory upstream
    packages its scripts in (a plain directory here — our copy is not a skill).
    """
    for base in (candidate, candidate / 'skills' / SKILL_DIRNAME):
        if all((base / 'scripts' / name).is_file() for name in REQUIRED_SCRIPTS):
            return base
    return None


def floorplan_home(explicit: str | Path | None = None) -> Path | None:
    """Resolve the floorplan skills dir: explicit > env > vendored. None = absent.

    Returning None (never raising) is deliberate: the map is an aid, so a host
    without floorplan must degrade to "not available, here is why", not refuse
    to run.
    """
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    raw = os.environ.get(ENV_VAR)
    if raw:
        candidates.append(Path(raw))
    candidates.append(_vendor_default())
    for candidate in candidates:
        found = _floorplan_dir(candidate)
        if found is not None:
            return found
    return None


def unavailable_reason() -> str:
    """The message a caller shows when no floorplan checkout was found."""
    return (
        'floorplan is not available: no copy was found. Expected the vendored '
        f'copy at {_vendor_default()} (see its VENDORED.md), or a checkout '
        f'named by {ENV_VAR}. '
        'The map is an aid — everything else works without it.'
    )


def node_binary() -> str | None:
    """Path to `node`, or None. Presence only: floorplan wants node >= 18.

    Not a version probe: that would cost a spawn on every call to answer a
    question the spawn is about to answer anyway (a too-old node fails the
    script and the error is reported verbatim).
    """
    return shutil.which('node')


def maps_home(home: str | Path | None = None) -> Path:
    """`<config home>/maps` — the parent of every workdir's map dir (#107).

    `home` is the *config* home, matching `config.worker_log_path`'s parameter:
    callers that already hold one pass it, everything else gets the resolved
    default. Derived state does not go in the user's repository.
    """
    if home is not None:
        return Path(home) / MAPS_DIRNAME
    from .config import config_home

    return config_home() / MAPS_DIRNAME


def map_dir(workdir: str | Path, home: str | Path | None = None) -> Path:
    """`<config home>/maps/<slug>-<hash8>` — this workdir's map dir (#107).

    Keyed on the *resolved* path, case-folded before hashing, because Windows
    would otherwise give `G:\\Repo` and `g:\\repo` two map dirs — and a rebuild
    silently landing in a second directory is exactly the confusion a rebuild
    is meant to clear. The slug keeps it legible when a human lists the folder;
    the hash keeps it unique.
    """
    project = Path(workdir).resolve()
    digest = hashlib.sha256(str(project).casefold().encode('utf-8')).hexdigest()[:8]
    slug = re.sub(r'[^a-z0-9]+', '-', project.name.casefold()).strip('-') or 'workdir'
    return maps_home(home) / f'{slug}-{digest}'


def map_page(workdir: str | Path, home: str | Path | None = None) -> Path:
    """`<map dir>/index.html` — where a build puts the map (#377).

    One definition, because three places depend on the layout: the build itself,
    the server route that serves the page to the Map panel, and the query tool
    that reads the graph written beside it.
    """
    return map_dir(workdir, home) / 'index.html'


def map_graph(workdir: str | Path, home: str | Path | None = None) -> Path:
    """`<map dir>/graph.json` — the data behind the map (#378).

    `query.mjs` is generated beside it by the same build (`build.mjs:655,717`),
    so #378 reads one directory rather than re-deriving the layout.
    """
    return map_dir(workdir, home) / 'graph.json'


def map_frame_page(workdir: str | Path, home: str | Path | None = None) -> Path:
    """The page the Map panel serves: the exported copy when it is current (#381).

    `map_page()` is what the builder wrote; this is the projection of it a
    sandboxed frame can run without dead controls — the copy whose Ask bar is
    hidden because nothing here answers it.

    Falls back to the build's own page when the export is missing, or when it is
    not *provably* newer, and the second half carries the weight: a rebuild that
    wrote the page but not its copy must not leave the frame showing the previous
    build while the panel says "built". A tie is not proof of anything — coarse
    filesystem timestamps give a rebuild's page and the previous copy the same
    mtime — so a tie resolves to the build page. That costs the dead Ask bar,
    which is visible and honest, rather than a map that is not the one just
    built, which is neither.
    """
    page = map_page(workdir, home)
    export = page.with_name(EXPORT_NAME)
    try:
        page_mtime = page.stat().st_mtime_ns
        export_mtime = export.stat().st_mtime_ns
    except OSError:
        # Not an error to report: an entry that is not there is answered by the
        # fallback, and `_map_state` reports the absence of the page itself.
        return page
    return export if export_mtime > page_mtime else page


class MapLocked(RuntimeError):
    """A build for this workdir is already running (#379).

    A conflict rather than an error: two builds write the same output paths, so
    the second is refused instead of queued behind a wait nobody can bound.
    """


def lock_path(workdir: str | Path, home: str | Path | None = None) -> Path:
    """`<map dir>/build.lock` — one build per workdir at a time (#379)."""
    return map_dir(workdir, home) / 'build.lock'


def lock_stale(workdir: str | Path, home: str | Path | None = None) -> bool:
    """True when a lock exists but is older than any live build could be.

    Absent lock reads as not stale: `build_lock` creates first and asks second,
    so this is only ever consulted about a lock that already existed.
    """
    try:
        age = time.time() - lock_path(workdir, home).stat().st_mtime
    except OSError:
        return False
    return age > LOCK_STALE_AFTER


@contextmanager
def build_lock(workdir: str | Path, home: str | Path | None = None):
    """Hold this workdir's build lock, or raise `MapLocked` (#379).

    `touch(exist_ok=False)` makes the check and the claim one operation, so two
    simultaneous requests cannot both win. A stale lock is taken over rather
    than honoured: a build that died between the touch and the unlink would
    otherwise refuse every later build for ever, and the map is derived state —
    rebuilding it is always safe.
    """
    path = lock_path(workdir, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.touch(exist_ok=False)
    except FileExistsError:
        if not lock_stale(workdir, home):
            raise MapLocked(
                f'a map build is already running for {Path(workdir).resolve()}'
            ) from None
        path.touch()
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


async def available(probe_timeout: int = PROBE_TIMEOUT) -> tuple[bool, str]:
    """(usable, detail) — node answering, and a floorplan checkout to drive.

    The only availability answer in the codebase: `/map/state` awaits this, so
    the panel's `available`/`detail` and the adapter's own preconditions cannot
    disagree. The probe is bounded, and a node that never answers is a reason
    rather than a hang.
    """
    node = node_binary()
    if node is None:
        return False, NODE_MISSING
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


def export_temp(out_dir: str | Path) -> Path:
    """A fresh sidecar path for the export to write before it is published (#381).

    Unique per call, and shaped like the one `tools._atomic_write` uses (R24
    #38): a uuid so no two writers — this build, a leftover from a killed one —
    can collide on the name, and a suffix that is recognisably ours so litter
    can be told from a copy. Nothing is cleared on the way in, because clearing
    would be a step that can fail before the work starts (see `_export_page`).
    """
    return Path(out_dir) / f'{EXPORT_NAME}.{uuid.uuid4().hex}{EXPORT_TEMP_SUFFIX}'


async def _export_page(out_dir: Path, timeout: int = EXPORT_TIMEOUT) -> str:
    """Write `out_dir`'s exported copy. Returns why not, or '' on success (#381).

    A note, never a failed build: the map is drawn either way, and the copy only
    removes chrome the frame cannot use. A copy that could not be made is
    reported beside the build's own warnings and the build's page is served.

    Written to a fresh sidecar and published, because a half-written copy is
    worse than none: `map_frame_page()` serves whatever is newer than the
    build's page, so a partial one would be served as if it were a map.
    Publishing also keeps a rebuild's *previous* copy in place, which is older
    than the new page and therefore never served.

    The temp name is a fresh one per call (`export_temp`), so there is nothing
    to clear first: clearing a previous run's sidecar would be a cleanup step
    on the way *in* that can fail on Windows (`PermissionError` on a file
    something else holds open) and turn a build into an exception. Publishing
    goes through `tools._replace_with_retry` for the matching reason on the way
    *out*: the frame may be displaying the copy being replaced, and that lock
    is transient (R24 #38).
    """
    dest = out_dir / EXPORT_NAME
    tmp = export_temp(out_dir)
    node = node_binary()
    if node is None:
        return NODE_MISSING
    cap = await run_captured(
        [node, str(out_dir / EXPORT_SCRIPT), '--export', str(tmp),
         '--include', EXPORT_INCLUDE],
        cwd=out_dir, timeout=timeout)
    if cap is None:
        _discard(tmp)
        return f'the map was built, but its exported copy timed out after {timeout}s'
    if cap.code != 0 or not tmp.is_file():
        _discard(tmp)
        return ('the map was built, but its exported copy failed '
                f'(exit {cap.code}): {cap.combined[:200]}')
    if tmp.stat().st_size == 0:
        # Exit 0 is not proof a page was written. An empty copy would pass the
        # existence check above and render a blank frame, which is worse than
        # the Ask bar it exists to remove, so emptiness is the same class of
        # failure as a non-zero exit and the served name is left alone.
        _discard(tmp)
        return ('the map was built, but its exported copy came back empty '
                f'(exit 0): {cap.combined[:200]}')
    try:
        _replace_with_retry(tmp, dest)
    except OSError as exc:
        _discard(tmp)
        return f'the map was built, but its exported copy could not be published: {exc}'
    return ''


def _discard(path: Path) -> None:
    """Remove a copy that must not survive a failed export.

    Never raises: this runs on the way out of a failure, and a build that is
    otherwise complete must not be turned into an error by cleanup. The file is
    a sidecar nothing serves, so a removal that fails leaves only litter.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


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
            error=NODE_MISSING,
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

    `arch` and `scan` default to the files floorplan expects inside `out_dir`;
    a caller that writes an architecture file elsewhere (#376) passes its own.
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
            error=NODE_MISSING)
    argv = [str(workdir), '--out', str(out_dir), '--json', '--unattended']
    arch_path = Path(arch) if arch is not None else out_dir / 'architecture.json'
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


# --- #379: the trigger ------------------------------------------------------

@dataclass(frozen=True)
class MapBuild:
    """One scan+build pair, as the route and the tool report it (#379).

    Flat rather than nesting `ScanResult`/`BuildResult`: both callers want the
    counts, the warnings verbatim and one reason, and neither has a use for the
    intermediate objects once the pair has settled.
    """

    ok: bool
    error: str = ''
    warnings: tuple[str, ...] = ()
    counts: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    page: Path | None = None

    def summary(self) -> str:
        """What was mapped, and what did not match.

        Every warning is printed verbatim on both paths, not counted and not
        dropped when the build failed: each one names a field of
        `architecture.json` that matched no file, and a failure is exactly when
        a reader needs to know which field was wrong (#376).
        """
        if not self.ok:
            head = f'map build failed: {self.error}'
        else:
            counts = self.counts
            head = (
                f'map built: {counts.get("files", 0)} files, '
                f'{counts.get("edges", 0)} edges, '
                f'{counts.get("routes", 0)} routes, '
                f'{counts.get("externals", 0)} external packages'
            )
            if self.page is not None:
                head = f'{head} · {self.page}'
        return '\n'.join([head, *self.warnings])

    def as_dict(self) -> dict:
        """The receipt as a reader sees it — the POST body and `build.json`."""
        return {
            'ok': self.ok,
            'error': self.error,
            'warnings': list(self.warnings),
            'counts': dict(self.counts),
            'files': dict(self.files),
            'page': str(self.page) if self.page is not None else None,
        }

    def write(self, path: Path) -> None:
        """Record this attempt beside the map, for the reader that polls (#379).

        The route returns the receipt when the pair settles inside its budget,
        and 202 when it does not; without this file the second path could say
        "built" or "not built" but never *why* it failed, which is the only
        actionable part. Written on failure too.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**self.as_dict(), 'at': datetime.now(UTC).isoformat()}
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


async def _build_pair(
    workdir: Path, out_dir: Path, home: str | Path | None,
    arch: str | Path | None,
) -> MapBuild:
    """The scan+build pair itself, with the lock already held (#379).

    The order is the contract: scan, then *author* floorplan's three inputs from
    what the scan found, then build (#376). Authoring before the scan would have
    to guess the file list; authoring after it makes every glob in
    `architecture.json` a measurement, which is why "matches no included file"
    is now an authoring error instead of a receipt warning nobody reads.

    `arch` stays a caller's override for the rare reader that has its own
    architecture file: given one, the other two inputs are the caller's too,
    because half a map from one author and half from another is worse than
    either.
    """
    usable, detail = await available()
    if not usable:
        return MapBuild(ok=False, error=detail)
    scanned = await scan(workdir, out_dir, home=home)
    if not scanned.ok:
        return MapBuild(ok=False, error=scanned.error)
    arch_path = Path(arch) if arch is not None else out_dir / ARCH_NAME
    # The same five sizes the scan published, through the same projection that
    # filled `ScanResult` - one mapping, not a third copy of `_COUNT_KEYS`.
    counts = _scan_counts(scanned.scan_path, {}) if scanned.scan_path else {}
    notes: tuple[str, ...] = ()
    if arch is None:
        # Imported here rather than at module scope: `floorplan_inputs` reads
        # this module's map dir and arch filename, so a second module-scope
        # import would be a cycle.
        from .floorplan_inputs import author

        authored = author(workdir, home)
        if not authored.ok:
            return MapBuild(ok=False, error=authored.summary(), counts=counts)
        notes = authored.notes
    built = await build(
        workdir, out_dir, home=home, arch=arch_path,
        scan_path=scanned.scan_path,
    )
    page = built.index_html
    warnings = (*notes, *built.warnings)
    if built.ok:
        # The copy the frame serves (#381). Last, because it is a projection of
        # a page that has to exist first; and a note rather than a failure,
        # because a map without it is still a map.
        #
        # This names what the build *published*, which is not the same question
        # as what the route serves: `map_frame_page()` resolves per request and
        # requires the copy to be strictly newer, so a copy that tied on the
        # filesystem clock would leave the build page on screen while this field
        # still named the copy. Publishing is a fact; serving is a comparison.
        problem = await _export_page(out_dir)
        if problem:
            warnings = (*warnings, problem)
        else:
            page = out_dir / EXPORT_NAME
    return MapBuild(
        ok=built.ok,
        error=built.error,
        # Authored notes first: a reader asking "why is nothing highlighted"
        # should not have to scroll past the builder's own warnings to find out.
        warnings=warnings,
        counts=counts,
        files=built.files,
        page=page if built.ok else None,
    )


async def build_map(
    workdir: str | Path, home: str | Path | None = None,
    arch: str | Path | None = None,
) -> MapBuild:
    """Scan then build this workdir's map, holding the build lock (#379).

    Raises `MapLocked` when another build holds the lock: whether that is a 409
    or a sentence back to the agent is the caller's decision, and neither is a
    failure of this function.

    Nothing needs preparing first: `floorplan_inputs` authors the three files
    floorplan cannot derive (#376) as part of the pair, so the map is a
    capability of the checkout rather than a configuration step. Every settled
    attempt is recorded at `<map dir>/build.json`, because the caller may stop
    waiting long before this returns.
    """
    workdir = Path(workdir)
    with build_lock(workdir, home):
        out_dir = map_dir(workdir, home)
        outcome = await _build_pair(workdir, out_dir, home, arch)
        outcome.write(out_dir / RECEIPT_NAME)
        return outcome


def read_receipt(workdir: str | Path, home: str | Path | None = None) -> dict | None:
    """The last settled build for this workdir, or None (#379).

    Read from disk rather than remembered, because the build that wrote it may
    have outlived the request that asked for it: after a 202 the only surviving
    record of what happened is this file.
    """
    try:
        text = (map_dir(workdir, home) / RECEIPT_NAME).read_text(encoding='utf-8')
        payload = json.loads(text)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


# --- #378: querying the built map --------------------------------------------

async def query_map(
    workdir: str | Path, verb: str, text: str = '', kind: str = '',
    home: str | Path | None = None, timeout: int = QUERY_TIMEOUT,
) -> QueryResult:
    """One read-only lookup in the built map, through floorplan's own CLI.

    `query.mjs` is generated *into the map dir* by the builder, over
    `graph.json` beside it (decision #107), so this resolves one directory
    rather than a second copy of the layout. The two ways it can be missing are
    kept apart on purpose: no map means "build one", while a map without its
    CLI means the payload changed shape — answering "build one" there would
    send the reader to rebuild something that already exists.

    Read-only by construction: `query.mjs` has four verbs and every one of them
    reads. An unknown verb is answered here, from `QUERY_VERBS`, so a typo costs
    no subprocess.
    """
    wanted = (verb or '').strip().lower()
    if wanted not in QUERY_VERBS:
        return QueryResult(ok=False, text=(
            f'unknown verb "{verb}": the map answers '
            + ', '.join(QUERY_VERBS) + '.'))
    target = map_dir(workdir, home)
    graph = target / GRAPH_NAME
    cli = target / QUERY_CLI
    if not graph.is_file():
        return QueryResult(ok=False, text=(
            f'no map has been built for {Path(workdir).resolve()} yet — build one '
            'first (map_build, or Build in the Map panel).'))
    if not cli.is_file():
        return QueryResult(ok=False, text=(
            f'the built map has no {QUERY_CLI} at {cli}: the payload changed shape. '
            'Rebuild the map first; if the CLI is still missing, this floorplan '
            'copy no longer generates one.'))
    args, problem = _query_args(wanted, text, kind)
    if problem:
        return QueryResult(ok=False, text=problem)
    node = node_binary()
    if node is None:
        return QueryResult(ok=False, text=NODE_MISSING)
    cap = await run_captured(
        [node, str(cli), *args], cwd=target, timeout=timeout)
    if cap is None:
        return QueryResult(
            ok=False, text=f'the map query timed out after {timeout}s')
    if cap.code != 0:
        # `query.mjs` prints `{"error": ...}` and exits 1 when the graph query
        # itself fails, so that sentence is the answer, not a crash of ours.
        payload = _parse_receipt(cap.stdout)
        if payload is not None and 'error' in payload:
            return QueryResult(ok=False, text=json.dumps(payload))
        return QueryResult(
            ok=False,
            text=f'the map query failed (exit {cap.code}): {cap.combined[:400]}')
    return QueryResult(ok=True, text=_cap_text(cap.stdout))


def _query_args(verb: str, text: str, kind: str) -> tuple[list[str], str]:
    """The CLI argv for one verb, or the sentence saying what it needs."""
    words = (text or '').split()
    if verb == 'overview':
        return ['overview'], ''
    if verb == 'path':
        if len(words) != 2:
            return [], ('path needs two ids: pass them space-separated, '
                        '"path <from> <to>".')
        return ['path', *words], ''
    if not words:
        return [], f'{verb} needs a query: the node or file to look up.'
    if verb == 'show':
        return ['show', words[0]], ''
    args = ['find', ' '.join(words)]
    if kind:
        args += ['--kind', kind]
    return args, ''


def _cap_text(text: str) -> str:
    """The CLI's JSON, capped: `show` on a big node can be large.

    Truncation is announced rather than silent — a clipped JSON document that
    looks complete is worse than one that says it was cut.
    """
    body = text.strip()
    if len(body) <= QUERY_MAX_CHARS:
        return body
    return (body[:QUERY_MAX_CHARS].rstrip()
            + f'\n… truncated at {QUERY_MAX_CHARS} characters; ask for a narrower '
              'verb (find or show) to see the rest.')


def build_floorplan_toolset(workdir: Path):
    """The map tools: refresh the map, then read it without a browser.

    `map_build` is for the turn that already knows the map is stale, because a
    map built before the edit describes code that no longer exists. `map_query`
    is the half that makes *the agent* cheaper as well as the human better
    informed: the same graph that draws the picture answers "where does this
    live" in one call, instead of a search loop over the source.
    """
    from pydantic_ai.toolsets import FunctionToolset

    async def map_build() -> str:
        """Build the architecture map for this project and report the receipt.

        Runs floorplan's scan, then its builder, into this project's map
        directory under the config home — nothing is written inside the
        project. Returns file and route counts plus every warning verbatim; a
        warning names a field of `architecture.json` that matched no file.
        """
        try:
            outcome = await build_map(workdir)
        except MapLocked as exc:
            # A conflict is a sentence, not an exception: the agent may simply
            # have raced the panel's button, and aborting its turn for that
            # would cost more than waiting.
            return f'not started: {exc}'
        return outcome.summary()

    async def map_query(verb: str, query: str = '', kind: str = '') -> str:
        """Look something up in this project's built architecture map.

        Read-only. `verb` is one of overview, find, show, path:
        overview is hosts, nodes and file counts; find locates a node or file by
        text (optionally `kind` = module | file | endpoint | symbol); show
        details one id's files, routes and dependencies; path traces the
        dependency chain between two ids, passed space-separated as
        "from to". Answers in JSON. Passes through to floorplan's own graph
        query, so it is the same answer the map renders.
        """
        result = await query_map(workdir, verb, query, kind)
        return result.text

    return FunctionToolset([map_build, map_query])

