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
           externals: int = 5, hosts: int = 2) -> dict:
    """The scan.json shape: the graph itself, indexed by these five lists."""
    return {
        'files': [{'path': f'src/a{i}.py'} for i in range(files)],
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


# --- #379: availability without a spawn -------------------------------------

def test_check_available_costs_no_subprocess(tmp_path, monkeypatch):
    """`/map/state` is polled, so its availability answer must not spawn.

    Presence answers both halves of the question a polled route asks: node on
    PATH, and a copy of floorplan to drive. The `node --version` probe stays in
    `available()`, for a caller that wants the version rather than a verdict.
    """
    spawned = []

    async def refuse(argv, **kwargs):
        spawned.append(argv)
        raise AssertionError('check_available spawned a subprocess')

    monkeypatch.setattr(floorplan, 'run_captured', refuse)
    monkeypatch.setattr(floorplan, 'node_binary', lambda: 'node')
    monkeypatch.setattr(floorplan, 'floorplan_home', lambda *a, **k: tmp_path / 'fp')
    ok, detail = floorplan.check_available()
    assert ok is True
    assert str(tmp_path / 'fp') in detail
    assert spawned == []


def test_check_available_names_the_missing_dependency(monkeypatch):
    monkeypatch.setattr(floorplan, 'node_binary', lambda: None)
    ok, detail = floorplan.check_available()
    assert ok is False
    assert 'node' in detail.lower()
    assert detail == floorplan.NODE_MISSING


def test_check_available_names_the_missing_copy(monkeypatch):
    monkeypatch.setattr(floorplan, 'node_binary', lambda: 'node')
    monkeypatch.setattr(floorplan, 'floorplan_home', lambda *a, **k: None)
    ok, detail = floorplan.check_available()
    assert ok is False
    assert detail == floorplan.unavailable_reason()


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
                 scan_error: str = ''):
        self.calls: list[tuple[str, list[str]]] = []
        self._scan = _scan_receipt() if scan_stdout is None else scan_stdout
        self._build = _build_receipt() if build_stdout is None else build_stdout
        self._scan_code = scan_code
        self._build_code = build_code
        self._graph = graph
        self._scan_error = scan_error

    async def __call__(self, argv, *, cwd=None, timeout=60, **kwargs):
        name = Path(argv[1]).name
        self.calls.append((name, list(argv)))
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


async def test_build_map_names_the_architecture_file_nobody_authored(tmp_path, monkeypatch):
    """#376 supplies it; until then the trigger must say so by name, rather
    than spend a scan to let build.mjs answer 'No architecture file at ...'."""
    recorder = _PairRecorder()
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is False
    assert 'architecture.json' in outcome.error
    assert '#376' in outcome.error
    assert recorder.calls == []


async def test_build_map_scans_then_builds_into_the_map_dir(tmp_path, monkeypatch):
    recorder = _PairRecorder(
        graph=_graph(files=621, edges=848, routes=88, externals=50, hosts=60))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
    map_dir = floorplan.map_dir(proj, cfg)
    map_dir.mkdir(parents=True)
    (map_dir / 'architecture.json').write_text('{"nodes": []}', encoding='utf-8')

    outcome = await floorplan.build_map(proj, home=cfg)

    assert outcome.ok is True, outcome.error
    assert recorder.scripts == ['scan.mjs', 'build.mjs']
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
    recorder = _PairRecorder(build_stdout=_build_receipt(warnings=warnings))
    proj, cfg = _wired(tmp_path, monkeypatch, recorder)
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
    assert recorder.scripts == ['scan.mjs', 'build.mjs']


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
    """Upstream check: the tool reaches a real engine toolset, not just a test."""
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
    assert 'map_build' in names
