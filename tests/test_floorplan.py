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
"""R103 #375: the floorplan boundary — bounded, degrading, never a hang.

The mocked seam is the real one: `floorplan.run_captured` is the subprocess
boundary, so the unit tests are about *our* decisions (which argv, what a
timeout means, what a missing copy means), not about floorplan's scanner.
The integration test runs the real thing, skipped only when the vendored copy
or node is genuinely absent.
"""

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from codingdude import floorplan
from codingdude.tools import Captured


def _copy_tree(root: Path) -> Path:
    """A fake floorplan copy: the two required scripts, no node needed.

    Laid out the way upstream packages it (`skills/floorplan/`), because that
    is one of the two shapes `floorplan_home` accepts. Nothing here is a skill
    — the directory name is upstream's, not ours.
    """
    scripts = root / 'skills' / 'floorplan' / 'scripts'
    # Idempotent: `build_map` asks `floorplan_home()` twice (once to answer
    # availability, once per script run), so a fixture that could only be built
    # once would fail on the second question, not on the code under test.
    scripts.mkdir(parents=True, exist_ok=True)
    for name in floorplan.REQUIRED_SCRIPTS:
        (scripts / name).write_text('// stub\n', encoding='utf-8')
    return root / 'skills' / 'floorplan'


def _scan_receipt(files: int = 3, routes: int = 1) -> str:
    """The real `--json` receipt shape: counts and repo/skip lists, no graph."""
    return json.dumps({
        'schema': 'floorplan/scan-result@1',
        'ok': True,
        'counts': {'files': files, 'routes': routes},
        'repos': [],
        'skipped': [],
        'summary': 'scan summary text',
    })


def _build_receipt(ok: bool = True, errors: list | None = None,
                   warnings: list | None = None) -> str:
    return json.dumps({
        'schema': 'floorplan/build-result@1',
        'ok': ok,
        'errors': errors or [],
        'warnings': warnings or [],
        'files': {'total': 357, 'unassigned': 109, 'unassignedPercent': 30.5},
        'health': {'high': 1, 'medium': 0, 'low': 1},
        'report': 'BUILD ok',
    })


class _Recorder:
    """Captures the argv our adapter builds, so flags are asserted not assumed.

    `graph` is what the real scan writes to `--out`: the adapter reads sizes
    from that artifact, so a fake that only printed a receipt would test the
    wrong source of truth.
    """

    def __init__(self, *, stdout: str = '', code: int = 0, stderr: str = '',
                 timeout: bool = False, graph: dict | None = None):
        self.calls: list[tuple[list[str], int]] = []
        self._stdout = stdout
        self._code = code
        self._stderr = stderr
        self._timeout = timeout
        self._graph = graph

    async def __call__(self, argv, *, cwd=None, timeout=60, **kwargs):
        self.calls.append((list(argv), timeout))
        if self._timeout:
            return None
        if self._graph is not None and '--out' in argv:
            out = Path(argv[argv.index('--out') + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(self._graph), encoding='utf-8')
        return Captured(code=self._code, stdout=self._stdout, stderr=self._stderr)


def _graph(files: int = 3, edges: int = 2, routes: int = 1,
           externals: int = 5, hosts: int = 2,
           category: str = 'code') -> dict:
    """The scan.json shape: the graph itself, indexed by these five lists.

    `category` matters now that the pair authors its own inputs (#376): the
    author derives every glob from the files the scan says are on the board, so
    an entry without one is a file the map never shows.
    """
    return {
        'files': [
            {'path': f'src/a{i}.py', 'category': category, 'lang': 'python', 'loc': 1}
            for i in range(files)
        ],
        'edges': [{} for _ in range(edges)],
        'routes': [{} for _ in range(routes)],
        'externals': [{} for _ in range(externals)],
        'hosts': [{} for _ in range(hosts)],
    }


# --- location ---------------------------------------------------------------

def test_home_prefers_the_explicit_path_over_env_and_vendor(tmp_path, monkeypatch):
    explicit = _copy_tree(tmp_path / 'explicit')
    from_env = _copy_tree(tmp_path / 'from-env')
    monkeypatch.setenv(floorplan.ENV_VAR, str(from_env))
    assert floorplan.floorplan_home(explicit) == explicit


def test_home_falls_back_to_the_env_var(tmp_path, monkeypatch):
    from_env = _copy_tree(tmp_path / 'from-env')
    monkeypatch.setenv(floorplan.ENV_VAR, str(from_env))
    assert floorplan.floorplan_home() == from_env


def test_home_accepts_a_repo_root_and_finds_skills_inside_it(tmp_path, monkeypatch):
    repo = _copy_tree(tmp_path / 'fp-repo')
    monkeypatch.delenv(floorplan.ENV_VAR, raising=False)
    # The checkout root is as legitimate a thing to point at as the skills dir.
    assert floorplan.floorplan_home(repo.parent.parent) == repo


def test_home_is_none_when_nothing_carries_the_scripts(tmp_path, monkeypatch):
    """No env var, no vendored copy: the honest "nothing to drive" case.

    The vendored default is neutralised explicitly — since `vendor/floorplan`
    ships with the repo, "point the env var at an empty dir" would now fall
    through to a real copy and test the wrong thing.
    """
    empty = tmp_path / 'empty'
    empty.mkdir()
    monkeypatch.setenv(floorplan.ENV_VAR, str(empty))
    monkeypatch.setattr(floorplan, '_vendor_default', lambda: tmp_path / 'no-vendor')
    assert floorplan.floorplan_home() is None


def test_the_vendored_copy_is_the_default_and_matches_its_checksums(monkeypatch):
    """Core, not optional: with no argument and no env var, the repo's own
    pinned copy is what resolves — and its CHECKSUMS file still describes it,
    so an upstream update that forgets to regenerate that file fails here
    instead of shipping a copy that silently differs from its stated pin."""
    import hashlib

    monkeypatch.delenv(floorplan.ENV_VAR, raising=False)
    home = floorplan.floorplan_home()
    assert home == floorplan._vendor_default()
    lines = (home / 'CHECKSUMS.sha256').read_text(encoding='utf-8').splitlines()
    assert len(lines) > 50, f'only {len(lines)} checksum lines'
    mismatched = []
    for line in lines:
        expected, rel = line.split('  ', 1)
        actual = hashlib.sha256((home / rel).read_bytes()).hexdigest()
        if actual != expected:
            mismatched.append(rel)
    assert mismatched == []


def test_unavailable_reason_names_the_knobs_a_reader_can_turn():
    reason = floorplan.unavailable_reason()
    assert floorplan.ENV_VAR in reason
    assert 'vendor' in reason


# --- scan -------------------------------------------------------------------

async def test_scan_runs_headless_with_json_and_unattended(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    recorder = _Recorder(stdout=_scan_receipt())
    monkeypatch.setattr(floorplan, 'run_captured', recorder)
    await floorplan.scan(tmp_path, tmp_path / 'out', home=home)
    argv, _ = recorder.calls[0]
    assert '--json' in argv and '--unattended' in argv
    assert '--out' in argv
    assert argv[argv.index('--out') + 1].endswith('scan.json')


async def test_scan_reports_the_graph_counts_from_the_scan_artifact(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'run_captured',
                        _Recorder(stdout=_scan_receipt(files=621, routes=88),
                                  graph=_graph(files=621, edges=848, routes=88,
                                               externals=50, hosts=60)))
    result = await floorplan.scan(tmp_path, tmp_path / 'out', home=home)
    assert result.ok is True
    assert (result.files, result.edges, result.routes,
            result.externals, result.hosts) == (621, 848, 88, 50, 60)


async def test_scan_falls_back_to_the_receipts_counts(tmp_path, monkeypatch):
    """No scan.json on disk (a scan that stopped early): the printed receipt
    still answers the two questions it can, and the graph-only counts are 0
    rather than invented."""
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'run_captured',
                        _Recorder(stdout=_scan_receipt(files=7, routes=2)))
    result = await floorplan.scan(tmp_path, tmp_path / 'out', home=home)
    assert result.ok is True
    assert (result.files, result.routes) == (7, 2)
    assert (result.edges, result.externals, result.hosts) == (0, 0, 0)


async def test_scan_timeout_names_the_bound_instead_of_raising(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'run_captured', _Recorder(timeout=True))
    result = await floorplan.scan(tmp_path, tmp_path / 'out', home=home, timeout=7)
    assert result.ok is False
    assert '7s' in result.error and 'timed out' in result.error


async def test_scan_failure_carries_floorplan_stderr(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'run_captured',
                        _Recorder(code=1, stderr='no files at all'))
    result = await floorplan.scan(tmp_path, tmp_path / 'out', home=home)
    assert result.ok is False
    assert 'no files at all' in result.error


async def test_scan_without_a_receipt_is_a_readable_error(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'run_captured',
                        _Recorder(code=0, stdout='scanning... done'))
    result = await floorplan.scan(tmp_path, tmp_path / 'out', home=home)
    assert result.ok is False
    assert 'receipt' in result.error


async def test_scan_without_floorplan_returns_the_reason(tmp_path, monkeypatch):
    monkeypatch.setenv(floorplan.ENV_VAR, str(tmp_path / 'nope'))
    monkeypatch.setattr(floorplan, '_vendor_default', lambda: tmp_path / 'no-vendor')
    result = await floorplan.scan(tmp_path, tmp_path / 'out')
    assert result.ok is False
    assert floorplan.ENV_VAR in result.error


async def test_scan_without_node_says_so(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'node_binary', lambda: None)
    result = await floorplan.scan(tmp_path, tmp_path / 'out', home=home)
    assert result.ok is False
    assert 'node' in result.error.lower()


# --- build ------------------------------------------------------------------

async def test_build_keeps_every_warning_verbatim(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    warnings = [
        'node "worker" path "src/codingdude/engine_entry.py" matches no included file',
        'node "gates" path "src/codingdude/claim_check.py" matches no included file',
    ]
    monkeypatch.setattr(floorplan, 'run_captured',
                        _Recorder(stdout=_build_receipt(warnings=warnings)))
    result = await floorplan.build(tmp_path, tmp_path / 'out', home=home)
    assert result.ok is True
    # The build's per-field warnings ARE the receipt: swallowing one is how a
    # guessed architecture.json ships silently (the probe produced 5 of them).
    assert list(result.warnings) == warnings


async def test_build_exit_1_is_reported_with_its_errors(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'run_captured',
                        _Recorder(code=1,
                                  stdout=_build_receipt(ok=False,
                                                        errors=['no node nodes'])))
    result = await floorplan.build(tmp_path, tmp_path / 'out', home=home)
    assert result.ok is False
    assert 'no node nodes' in result.error


async def test_build_points_at_the_files_it_wrote(tmp_path, monkeypatch):
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'run_captured',
                        _Recorder(stdout=_build_receipt()))
    out = tmp_path / 'out'
    result = await floorplan.build(tmp_path, out, home=home)
    assert result.index_html == out / 'index.html'
    assert result.graph_json == out / 'graph.json'


async def test_build_reads_its_architecture_from_the_out_dir(tmp_path, monkeypatch):
    """`build.mjs:45` defaults `--arch` to `outDir/architecture.json`, and the
    out dir is the map dir (decision #107). The adapter must agree with it, or
    the inputs #376 writes would never be found."""
    home = _copy_tree(tmp_path / 'fp')
    out = tmp_path / 'out'
    out.mkdir()
    recorder = _Recorder(stdout=_build_receipt())
    monkeypatch.setattr(floorplan, 'run_captured', recorder)

    await floorplan.build(tmp_path, out, home=home)
    argv, _ = recorder.calls[0]
    # Nothing authored yet: pass no flag and let floorplan name the file it wants.
    assert '--arch' not in argv

    (out / 'architecture.json').write_text('{}', encoding='utf-8')
    await floorplan.build(tmp_path, out, home=home)
    argv, _ = recorder.calls[1]
    assert argv[argv.index('--arch') + 1] == str(out / 'architecture.json')


# --- the real thing ---------------------------------------------------------

def _real_home() -> Path | None:
    return floorplan.floorplan_home()


@pytest.mark.skipif(_real_home() is None, reason='floorplan is not installed here')
async def test_scan_a_fixture_repo_with_the_real_node(tmp_path):
    repo = tmp_path / 'fixture'
    (repo / 'src').mkdir(parents=True)
    (repo / 'src' / 'a.py').write_text('import os\n', encoding='utf-8')
    (repo / 'src' / 'b.py').write_text('from src import a\n', encoding='utf-8')
    (repo / 'README.md').write_text('# fixture\n', encoding='utf-8')
    result = await floorplan.scan(repo, tmp_path / 'out')
    assert result.ok is True, result.error
    assert result.files >= 3
    assert (tmp_path / 'out' / 'scan.json').is_file()
    # The adapter writes nothing into the scanned tree.
    assert sorted(p.name for p in repo.iterdir()) == ['README.md', 'src']


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
async def test_available_probes_node_and_names_the_copy(tmp_path, monkeypatch):
    """The node probe runs for real (bounded); the copy is stubbed so the test
    does not depend on the vendored checkout being present."""
    home = _copy_tree(tmp_path / 'fp')
    monkeypatch.setattr(floorplan, 'floorplan_home', lambda *a, **k: home)
    ok, detail = await floorplan.available()
    assert ok is True, detail
    assert detail.startswith('node ')
    assert str(home) in detail


async def test_available_without_node_names_the_dependency(monkeypatch):
    monkeypatch.setattr(floorplan, 'node_binary', lambda: None)
    ok, detail = await floorplan.available()
    assert ok is False
    assert 'node' in detail.lower()


# --- where the map lives (decision #107) ------------------------------------

def test_the_map_dir_is_under_the_config_home_and_never_in_the_project(tmp_path):
    """A build must not be able to dirty the repository it maps."""
    project = tmp_path / 'proj'
    project.mkdir()
    home = tmp_path / 'home'

    page = floorplan.map_page(project, home)
    assert page.parent.parent == home / 'maps'
    assert page.name == 'index.html'
    assert project not in page.parents
    assert floorplan.map_graph(project, home) == page.parent / 'graph.json'


def test_the_map_dir_key_is_stable_and_case_folded(tmp_path):
    """One workdir, one map dir. On Windows `G:\\Repo` and `g:\\repo` are the
    same project, and two map dirs would make a rebuild look like a no-op."""
    home = tmp_path / 'home'
    project = tmp_path / 'Repo'
    project.mkdir()

    first = floorplan.map_dir(project, home)
    assert floorplan.map_dir(project, home) == first
    assert floorplan.map_dir(Path(str(project).upper()), home) == first
    assert first.name.startswith('repo-')
    assert len(first.name.rsplit('-', 1)[1]) == 8


def test_same_named_projects_in_different_places_get_different_map_dirs(tmp_path):
    home = tmp_path / 'home'
    one = tmp_path / 'a' / 'proj'
    two = tmp_path / 'b' / 'proj'
    one.mkdir(parents=True)
    two.mkdir(parents=True)

    assert floorplan.map_dir(one, home) != floorplan.map_dir(two, home)
    assert floorplan.map_dir(one, home).name.startswith('proj-')


# --- #379: availability, and where its one answer lives ---------------------

def test_availability_is_the_one_answer_and_it_names_the_missing_dependency(monkeypatch):
    monkeypatch.setattr(floorplan, 'node_binary', lambda: None)
    ok, detail = asyncio.run(floorplan.available())
    assert ok is False
    assert 'node' in detail.lower()
    assert detail == floorplan.NODE_MISSING


def test_availability_names_the_missing_copy(tmp_path, monkeypatch):
    async def node_answers(argv, **kwargs):
        return Captured(code=0, stdout='v22.0.0\n', stderr='')

    monkeypatch.setattr(floorplan, 'node_binary', lambda: 'node')
    monkeypatch.setattr(floorplan, 'run_captured', node_answers)
    monkeypatch.setattr(floorplan, 'floorplan_home', lambda *a, **k: None)
    ok, detail = asyncio.run(floorplan.available())
    assert ok is False
    assert detail == floorplan.unavailable_reason()


def test_there_is_exactly_one_availability_function():
    """The state route used to ask a second, cheaper copy of this question, and
    two answers to "can we build" is how they drift apart. One name, awaited by
    the panel's route and by `build_map` alike."""
    src = Path(floorplan.__file__).read_text(encoding='utf-8')
    assert src.count('async def available(') == 1
    assert 'def check_available(' not in src


def test_the_missing_node_message_has_one_source():
    """It used to be spelled out at four call sites. One string now, so a
    reader who greps the message finds every place that reports it."""
    src = Path(floorplan.__file__).read_text(encoding='utf-8')
    assert src.count('node is not on PATH') == 1


# --- #379: one build at a time ----------------------------------------------

def _proj(parent: Path, name: str = 'proj') -> Path:
    proj = parent / name
    proj.mkdir(parents=True)
    return proj


def test_a_second_build_for_the_same_project_is_refused(tmp_path):
    proj, home = _proj(tmp_path), tmp_path / 'home'
    with floorplan.build_lock(proj, home):
        with pytest.raises(floorplan.MapLocked):
            with floorplan.build_lock(proj, home):
                pass


def test_the_lock_is_released_even_when_the_build_raises(tmp_path):
    """A lock leaked on the error path would refuse every later build."""
    proj, home = _proj(tmp_path), tmp_path / 'home'
    with pytest.raises(RuntimeError):
        with floorplan.build_lock(proj, home):
            raise RuntimeError('boom')
    assert not floorplan.lock_path(proj, home).exists()
    with floorplan.build_lock(proj, home):
        pass


def test_a_lock_left_behind_by_a_dead_build_is_taken_over(tmp_path):
    """A lock with no staleness rule wedges the map for ever — the wedge class
    #368 removed. Past the sum of both timeouts plus a margin, the next build
    takes it rather than refusing until someone deletes a file by hand."""
    proj, home = _proj(tmp_path), tmp_path / 'home'
    path = floorplan.lock_path(proj, home)
    path.parent.mkdir(parents=True)
    path.touch()
    old = time.time() - floorplan.LOCK_STALE_AFTER - 1
    os.utime(path, (old, old))

    assert floorplan.lock_stale(proj, home) is True
    with floorplan.build_lock(proj, home):
        assert path.exists()


def test_a_fresh_lock_is_never_taken_over(tmp_path):
    proj, home = _proj(tmp_path), tmp_path / 'home'
    with floorplan.build_lock(proj, home):
        assert floorplan.lock_stale(proj, home) is False


def test_two_projects_never_share_a_lock(tmp_path):
    home = tmp_path / 'home'
    one, two = _proj(tmp_path, 'one'), _proj(tmp_path, 'two')
    with floorplan.build_lock(one, home):
        assert floorplan.lock_stale(two, home) is False
        with floorplan.build_lock(two, home):
            pass


# --- #379: the scan+build pair ----------------------------------------------

class _PairRecorder:
    """Two receipts, one per script, because the pair is scan *then* build.

    `graph` is still written for a scan: the adapter sizes the scan from the
    artifact, not from the printed counts, so a fake that skipped it would test
    the wrong source of truth (the bug the real-node probe caught).
    """

    def __init__(self, *, scan_stdout: str | None = None,
                 build_stdout: str | None = None, scan_code: int = 0,
                 build_code: int = 0, graph: dict | None = None,
                 scan_error: str = '', serve_code: int = 0,
                 serve_stdout: str = 'Exported the map'):
        self.calls: list[tuple[str, list[str]]] = []
        self._scan = _scan_receipt() if scan_stdout is None else scan_stdout
        self._build = _build_receipt() if build_stdout is None else build_stdout
        self._scan_code = scan_code
        self._build_code = build_code
        self._graph = graph
        self._scan_error = scan_error
        self._serve_code = serve_code
        self._serve_stdout = serve_stdout

    async def __call__(self, argv, *, cwd=None, timeout=60, **kwargs):
        name = Path(argv[1]).name
        if name == '--version':
            # `available()` probes node before anything else; answering here
            # keeps the probe out of `calls`, which asserts the script order.
            return Captured(code=0, stdout='v22.0.0\n', stderr='')
        self.calls.append((name, list(argv)))
        if name == floorplan.EXPORT_SCRIPT:
            # #381: the exported copy is a real file the builder's own server
            # writes, so the fake writes one too and the fallback path is the
            # only thing a failure changes.
            if self._serve_code == 0:
                dest = Path(argv[argv.index('--export') + 1])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text('<html>exported</html>', encoding='utf-8')
            return Captured(code=self._serve_code, stdout=self._serve_stdout, stderr='')
        if name != 'scan.mjs':
            return Captured(code=self._build_code, stdout=self._build, stderr='')
        if self._graph is not None:
            out = Path(argv[argv.index('--out') + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(self._graph), encoding='utf-8')
        return Captured(code=self._scan_code, stdout=self._scan,
                        stderr=self._scan_error)

    @property
    def scripts(self) -> list[str]:
        return [name for name, _ in self.calls]


def _wired(tmp_path, monkeypatch, recorder, cfg=None):
    """A project, a config home, a fake floorplan copy and the fake node."""
    proj = _proj(tmp_path)
    cfg = tmp_path / 'home' if cfg is None else cfg
    monkeypatch.setattr(floorplan, 'node_binary', lambda: 'node')
    monkeypatch.setattr(floorplan, 'floorplan_home',
                        lambda *a, **k: _copy_tree(tmp_path / 'fp'))
    monkeypatch.setattr(floorplan, 'run_captured', recorder)
    return proj, cfg


async def test_build_map_authors_the_inputs_from_the_scan_before_it_builds(tmp_path, monkeypatch):
    """#376: floorplan cannot derive what a part of the codebase is for, so the
    pair authors the three inputs from the scan it just took — no preparation
    step, and no guessed path (the scan is what the globs are derived from)."""
    recorder = _PairRecorder(graph=_graph(files=3))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is True, outcome.error
    # Scan, build, then the copy the frame serves (#381).
    assert recorder.scripts == ['scan.mjs', 'build.mjs', 'serve.mjs']
    authored = floorplan.map_dir(proj, cfg) / 'architecture.json'
    assert authored.is_file()
    nodes = json.loads(authored.read_text(encoding='utf-8'))['nodes']
    assert [node['id'] for node in nodes] == ['src']


async def test_build_map_refuses_to_build_inputs_it_could_not_author(tmp_path, monkeypatch):
    """The author is a gate, not a courtesy: a scan with nothing to map stops
    the pair before floorplan is asked to draw an empty board."""
    recorder = _PairRecorder(graph=_graph(files=3, category='docs'))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is False
    assert 'no code files' in outcome.error
    # The build was never spent on a file the author refused to write.
    assert recorder.scripts == ['scan.mjs']


async def test_build_map_scans_then_builds_into_the_map_dir(tmp_path, monkeypatch):
    recorder = _PairRecorder(
        graph=_graph(files=621, edges=848, routes=88, externals=50, hosts=60))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    map_dir = floorplan.map_dir(proj, cfg)
    map_dir.mkdir(parents=True)
    (map_dir / 'architecture.json').write_text('{"nodes": []}', encoding='utf-8')

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is True, outcome.error
    assert recorder.scripts == ['scan.mjs', 'build.mjs', 'serve.mjs']
    _, build_argv = recorder.calls[1]
    assert build_argv[build_argv.index('--out') + 1] == str(map_dir)
    assert build_argv[build_argv.index('--arch') + 1] == str(map_dir / 'architecture.json')
    assert build_argv[build_argv.index('--scan') + 1] == str(map_dir / 'scan.json')
    # The summary is what the agent tool and the panel both read.
    assert '621 files' in outcome.summary()
    # Decision #107: the project itself gains nothing.
    assert sorted(p.name for p in proj.iterdir()) == []


async def test_build_map_reports_a_scan_failure_and_does_not_build(tmp_path, monkeypatch):
    recorder = _PairRecorder(scan_code=1, scan_error='no files at all')
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    floorplan.map_dir(proj, cfg).mkdir(parents=True)
    (floorplan.map_dir(proj, cfg) / 'architecture.json').write_text('{}', encoding='utf-8')

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is False
    assert 'no files at all' in outcome.error
    assert recorder.scripts == ['scan.mjs']


async def test_build_map_keeps_the_builds_per_field_warnings(tmp_path, monkeypatch):
    warnings = ['node "gates" path "src/codingdude/claim_check.py" matches no included file']
    recorder = _PairRecorder(graph=_graph(files=3),
                             build_stdout=_build_receipt(warnings=warnings))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    # This test is about the *builder's* warnings; the author's own best-effort
    # note about the tree is asserted in test_floorplan_inputs.py.
    monkeypatch.setattr('codingdude.floorplan_inputs.git_changes', lambda root: ({}, ''))
    floorplan.map_dir(proj, cfg).mkdir(parents=True)
    (floorplan.map_dir(proj, cfg) / 'architecture.json').write_text('{}', encoding='utf-8')

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.warnings == tuple(warnings)
    # A guessed path is the failure mode #376 must not ship: the warning has to
    # reach the reader, not be counted and dropped.
    assert warnings[0] in outcome.summary()


async def test_build_map_refuses_a_second_concurrent_call(tmp_path, monkeypatch):
    recorder = _PairRecorder()
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    with floorplan.build_lock(proj, cfg):
        with pytest.raises(floorplan.MapLocked):
            await floorplan.build_map(proj, home=cfg)
    assert recorder.calls == []


async def test_build_map_without_node_returns_the_reason(tmp_path, monkeypatch):
    recorder = _PairRecorder()
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    monkeypatch.setattr(floorplan, 'node_binary', lambda: None)

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is False
    assert outcome.error == floorplan.NODE_MISSING
    assert recorder.calls == []


async def test_build_map_records_the_attempt_beside_the_map(tmp_path, monkeypatch):
    """The route answers 202 when the pair outlasts its budget, so the receipt
    has to exist on disk: the request is gone by the time the build finishes."""
    recorder = _PairRecorder(graph=_graph(files=621, routes=88))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    map_dir = floorplan.map_dir(proj, cfg)
    map_dir.mkdir(parents=True)
    (map_dir / floorplan.ARCH_NAME).write_text('{}', encoding='utf-8')

    await floorplan.build_map(proj, home=cfg)

    receipt = floorplan.read_receipt(proj, cfg)
    assert receipt is not None
    assert receipt['ok'] is True
    assert receipt['counts']['files'] == 621
    assert receipt['at']


async def test_the_receipt_keeps_a_failure_reason_and_its_warnings(tmp_path, monkeypatch):
    warnings = ['node "gates" path "src/x.py" matches no included file']
    recorder = _PairRecorder(
        scan_code=1, scan_error='no files at all',
        build_stdout=_build_receipt(warnings=warnings))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    map_dir = floorplan.map_dir(proj, cfg)
    map_dir.mkdir(parents=True)
    (map_dir / floorplan.ARCH_NAME).write_text('{}', encoding='utf-8')

    outcome = await floorplan.build_map(proj, home=cfg)

    receipt = floorplan.read_receipt(proj, cfg)
    assert outcome.ok is False
    assert receipt['ok'] is False
    assert 'no files at all' in receipt['error']


def test_no_receipt_reads_as_none(tmp_path):
    assert floorplan.read_receipt(tmp_path / 'nothing-here') is None


async def test_a_failed_build_still_reports_its_warnings(tmp_path, monkeypatch):
    """A build can fail *and* carry warnings, and the warnings name the field
    that is wrong — dropping them on the failure path hides the fix."""
    warnings = ['node "gates" path "src/x.py" matches no included file']
    recorder = _PairRecorder(
        graph=_graph(files=3),
        build_stdout=_build_receipt(ok=False, errors=['boom'], warnings=warnings))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    map_dir = floorplan.map_dir(proj, cfg)
    map_dir.mkdir(parents=True)
    (map_dir / floorplan.ARCH_NAME).write_text('{}', encoding='utf-8')

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is False
    assert warnings[0] in outcome.summary()


# --- #379: the agent-side trigger -------------------------------------------

def _map_tool(proj: Path):
    return floorplan.build_floorplan_toolset(proj).tools['map_build'].function


async def test_the_map_build_tool_returns_the_summary(home, tmp_path, monkeypatch):
    """The agent refreshes the map *before* pointing a human at it."""
    recorder = _PairRecorder(graph=_graph(files=621, edges=848, routes=88))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder, cfg=home)
    map_dir = floorplan.map_dir(proj, cfg)
    map_dir.mkdir(parents=True)
    (map_dir / 'architecture.json').write_text('{}', encoding='utf-8')

    text = await _map_tool(proj)()

    assert '621 files' in text
    assert recorder.scripts == ['scan.mjs', 'build.mjs', 'serve.mjs']


async def test_the_map_build_tool_degrades_to_the_reason(home, tmp_path, monkeypatch):
    recorder = _PairRecorder()
    proj, cfg = _wired(tmp_path, monkeypatch, recorder, cfg=home)
    monkeypatch.setattr(floorplan, 'node_binary', lambda: None)

    text = await _map_tool(proj)()

    assert floorplan.NODE_MISSING in text
    assert recorder.calls == []


async def test_the_map_build_tool_reports_a_concurrent_build_as_text(home, tmp_path, monkeypatch):
    """A second build is a sentence, not a traceback: the agent may simply be
    early, and a raised exception would abort its turn for a race."""
    recorder = _PairRecorder()
    proj, cfg = _wired(tmp_path, monkeypatch, recorder, cfg=home)
    with floorplan.build_lock(proj, cfg):
        text = await _map_tool(proj)()
    assert 'already' in text.lower()
    assert recorder.calls == []


async def test_map_build_is_wired_into_build_all(home, tmp_path, monkeypatch):
    """Upstream check: the tools reach a real engine toolset, not just a test."""
    from codingdude.config import Config
    from codingdude.db import Database
    from codingdude.plugins import PluginContext, build_all

    monkeypatch.setattr('codingdude.mcp_config.ensure_default_mcp', lambda *_: None)
    monkeypatch.setattr('codingdude.plugins.merged_mcp_server_names', lambda *_: [])
    ctx = PluginContext(
        workdir=tmp_path, config=Config.defaults(), db=Database.connect(home),
        session_id='s379', home=home,
    )
    toolsets = await build_all(ctx)
    names = {t.name for ts in toolsets for t in getattr(ts, 'tools', {}).values()}
    assert {'map_build', 'map_query'} <= names


# --- #378: querying the built map -------------------------------------------

class _QueryRecorder:
    """The fake `node` for a graph query: records argv, returns one answer."""

    def __init__(self, stdout: str = '{"ok": true}', code: int = 0):
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._code = code

    async def __call__(self, argv, *, cwd=None, timeout=60, **kwargs):
        self.calls.append(list(argv))
        return Captured(code=self._code, stdout=self._stdout, stderr='')

    @property
    def scripts(self) -> list[str]:
        return [Path(argv[1]).name for argv in self.calls]

    @property
    def args(self) -> list[list[str]]:
        return [argv[2:] for argv in self.calls]


def _built_map(tmp_path, monkeypatch, recorder, *, cli: bool = True):
    """A project whose map dir holds a graph, and a fake node to query it."""
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    target = floorplan.map_dir(proj, cfg)
    target.mkdir(parents=True, exist_ok=True)
    (target / floorplan.GRAPH_NAME).write_text('{}', encoding='utf-8')
    if cli:
        (target / floorplan.QUERY_CLI).write_text('// generated\n', encoding='utf-8')
    return proj, cfg, target


async def test_the_query_tool_passes_each_verb_to_the_generated_cli(tmp_path, monkeypatch):
    recorder = _QueryRecorder('{"nodes": []}')
    proj, cfg, _ = _built_map(tmp_path, monkeypatch, recorder)

    for verb, text, kind in (
        ('overview', '', ''),
        ('find', 'session store', 'file'),
        ('show', 'src.codingdude', ''),
        ('path', 'a b', ''),
    ):
        result = await floorplan.query_map(proj, verb, text, kind, home=cfg)
        assert result.ok is True, result.text

    assert recorder.scripts == ['query.mjs'] * 4
    assert recorder.args == [
        ['overview'],
        ['find', 'session store', '--kind', 'file'],
        ['show', 'src.codingdude'],
        ['path', 'a', 'b'],
    ]


async def test_an_unknown_verb_costs_no_subprocess(tmp_path, monkeypatch):
    """A typo is answered from the module's own list, so a wrong verb cannot
    spend a thirty-second subprocess to say what is already known."""
    recorder = _QueryRecorder()
    proj, cfg, _ = _built_map(tmp_path, monkeypatch, recorder)

    result = await floorplan.query_map(proj, 'search', 'x', home=cfg)

    assert result.ok is False
    for verb in floorplan.QUERY_VERBS:
        assert verb in result.text
    assert recorder.calls == []


async def test_a_map_that_was_never_built_says_build_one_first(tmp_path, monkeypatch):
    recorder = _QueryRecorder()
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)

    result = await floorplan.query_map(proj, 'overview', home=cfg)

    assert result.ok is False
    assert 'build one' in result.text
    assert recorder.calls == []


async def test_a_map_without_its_cli_says_the_payload_changed_shape(tmp_path, monkeypatch):
    """The two absences are different answers: sending a reader to rebuild a map
    that already exists is a wild goose chase."""
    recorder = _QueryRecorder()
    proj, cfg, target = _built_map(tmp_path, monkeypatch, recorder, cli=False)

    result = await floorplan.query_map(proj, 'overview', home=cfg)

    assert result.ok is False
    assert 'payload changed shape' in result.text
    assert str(target) in result.text
    # Nothing was spawned to answer a question about a missing file.
    assert recorder.calls == []


async def test_a_failed_query_hands_back_the_clis_own_words(tmp_path, monkeypatch):
    recorder = _QueryRecorder('{"error": "Unknown id; use find first."}', code=1)
    proj, cfg, _ = _built_map(tmp_path, monkeypatch, recorder)

    result = await floorplan.query_map(proj, 'show', 'n:nowhere', home=cfg)

    assert result.ok is False
    assert 'Unknown id' in result.text


async def test_a_query_that_needs_an_argument_says_so(tmp_path, monkeypatch):
    recorder = _QueryRecorder()
    proj, cfg, _ = _built_map(tmp_path, monkeypatch, recorder)

    missing = await floorplan.query_map(proj, 'find', '', home=cfg)
    one_id = await floorplan.query_map(proj, 'path', 'only', home=cfg)

    assert 'needs a query' in missing.text
    assert 'needs two ids' in one_id.text
    assert recorder.calls == []


async def test_a_large_answer_is_truncated_and_says_so(tmp_path, monkeypatch):
    """Through the tool, not a helper: a clipped JSON document that looks
    complete is worse than one that says it was cut."""
    huge = json.dumps({'files': ['x' * (floorplan.QUERY_MAX_CHARS + 500)]})
    recorder = _QueryRecorder(huge)
    proj, cfg, _ = _built_map(tmp_path, monkeypatch, recorder)

    result = await floorplan.query_map(proj, 'show', 'n:big', home=cfg)

    assert result.ok is True
    assert len(result.text) < len(huge)
    assert 'truncated' in result.text


async def test_a_small_answer_is_passed_through_untouched(tmp_path, monkeypatch):
    recorder = _QueryRecorder('{"a": 1}')
    proj, cfg, _ = _built_map(tmp_path, monkeypatch, recorder)

    assert (await floorplan.query_map(proj, 'overview', home=cfg)).text == '{"a": 1}'


async def test_the_query_tool_reads_a_real_built_map(tmp_path, monkeypatch):
    """Against a real build, not a fake: `find` and `path` must return parseable
    JSON from the graph the builder wrote."""
    if shutil.which('node') is None:
        pytest.skip('node is not installed')
    if floorplan.floorplan_home() is None:
        pytest.skip('floorplan is not vendored')
    repo = tmp_path / 'fixture'
    (repo / 'src' / 'demo').mkdir(parents=True)
    (repo / 'tools').mkdir()
    (repo / 'pyproject.toml').write_text(
        '[project]\nname = "demo"\ndescription = "A demo repo."\n', encoding='utf-8')
    (repo / 'src' / 'demo' / 'core.py').write_text(
        '"""Holds the core things in a store."""\n', encoding='utf-8')
    (repo / 'tools' / 'thing.py').write_text(
        '"""Runs the thing."""\n', encoding='utf-8')
    monkeypatch.setattr('codingdude.floorplan_inputs.git_changes', lambda root: ({}, ''))
    home = tmp_path / 'home'
    built = await floorplan.build_map(repo, home=home)
    assert built.ok is True, built.error

    found = await floorplan.query_map(repo, 'find', 'core', home=home)
    overview = await floorplan.query_map(repo, 'overview', home=home)
    shown = await floorplan.query_map(repo, 'show', 'n:src', home=home)

    assert found.ok is True, found.text
    assert json.loads(found.text)
    assert json.loads(overview.text)['project'] == 'demo'
    # `path` needs two ids, which only a real graph can supply; a node and one of
    # its own files is the shortest honest pair.
    assert json.loads(shown.text)['id'] == 'n:src'
    chained = await floorplan.query_map(repo, 'path', 'n:src f:src/demo/core.py', home=home)
    assert json.loads(chained.text) is not None


# --- #381: the exported copy the frame serves --------------------------------

def _both_pages(tmp_path, *, export_newer: bool = True):
    """A map dir holding both pages, with the export's age under control."""
    out = tmp_path / 'mapdir'
    out.mkdir(parents=True)
    page = out / 'index.html'
    page.write_text('<html>build</html>', encoding='utf-8')
    export = out / floorplan.EXPORT_NAME
    export.write_text('<html>exported</html>', encoding='utf-8')
    if not export_newer:
        older = page.stat().st_mtime - 60
        os.utime(export, (older, older))
    return out, page, export


def test_the_frame_serves_the_exported_copy_when_it_is_current(tmp_path, monkeypatch):
    """#381: the exported copy is the one without the Ask bar, so it is the one
    the sandboxed frame gets; `map_page()` stays the build's own page."""
    out, _page, export = _both_pages(tmp_path)
    monkeypatch.setattr(floorplan, 'map_dir', lambda *a, **k: out)

    assert floorplan.map_frame_page(tmp_path) == export


def test_the_frame_falls_back_to_the_build_page_without_an_export(tmp_path, monkeypatch):
    """A map built before this change, or whose export failed, still opens."""
    out = tmp_path / 'mapdir'
    out.mkdir()
    page = out / 'index.html'
    page.write_text('<html>build</html>', encoding='utf-8')
    monkeypatch.setattr(floorplan, 'map_dir', lambda *a, **k: out)

    assert floorplan.map_frame_page(tmp_path) == page


def test_the_frame_ignores_an_export_older_than_the_build(tmp_path, monkeypatch):
    """A rebuild that wrote the page but not its copy must not serve the copy:
    the frame would show the previous build while the panel said "built"."""
    out, page, _export = _both_pages(tmp_path, export_newer=False)
    monkeypatch.setattr(floorplan, 'map_dir', lambda *a, **k: out)

    assert floorplan.map_frame_page(tmp_path) == page


async def test_the_pair_writes_the_copy_the_frame_serves(tmp_path, monkeypatch):
    """#381: the copy is made by floorplan's own `serve.mjs --export`, which is
    the same path its Export button takes — not a second implementation of it."""
    recorder = _PairRecorder(graph=_graph(files=3))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is True, outcome.error
    assert recorder.scripts == ['scan.mjs', 'build.mjs', 'serve.mjs']
    _, export_argv = recorder.calls[2]
    map_dir = floorplan.map_dir(proj, cfg)
    # The script writes a sidecar that we then publish: the served name never
    # holds a half-written file.
    assert export_argv[export_argv.index('--export') + 1] == str(
        floorplan.export_temp(map_dir))
    assert (map_dir / floorplan.EXPORT_NAME).is_file()
    assert not floorplan.export_temp(map_dir).exists()
    # `health` is left out on purpose: floorplan's health scan is heuristic and
    # reports a HIGH finding on routes that do carry `Depends(authorize)`, so
    # showing it in our own panel would present a wrong verdict as ours.
    assert export_argv[export_argv.index('--include') + 1] == 'flows,notes,recent'
    assert outcome.page == map_dir / floorplan.EXPORT_NAME


async def test_a_failed_export_leaves_no_partial_copy_to_serve(tmp_path, monkeypatch):
    """A copy half-written before the failure must not become the map.

    `map_frame_page()` serves whatever is newer than the build's page, so the
    failure mode this pins is a truncated file inheriting that freshness: the
    previous copy has to survive untouched, and the partial one has to be gone.
    """
    out = tmp_path / 'map'
    out.mkdir()
    dest = out / floorplan.EXPORT_NAME
    dest.write_text('<html>older copy</html>', encoding='utf-8')
    page = out / 'index.html'
    page.write_text('<html>built</html>', encoding='utf-8')
    monkeypatch.setattr(floorplan, 'map_dir', lambda *a, **k: out)
    # The rebuild wrote a newer page, so an older copy is correctly ignored.
    newer = page.stat().st_mtime + 60
    os.utime(page, (newer, newer))

    async def half_writes(argv, *, cwd=None, timeout=60, **kwargs):
        Path(argv[argv.index('--export') + 1]).write_text(
            '<html>truncated', encoding='utf-8')
        return Captured(code=1, stdout='', stderr='ENOSPC: no space left')

    monkeypatch.setattr(floorplan, 'run_captured', half_writes)
    monkeypatch.setattr(floorplan, 'node_binary', lambda: Path('node'))

    problem = await floorplan._export_page(out)

    assert 'exported copy failed' in problem
    assert 'ENOSPC' in problem
    assert dest.read_text(encoding='utf-8') == '<html>older copy</html>'
    assert not floorplan.export_temp(out).exists()
    assert floorplan.map_frame_page(tmp_path) == page


async def test_a_failed_export_is_a_warning_and_the_build_page_is_served(tmp_path, monkeypatch):
    """The map is drawn either way: a copy that could not be made is a note
    beside the build's own warnings, never a failed build."""
    recorder = _PairRecorder(graph=_graph(files=7), serve_code=1,
                             serve_stdout="Couldn't export the map: no index.html")
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is True
    assert outcome.page == floorplan.map_page(proj, cfg)
    assert any('exported copy' in warning for warning in outcome.warnings)
