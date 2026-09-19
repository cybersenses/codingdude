"""#86 (R38 phase 3): edited-file dependency/impact graph."""

import subprocess
from pathlib import Path

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
