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
import shutil
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
    scripts.mkdir(parents=True)
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
