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
"""#86 (R38 phase 3): edited-file dependency/impact graph."""

import subprocess
from pathlib import Path

import pytest

from codingdude import impact
from codingdude.impact import _js_stems, _module_name, impact_graph


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(['git', '-c', 'safe.directory=*', *args], cwd=cwd,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f'git {args} failed: {r.stderr}')


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@t')
    _git(repo, 'config', 'user.name', 't')
    return repo


def test_module_name_drops_top_level() -> None:
    assert _module_name('src/pkg/mod.py') == 'pkg.mod'
    assert _module_name('mod.py') == 'mod'
    assert _module_name('pkg/__init__.py') == 'pkg'


def test_js_stems_cover_relative_forms() -> None:
    assert _js_stems('src/util.ts') == {'./src/util', './util'}


def test_impact_finds_python_dependents(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / 'core.py').write_text('def f():\n    pass\n')
    (repo / 'user.py').write_text('import core\n\n\ndef g():\n    return core.f()\n')
    out = impact_graph(repo, ['core.py'])
    assert out['edges'][0]['dependents'] == ['user.py']
    assert out['orphans'] == []


def test_impact_marks_orphans(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / 'lonely.py').write_text('x = 1\n')
    out = impact_graph(repo, ['lonely.py'])
    assert out['edges'][0]['dependents'] == []
    assert out['orphans'] == ['lonely.py']


def test_impact_skips_changed_files_as_dependents_and_ignores_dirs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / 'a.py').write_text('def f():\n    pass\n')
    (repo / 'b.py').write_text('import a\n')
    out = impact_graph(repo, ['a.py', 'b.py'])
    by_path = {e['path']: e for e in out['edges']}
    assert by_path['a.py']['dependents'] == []  # b.py is itself changed, excluded
    assert 'b.py' in out['orphans']


def test_impact_without_changes_returns_before_walking_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#371: nothing changed has a known answer, so no walk is warranted.

    The Diff panel polls this endpoint every 2s. On a repo carrying a venv the
    walk cost ~62s to prove the empty result, which is why the panel never left
    'loading...'.
    """

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('impact_graph walked the tree with nothing changed')

    monkeypatch.setattr(impact, '_source_files', explode)
    assert impact_graph(tmp_path, []) == {'edges': [], 'orphans': []}


def test_impact_ignores_a_file_that_only_mentions_the_module_name(tmp_path: Path) -> None:
    """The cheap text pre-filter is a necessary condition, never a match.

    'core' appears here only in a comment and a string literal, so this file
    cannot be a dependent even though it survives the filter.
    """
    repo = _repo(tmp_path)
    (repo / 'core.py').write_text('def f():\n    pass\n')
    (repo / 'chatty.py').write_text('# core is great\nNOTE = "core"\n')
    out = impact_graph(repo, ['core.py'])
    assert out['edges'][0]['dependents'] == []
    assert out['orphans'] == ['core.py']


def test_impact_ignores_dependents_inside_skipped_directories(tmp_path: Path) -> None:
    """A vendored copy under node_modules is not a dependent of this repo."""
    repo = _repo(tmp_path)
    (repo / 'util.js').write_text('export const x = 1\n')
    vendored = repo / 'node_modules' / 'pkg'
    vendored.mkdir(parents=True)
    (vendored / 'uses.js').write_text("import { x } from './util'\n")
    out = impact_graph(repo, ['util.js'])
    assert out['edges'][0]['dependents'] == []


def test_impact_ignores_dependents_in_side_venvs_and_plain_venv(tmp_path: Path) -> None:
    """#371: the walker prunes with tools.skip_dir, not bare SKIP_DIRS.

    A .venv-verify/.venv-harness sibling or a plain `venv` is a second
    interpreter, never project source. Pruning only SKIP_DIRS reported those
    files as dependents and left 24736 of this repo's 25122 walked files - 98%
    of the cost this fix exists to remove - inside side venvs.
    """
    repo = _repo(tmp_path)
    changed = repo / 'src' / 'pkg' / 'b.py'
    changed.parent.mkdir(parents=True)
    changed.write_text('VALUE = 1\n')
    (repo / 'src' / 'user.py').write_text('import pkg.b\n')
    for outside in ('.venv-verify', '.venv-harness', 'venv'):
        site = repo / outside / 'site'
        site.mkdir(parents=True)
        (site / 'decoy.py').write_text('import pkg.b\n')
    out = impact_graph(repo, ['src/pkg/b.py'])
    assert out['edges'][0]['dependents'] == ['src/user.py']


def test_impact_finds_javascript_dependents(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / 'util.js').write_text('export const x = 1\n')
    (repo / 'app.js').write_text("import { x } from './util'\n")
    out = impact_graph(repo, ['util.js'])
    assert out['edges'][0]['dependents'] == ['app.js']


def test_impact_resolves_python_and_javascript_changes_together(tmp_path: Path) -> None:
    """Both languages in one call: neither may be filtered out by the other."""
    repo = _repo(tmp_path)
    (repo / 'core.py').write_text('def f():\n    pass\n')
    (repo / 'user.py').write_text('import core\n')
    (repo / 'util.js').write_text('export const x = 1\n')
    (repo / 'app.js').write_text("import { x } from './util'\n")
    out = impact_graph(repo, ['core.py', 'util.js'])
    by_path = {e['path']: e['dependents'] for e in out['edges']}
    assert by_path['core.py'] == ['user.py']
    assert by_path['util.js'] == ['app.js']
    assert out['orphans'] == []


# --- #373: relative imports are dependencies too ---------------------------


def test_package_of_a_module_and_of_a_package() -> None:
    assert impact._package_of('src/pkg/b.py') == 'pkg'
    assert impact._package_of('src/pkg/__init__.py') == 'pkg'
    assert impact._package_of('src/pkg/sub/deep.py') == 'pkg.sub'
    assert impact._package_of('src/mod.py') == ''


def test_py_imports_resolve_relative_levels() -> None:
    """A level is resolved against the importing file's own package, so the
    result is the same dotted name an absolute import would have produced."""
    imports_of = impact._py_imports_of
    assert imports_of('from .b import VALUE', 'pkg') == {'pkg.b'}
    assert imports_of('from . import b', 'pkg') == {'pkg.b'}
    assert imports_of('from ..x import y', 'pkg.sub') == {'pkg.x'}
    assert imports_of('from pkg.b import VALUE', 'pkg') == {'pkg.b'}
    assert imports_of('import pkg.b', 'pkg') == {'pkg.b'}


def test_py_imports_ignore_a_level_that_climbs_past_the_root() -> None:
    """`from ...x import y` in pkg/ has no parent package: an ImportError, not
    an edge. Inventing one would report a dependency that cannot exist."""
    assert impact._py_imports_of('from ...x import y', 'pkg') == set()


def test_relative_import_is_the_same_edge_as_an_absolute_one(tmp_path: Path) -> None:
    """#373: `from .b import VALUE` is an edge on pkg.b, exactly like
    `from pkg.b import VALUE`.

    Dropping ast.ImportFrom.level resolved the relative form to a bare 'b'
    that never matched _module_name(), so most intra-package edges were
    invisible: on this repo 49 of 80 modules use relative imports and only 16
    carry an absolute sibling import, so the graph under-reported dependents
    and a change looked safer than it was.

    The relative files are also the regression test for #371's text
    pre-filter: neither spells `pkg` anywhere, so a filter keyed on the first
    dotted segment would drop both and leave the graph wrong while starting to
    look right. They only survive because it keys on the last one.
    """
    repo = _repo(tmp_path)
    pkg = repo / 'src' / 'pkg'
    pkg.mkdir(parents=True)
    (pkg / 'b.py').write_text('VALUE = 1\n')
    (pkg / 'rel_from.py').write_text('from .b import VALUE\n')
    (pkg / 'rel_module.py').write_text('from . import b\n')
    (pkg / 'abs_from.py').write_text('from pkg.b import VALUE\n')
    out = impact_graph(repo, ['src/pkg/b.py'])
    assert out['edges'][0]['dependents'] == [
        'src/pkg/abs_from.py',
        'src/pkg/rel_from.py',
        'src/pkg/rel_module.py',
    ]


def test_relative_import_resolves_against_the_nearest_parent(tmp_path: Path) -> None:
    """`from ..x import y` inside pkg/sub is an edge on pkg.x, not on sub.x."""
    repo = _repo(tmp_path)
    pkg = repo / 'src' / 'pkg'
    (pkg / 'sub').mkdir(parents=True)
    (pkg / 'x.py').write_text('VALUE = 1\n')
    (pkg / 'sub' / 'deep.py').write_text('from ..x import y\n')
    out = impact_graph(repo, ['src/pkg/x.py'])
    assert out['edges'][0]['dependents'] == ['src/pkg/sub/deep.py']

