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
"""R103 #376: floorplan's three authored inputs, derived from computed facts.

The module's whole claim is that nothing in these files is invented, so the
tests are about *derivation*: a glob that claims files, a label the repository
already uses, a sentence the code already carries. Two of them are gates rather
than features — a path claiming no file is an error (floorplan itself only
warns), and the author refuses to write what it cannot check.

The fakes stop at the file system: `git_changes` is the only subprocess in the
author, so stubbing it is the whole boundary. The last test runs the real
scanner and builder on a fixture repository, skipped only when node or the
vendored copy is genuinely absent.
"""

import json
import shutil
from pathlib import Path

import pytest

from codingdude import floorplan
from codingdude import floorplan_inputs as fi


def _entry(path: str, *, category: str = 'code', lang: str = 'python') -> dict:
    return {'path': path, 'category': category, 'lang': lang, 'loc': 1}


def _scan(*entries: dict, routes: list | None = None,
          externals: list | None = None) -> dict:
    return {
        'files': list(entries),
        'edges': [],
        'routes': routes or [],
        'externals': externals or [],
        'hosts': [],
        'http': [],
    }


# --- the glob dialect --------------------------------------------------------

@pytest.mark.parametrize(('pattern', 'path', 'expected'), [
    ('src/**', 'src/a.py', True),
    ('src/**', 'src/deep/a.py', True),
    ('src/**', 'tests/a.py', False),
    ('src/*.py', 'src/a.py', True),
    ('src/*.py', 'src/deep/a.py', False),
    ('**/*.test.ts', 'frontend/x.test.ts', True),
    ('**/*.test.ts', 'frontend/src/deep/x.test.ts', True),
    ('**/*.test.ts', 'frontend/x.ts', False),
    ('src/?py', 'src/py', False),
    ('src/{a,b}.py', 'src/a.py', True),
    ('src/{a,b}.py', 'src/c.py', False),
    # A pattern with no wildcard also names a directory (schema.md).
    ('backend/app', 'backend/app/models.py', True),
    ('backend/app', 'backend/app', False),
    ('*', 'bench.py', True),
    ('*', 'src/bench.py', False),
])
def test_glob_match_implements_floorplans_dialect(pattern, path, expected):
    assert fi.glob_match(pattern, path) is expected


# --- the scan's file list ----------------------------------------------------

def test_only_included_code_reaches_the_board():
    """`ignore` and `include` are the builder's filter, so the author's list is
    the same filter — otherwise a glob could name a file the board never shows."""
    scan = _scan(
        _entry('src/a.py'),
        _entry('vendor/floorplan/scripts/build.mjs', lang='javascript'),
        _entry('docs/manual.md', category='docs', lang='markdown'),
    )
    assert [f['path'] for f in fi.included_files(scan)] == ['src/a.py']


# --- chips -------------------------------------------------------------------

def test_a_parent_directory_that_owns_no_files_is_not_a_chip(tmp_path):
    """`src` is large enough to earn a chip and still owns nothing once
    `src/codingdude` claims its files — exactly what happens on this repo."""
    files = [_entry(f'src/codingdude/m{i}.py') for i in range(6)]

    nodes = fi.nodes_for(tmp_path, fi.included_files(_scan(*files)), set())

    ids = {node['id'] for node in nodes}
    assert 'src.codingdude' in ids
    assert 'src' not in ids


def test_a_shallow_directory_below_its_threshold_stays_a_folder(tmp_path):
    files = [_entry(f'frontend/src/panels/p{i}.jsx', lang='javascript') for i in range(3)]
    files.append(_entry('frontend/main.jsx', lang='javascript'))

    nodes = fi.nodes_for(tmp_path, fi.included_files(_scan(*files)), set())

    ids = {node['id'] for node in nodes}
    assert 'frontend.src.panels' not in ids  # 3 files at depth 3
    assert 'frontend.src' not in ids  # 3 files at depth 2
    assert 'frontend' in ids


def test_chips_are_labelled_and_kinded_from_the_repository(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname = "demo"\ndescription = "A demo repo."\n'
        '[project.scripts]\ndemo = "demo.cli:main"\n',
        encoding='utf-8',
    )
    files = [
        _entry('src/demo/cli.py'),
        _entry('src/demo/core.py'),
        _entry('src/demo/api.py'),
        _entry('src/demo/db.py'),
        _entry('tests/test_core.py'),
        _entry('tests/test_api.py'),
        _entry('tools/script.py'),
    ]

    architecture = fi.build_architecture(tmp_path, _scan(*files))
    by_id = {node['id']: node for node in architecture['nodes']}

    assert architecture['project'] == {
        'name': 'demo',
        'summary': 'A demo repo.',
        'entrypoints': ['src/demo/cli.py'],
    }
    assert by_id['src.demo']['kind'] == 'service'  # it owns the entrypoint
    assert by_id['tests']['kind'] == 'test'
    assert by_id['tests']['label'] == 'Tests'
    assert by_id['tools']['kind'] == 'script'
    # Raw is only present explicitly: nothing here asserts a purpose it lacks.
    assert architecture['audience'] == 'developers'
    assert architecture['ignore'] == list(fi.IGNORE)


def test_a_file_no_directory_claims_lands_on_a_root_chip(tmp_path):
    """`bench.py` has no directory to belong to, and `Unassigned` reads as an
    authoring gap rather than a fact about where the file lives."""
    files = [_entry(f'src/pkg/m{i}.py') for i in range(4)] + [_entry('bench.py')]

    nodes = fi.nodes_for(tmp_path, fi.included_files(_scan(*files)), set())

    root = next(node for node in nodes if node['id'] == 'root')
    assert root['paths'] == ['*']


def test_external_chips_cover_only_declared_dependencies_the_scan_saw(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname = "demo"\n'
        'dependencies = ["pydantic-ai>=2.68", "requests"]\n',
        encoding='utf-8',
    )
    scan = _scan(externals=[
        {'id': 'pypi:pydantic_ai', 'name': 'pydantic_ai', 'files': 9},
        {'id': 'pypi:helpers', 'name': 'helpers', 'files': 5},
    ])

    nodes = fi.externals_for(fi.declared_dependencies(tmp_path), scan)

    # `requests` is declared but never imported here; `helpers` is imported but
    # never declared. Neither is this repository's choice, so neither is a chip.
    assert [node['id'] for node in nodes] == ['dep.pydantic_ai']
    assert nodes[0]['packages'] == ['pypi:pydantic_ai']


def test_external_chips_are_capped_by_importing_file_count(tmp_path):
    deps = [f'pkg{i}' for i in range(fi.MAX_EXTERNAL_NODES + 5)]
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname = "demo"\ndependencies = ' + json.dumps(deps) + '\n',
        encoding='utf-8',
    )
    scan = _scan(externals=[
        {'id': f'pypi:pkg{i}', 'name': f'pkg{i}', 'files': i} for i in range(len(deps))
    ])

    nodes = fi.externals_for(fi.declared_dependencies(tmp_path), scan)

    assert len(nodes) == fi.MAX_EXTERNAL_NODES
    # The cap keeps the biggest, so the smallest survivors are still the largest.
    assert nodes[0]['id'] == f'dep.pkg{len(deps) - 1}'


# --- the gate: a path that claims nothing ------------------------------------

def test_every_declared_path_matches_an_included_file(tmp_path):
    files = [_entry(f'src/pkg/m{i}.py') for i in range(4)] + [_entry('bench.py')]
    included = fi.included_files(_scan(*files))

    architecture = fi.build_architecture(tmp_path, _scan(*files))

    assert fi.validate(architecture, included) == []


def test_a_path_that_claims_no_file_is_an_error_not_a_warning(tmp_path):
    """floorplan only warns (`build.mjs:236`); the first probe shipped 5 such
    paths. Here the same mistake refuses the write."""
    files = [_entry(f'src/pkg/m{i}.py') for i in range(4)]
    included = fi.included_files(_scan(*files))
    architecture = fi.build_architecture(tmp_path, _scan(*files))
    architecture['nodes'].append({
        'id': 'ghost', 'label': 'Ghost', 'kind': 'library', 'paths': ['ghost/**'],
    })

    errors = fi.validate(architecture, included)

    assert any('matches no included file' in error and 'ghost/**' in error
               for error in errors), errors


def test_a_parent_that_is_not_a_node_is_an_error(tmp_path):
    files = [_entry(f'src/pkg/m{i}.py') for i in range(4)]
    architecture = fi.build_architecture(tmp_path, _scan(*files))
    architecture['nodes'][0]['parent'] = 'nowhere'

    errors = fi.validate(architecture, fi.included_files(_scan(*files)))

    assert any('which is not a node' in error for error in errors)


# --- descriptions ------------------------------------------------------------

def test_descriptions_quote_the_codes_own_docstring(tmp_path):
    (tmp_path / 'a.py').write_text(
        '"""Sends the order confirmation.\n\nAnything else is detail."""\n',
        encoding='utf-8')
    (tmp_path / 'bare.py').write_text('X = 1\n', encoding='utf-8')
    (tmp_path / 'srv.py').write_text(
        'def ship():\n    """Marks the order shipped."""\n', encoding='utf-8')
    files = [_entry('a.py'), _entry('bare.py'), _entry('srv.py')]
    routes = [{'file': 'srv.py', 'method': 'GET', 'path': '/ship', 'handler': 'ship'}]

    payload = fi.descriptions(tmp_path, files, routes)

    # `bare.py` has nothing to quote, so it has no entry at all: floorplan falls
    # back to its own name, which is true, rather than a sentence nobody wrote.
    assert payload['files'] == {'a.py': {'description': 'Sends the order confirmation.'}}
    assert payload['routes'] == {'GET /ship': {'description': 'Marks the order shipped.'}}


def test_a_long_docstring_is_cut_at_the_first_sentence(tmp_path):
    """Through `descriptions`, not the sentence helper: what matters is the
    sentence a card shows, and a paragraph pasted into one is the defect."""
    (tmp_path / "long.py").write_text(
        '"""First thing. Then a second sentence nobody asked for."""\n',
        encoding="utf-8")
    (tmp_path / "longer.py").write_text(
        '"""' + "word " * 200 + '"""\n', encoding="utf-8")

    payload = fi.descriptions(tmp_path, [_entry("long.py"), _entry("longer.py")], [])

    assert payload["files"]["long.py"]["description"] == "First thing."
    assert len(payload["files"]["longer.py"]["description"]) <= fi.DESC_LIMIT


# --- recent work -------------------------------------------------------------

def test_recent_work_highlights_only_files_on_the_map(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, 'git_changes', lambda root: (
        {'src/a.py': 'changed', 'docs/manual.md': 'changed'}, ''))
    architecture = {'nodes': [
        {'id': 'src', 'label': 'Source', 'kind': 'library', 'paths': ['src/**']},
    ]}

    payload, note = fi.recent_work(tmp_path, [_entry('src/a.py')], architecture)

    assert note == ''
    task = payload['tasks'][0]
    assert [item['ref'] for item in task['items']] == ['src/a.py']
    # The card names the same chip the reader is looking at.
    assert task['title'] == 'Changes in Source'


def test_recent_work_keeps_the_reason_a_git_read_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, 'git_changes', lambda root: (
        {}, 'recent work unavailable: git is not on PATH'))

    payload, note = fi.recent_work(tmp_path, [_entry('a.py')], {'nodes': []})

    assert payload['tasks'] == []
    assert 'git is not on PATH' in note


def test_an_unchanged_tree_highlights_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, 'git_changes', lambda root: ({}, ''))

    payload, note = fi.recent_work(tmp_path, [_entry('a.py')], {'nodes': []})

    assert payload['tasks'] == []
    assert note == ''


# --- the author --------------------------------------------------------------

def _map_dir(monkeypatch, tmp_path: Path, scan: dict) -> Path:
    target = tmp_path / 'map'
    target.mkdir(parents=True, exist_ok=True)
    (target / 'scan.json').write_text(json.dumps(scan), encoding='utf-8')
    monkeypatch.setattr(fi, 'map_dir', lambda *args, **kwargs: target)
    return target


def test_the_author_writes_all_three_inputs(tmp_path, monkeypatch):
    scan = _scan(*[_entry(f'src/pkg/m{i}.py') for i in range(5)])
    target = _map_dir(monkeypatch, tmp_path, scan)
    monkeypatch.setattr(fi, 'git_changes', lambda root: ({'src/pkg/m0.py': 'changed'}, ''))

    authored = fi.author(tmp_path)

    assert authored.ok is True, authored.error
    assert {path.name for path in authored.paths} == {
        'architecture.json', 'repo.json', 'recent-work.json'}
    for name in ('architecture.json', 'descriptions/repo.json', 'recent-work.json'):
        assert (target / name).is_file(), name
    architecture = json.loads((target / 'architecture.json').read_text(encoding='utf-8'))
    assert fi.validate(architecture, fi.included_files(scan)) == []
    recent = json.loads((target / 'recent-work.json').read_text(encoding='utf-8'))
    assert recent['tasks'][0]['items'] == [{'ref': 'src/pkg/m0.py', 'change': 'changed'}]


def test_the_author_refuses_without_a_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, 'map_dir', lambda *args, **kwargs: tmp_path / 'nothing')

    authored = fi.author(tmp_path)

    assert authored.ok is False
    assert 'cannot read the scan' in authored.error


def test_the_author_refuses_a_scan_with_no_code(tmp_path, monkeypatch):
    _map_dir(monkeypatch, tmp_path, _scan(_entry('README.md', category='docs')))

    authored = fi.author(tmp_path)

    assert authored.ok is False
    assert 'no code files' in authored.error


def test_a_failed_git_read_is_reported_rather_than_hidden(tmp_path, monkeypatch):
    """`recent work` is a nicety; a silent empty file would read as "nothing
    changed", which is a claim the author cannot make."""
    _map_dir(monkeypatch, tmp_path, _scan(*[_entry(f'src/pkg/m{i}.py') for i in range(5)]))
    monkeypatch.setattr(fi, 'git_changes', lambda root: ({}, 'recent work unavailable: boom'))

    authored = fi.author(tmp_path)

    assert authored.ok is True
    assert authored.notes == ('recent work unavailable: boom',)


# --- the real thing ----------------------------------------------------------

@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
@pytest.mark.skipif(floorplan.floorplan_home() is None, reason='floorplan is not vendored')
async def test_the_map_builds_itself_on_a_fixture_repo(tmp_path, monkeypatch):
    """The acceptance line, end to end: authored from the scan, then built with
    no errors, no warnings, and nothing left unassigned."""
    repo = tmp_path / 'fixture'
    (repo / 'src' / 'demo').mkdir(parents=True)
    (repo / 'pyproject.toml').write_text(
        '[project]\nname = "demo"\ndescription = "A demo repo."\n', encoding='utf-8')
    (repo / 'src' / 'demo' / 'core.py').write_text(
        '"""Holds the things.\n\nMore detail."""\n\nVALUE = 1\n', encoding='utf-8')
    (repo / 'src' / 'demo' / 'cli.py').write_text(
        '"""Runs the thing."""\n\n\ndef main() -> None:\n    """Start it."""\n',
        encoding='utf-8')
    (repo / 'README.md').write_text('# demo\n', encoding='utf-8')
    # The author's only subprocess is `git status`; a fixture outside git would
    # otherwise contribute a "recent work unavailable" note by design.
    monkeypatch.setattr(fi, 'git_changes', lambda root: ({}, ''))

    outcome = await floorplan.build_map(repo, home=tmp_path / 'home')

    assert outcome.ok is True, outcome.error
    assert outcome.warnings == ()
    assert outcome.files.get('unassigned') == 0
    target = floorplan.map_dir(repo, tmp_path / 'home')
    for name in ('architecture.json', 'descriptions/repo.json',
                 'recent-work.json', 'index.html'):
        assert (target / name).is_file(), name
    assert (target / 'query.mjs').is_file()  # what #378 reads
