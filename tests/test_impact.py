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
