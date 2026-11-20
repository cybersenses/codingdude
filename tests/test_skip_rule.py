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
"""#374: one skip rule for every workdir walker.

The walkers below used to filter with ``any(part in SKIP_DIRS ...)``. SKIP_DIRS
holds neither the ``.venv-*`` side venvs nor plain ``venv``, so ~24.7k files of
third-party copies on this repo were walked, parsed and reported as project
dependents, definitions and dead code. The fix is :func:`codingdude.tools.skip_parts`
(the parts-aware twin of ``skip_dir``), and these tests are per-walker: the rule
being right is not evidence that a walker calls it.

Every assertion is one direction only — side-venv content must never appear —
plus a control that the *real* source still does, so a walker that returns
nothing cannot pass by scanning nothing.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

from codingdude import (
    ast_tools,
    callgraph,
    codegraph_boot,
    deadcode,
    delegation,
    onboarding,
    refactor,
    semantic,
    structure,
    tools,
)
from codingdude.ast_tools import build_ast_toolset
from codingdude.db import Database
from codingdude.tools import (
    ARTIFACT_KEEP,
    SKIP_DIRS,
    build_toolset,
    skip_dir,
    skip_parts,
)

#: The one real source file in the fixture project.
REAL = 'src/app.py'
#: A token that only exists inside a side venv / node_modules copy.
DECOY = 'DECOY_SIDE_VENV_TOKEN'
#: Third-party trees that a walker must never treat as project source. The
#: first three are the class #374 is about; node_modules is the pre-existing
#: SKIP_DIRS member kept here as the control for the shared set.
SIDE_TREES = (
    '.venv-harness/lib/site-packages',
    '.venv-verify/lib/site-packages',
    'venv/lib/site-packages',
    'node_modules/dep',
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Workdir whose only project source is `src/app.py`."""
    (tmp_path / 'src').mkdir()
    (tmp_path / REAL).write_text('def real_source():\n    return 1\n', encoding='utf-8')
    for tree in SIDE_TREES:
        target = tmp_path / tree
        target.mkdir(parents=True)
        (target / 'decoy.py').write_text(
            f'{DECOY} = 1\n', encoding='utf-8')
        (target / 'decoy.js').write_text(
            f'export const {DECOY} = 1\n', encoding='utf-8')
    return tmp_path


def _leaked(paths) -> list[str]:
    """Paths a walker should not have handed back."""
    out = []
    for path in paths:
        posix = Path(path).as_posix()
        if any(tree.split('/')[0] in posix for tree in SIDE_TREES):
            out.append(posix)
    return out


# --- the rule itself -------------------------------------------------------


@pytest.mark.parametrize('name', sorted(SKIP_DIRS))
def test_skip_dir_covers_the_shared_set(name: str) -> None:
    assert skip_dir(name)


@pytest.mark.parametrize('name', ['.venv-harness', '.venv-verify', 'venv'])
def test_skip_dir_covers_side_venvs(name: str) -> None:
    """The R75/#255 class: venvs beside the project, not just `--venv` itself."""
    assert skip_dir(name)


@pytest.mark.parametrize('name', ['src', 'tests', 'reference', 'docs', 'app.py'])
def test_skip_dir_leaves_project_source_alone(name: str) -> None:
    assert not skip_dir(name)


def test_skip_parts_flags_a_side_venv_below_the_root() -> None:
    assert skip_parts(Path('.venv-verify/lib/site-packages/pkg/mod.py'))
    assert skip_parts(Path('venv/lib/site-packages/pkg/mod.py'))


def test_skip_parts_allows_project_source() -> None:
    assert not skip_parts(Path(REAL))
    assert not skip_parts(Path('src/pkg/deep/mod.py'))


def test_skip_parts_honours_caller_extras_on_top_of_the_shared_rule() -> None:
    """semantic's `reference/` exclusion is an extra, not a forked rule."""
    assert not skip_parts(Path('reference/manual.md'))
    assert skip_parts(Path('reference/manual.md'), {'reference'})
    assert skip_parts(Path('.venv-verify/x.py'), {'reference'})


# --- one assertion per migrated walker -------------------------------------


def test_ast_tool_python_files_skip_side_venvs(project: Path) -> None:
    files = list(ast_tools._python_files(project))
    assert _leaked(files) == []
    assert [f.name for f in files] == ['app.py']


def test_ast_navigation_and_generic_walkers_skip_side_venvs(project: Path) -> None:
    """The module's other two walkers, which name-based grep for SKIP_DIRS missed
    (they are nested inside the toolset builder, so they are driven through the
    tools that use them: find_definition over a navigation-only and a
    full-support suffix)."""
    (project / 'src' / 'settings.json').write_text('{"needle": 1}\n', encoding='utf-8')
    (project / 'src' / 'main.go').write_text('package main\nfunc needle() {}\n', encoding='utf-8')
    for tree in SIDE_TREES:
        (project / tree / 'decoy.json').write_text('{"needle": 1}\n', encoding='utf-8')
        (project / tree / 'decoy.go').write_text('package decoy\nfunc needle() {}\n', encoding='utf-8')
    find_definition = build_ast_toolset(project).tools['find_definition'].function
    for symbol in ('needle', 'main'):
        out = find_definition(symbol, path='.')
        assert 'venv' not in out and 'node_modules' not in out, out


def test_callgraph_files_skip_side_venvs(project: Path) -> None:
    files = list(callgraph._iter_source_files(project, 10_000))
    assert _leaked(files) == []
    assert [f.name for f in files] == ['app.py']


def test_deadcode_files_skip_side_venvs(project: Path) -> None:
    files = list(deadcode._iter_source_files(project, {'.py'}))
    assert _leaked(files) == []
    assert [f.name for f in files] == ['app.py']


def test_deadcode_all_files_skip_side_venvs(project: Path) -> None:
    """The tree-sitter walker had its own SKIP_NAMES (#374 review finding).

    Two walkers in one module, one migrated and one forgotten, is how the
    defect survived the first sweep: the second walked `.venv-verify` and
    reported its definitions as project dead code.
    """
    files = list(deadcode._all_files(project))
    assert _leaked(files) == []
    assert [f.name for f in files] == ['app.py']


def test_deadcode_all_files_still_skips_built_output(project: Path) -> None:
    """`dist/` is an extra on top of the shared rule, not a dropped one."""
    built = project / 'dist'
    built.mkdir()
    (built / 'bundle.js').write_text('export const x = 1\n', encoding='utf-8')
    assert [f.name for f in deadcode._all_files(project)] == ['app.py']


def test_refactor_files_skip_side_venvs(project: Path) -> None:
    files = list(refactor._iter_source(project))
    assert _leaked(files) == []
    assert [f.name for f in files] == ['app.py']


def test_delegation_files_skip_side_venvs(project: Path) -> None:
    files = list(delegation._iter_target_files(project))
    assert _leaked(files) == []
    assert [f.name for f in files] == ['app.py']


def test_project_structure_skips_side_venvs(project: Path) -> None:
    structure_map = structure.project_structure(project)
    paths = [entry['path'] for entry in structure_map['files']]
    assert paths == [REAL]


def test_semantic_index_skips_side_venvs(project: Path, home: Path) -> None:
    index = semantic.SemanticIndex(semantic.FakeEmbedder(dimension=64), Database.connect(home))
    assert index.index_workdir(project) == 1
    rows = index.db._conn.execute('SELECT path FROM embeddings').fetchall()
    assert [row['path'] for row in rows] == [REAL]


def test_grep_tool_skips_side_venvs(project: Path) -> None:
    grep = build_toolset(project).tools['grep'].function
    assert grep(pattern=DECOY, path='.') == '(no matches)'
    # Control: the same call does find real source, so the empty answer above
    # is the skip rule working, not grep being broken. (grep prints the path
    # with the platform separator; the tail is what identifies the file.)
    assert 'app.py:1' in grep(pattern='real_source', path='.')


def test_onboarding_language_mix_skips_side_venvs(project: Path) -> None:
    conventions = onboarding.detect_conventions(project)
    assert conventions['languages'] == {'python': 1}


def test_codegraph_staleness_ignores_side_venvs(project: Path) -> None:
    """A side venv newer than the index is not a stale project index; it used
    to be reported as one, triggering a needless full re-index."""
    index = project / '.codegraph'
    index.mkdir()
    (index / 'index.bin').write_text('x', encoding='utf-8')
    future = time.time() + 60
    for tree in SIDE_TREES:
        os.utime(project / tree / 'decoy.py', (future, future))
    assert codegraph_boot.index_is_stale(project) is False
    # Control: real source newer than the index IS stale.
    os.utime(project / REAL, (future, future))
    assert codegraph_boot.index_is_stale(project) is True


# --- artifact scans: the same rule, one entry kept back ---------------------


def test_artifact_scans_skip_side_venvs_but_keep_the_scratch_area(project: Path) -> None:
    """A screenshot lands in .scratch; a decoy render inside a venv is noise.

    These scans look for *output*, so they run the shared rule with
    `keep=ARTIFACT_KEEP` rather than carrying a fourth private copy of it.
    """
    assert skip_parts(Path('.venv-verify/shot.png'), keep=ARTIFACT_KEEP)
    assert not skip_parts(Path('.scratch/shot.png'), keep=ARTIFACT_KEEP)
    assert skip_parts(Path('.scratch/shot.png'))  # source walkers still skip it

    scratch = project / '.scratch'
    scratch.mkdir()
    (scratch / 'shot.png').write_bytes(b'\x89PNG')
    for tree in SIDE_TREES:
        (project / tree / 'decoy.png').write_bytes(b'\x89PNG')
    seen: list[str] = []
    tools._register_new_renders(project, started=0.0, on_render=seen.append)
    assert seen == ['.scratch/shot.png']


def test_no_module_keeps_its_own_skip_set() -> None:
    """The durable guard: this defect was one rule duplicated a dozen times.

    A module needing an extra subtree passes `extra=`; needing output rather
    than source passes `keep=`. A module-local SKIP* set is the fork that made
    #374 possible, so it fails here instead of being rediscovered by reading.
    """
    src = Path(__file__).resolve().parents[1] / 'src' / 'codingdude'
    pattern = re.compile(r'^\s*_?SKIP[A-Z_]*\s*=\s*[{(]', re.MULTILINE)
    offenders = sorted(
        path.relative_to(src).as_posix()
        for path in src.rglob('*.py')
        if path.name != 'tools.py' and pattern.search(path.read_text(encoding='utf-8'))
    )
    assert offenders == []
