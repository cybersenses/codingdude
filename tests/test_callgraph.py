"""Tests for the user-facing call graph seam (R42 #94)."""

from pathlib import Path

from codingdude.callgraph import build_call_graph


def _write(tmp_path: Path, name: str, code: str) -> Path:
    p = tmp_path / name
    p.write_text(code, encoding='utf-8')
    return p


def test_python_calls_within_file(tmp_path):
    _write(tmp_path, 'm.py', '''
def helper():
    return 1

def main():
    helper()
    helper()
''')
    g = build_call_graph(tmp_path / 'm.py')
    names = {n['name'] for n in g['nodes']}
    assert names == {'helper', 'main'}
    assert ('main', 'helper') in {tuple(e) for e in g['edges']}


def test_python_methods_nested_under_classes(tmp_path):
    _write(tmp_path, 'm.py', '''
class Greeter:
    def greet(self):
        self._talk()

    def _talk(self):
        pass
''')
    g = build_call_graph(tmp_path / 'm.py')
    ids = {n['id'] for n in g['nodes']}
    assert 'Greeter.greet' in ids and 'Greeter._talk' in ids
    assert ('Greeter.greet', 'Greeter._talk') in {tuple(e) for e in g['edges']}


def test_orphans_flagged(tmp_path):
    _write(tmp_path, 'm.py', '''
def unused():
    pass

def entry():
    helper()

def helper():
    pass
''')
    g = build_call_graph(tmp_path / 'm.py')
    by_id = {n['id']: n for n in g['nodes']}
    assert by_id['unused']['orphan'] is True
    # entry() calls helper but nothing calls entry => dead code too.
    assert by_id['entry']['orphan'] is True
    assert by_id['helper']['orphan'] is False


def test_dead_but_calling_function_flagged_orphan(tmp_path):
    _write(tmp_path, 'm.py', '''
def dead():
    helper()

def helper():
    pass
''')
    g = build_call_graph(tmp_path / 'm.py')
    by_id = {n['id']: n for n in g['nodes']}
    # dead() is never called => dead code, even though it calls helper().
    assert by_id['dead']['orphan'] is True
    assert by_id['helper']['orphan'] is False


def test_unparseable_file_fails_fast(tmp_path):
    p = _write(tmp_path, 'm.py', 'def broken(:\n')
    try:
        build_call_graph(p)
    except SyntaxError:
        pass
    else:
        raise AssertionError('expected SyntaxError for unparseable python')


def test_missing_file_fails_fast(tmp_path):
    try:
        build_call_graph(tmp_path / 'nope.py')
    except FileNotFoundError:
        pass
    else:
        raise AssertionError('expected FileNotFoundError')


def test_js_calls(tmp_path):
    _write(tmp_path, 'm.js', '''
function helper() { return 1; }
function main() { helper(); }
''')
    g = build_call_graph(tmp_path / 'm.js')
    names = {n['name'] for n in g['nodes']}
    assert 'main' in names
    assert ('main', 'helper') in {tuple(e) for e in g['edges']}


def test_js_arrow_and_const_functions_are_callables(tmp_path):
    _write(tmp_path, 'm.jsx', '''
const helper = () => 1;
const main = () => { helper(); };
export default main;
''')
    g = build_call_graph(tmp_path / 'm.jsx')
    names = {n['name'] for n in g['nodes']}
    assert names == {'helper', 'main'}
    assert ('main', 'helper') in {tuple(e) for e in g['edges']}
    by_name = {n['name']: n for n in g['nodes']}
    # main is never called (export is not a call) => dead code; helper is called by main.
    assert by_name['main']['orphan'] is True
    assert by_name['helper']['orphan'] is False


def test_js_self_edge_not_emitted_for_nested_calls(tmp_path):
    _write(tmp_path, 'm.js', '''
const outer = () => {
  const inner = () => 1;
  inner();
};
''')
    g = build_call_graph(tmp_path / 'm.js')
    nodes = {n['name'] for n in g['nodes']}
    assert nodes == {'outer', 'inner'}
    edges = {tuple(e) for e in g['edges']}
    assert ('outer', 'inner') in edges
    assert all(a != b for a, b in edges), 'self-edges are bogus'


def test_node_carries_line_numbers(tmp_path):
    _write(tmp_path, 'm.py', 'def a():\n    pass\n')
    g = build_call_graph(tmp_path / 'm.py')
    assert g['nodes'][0]['line'] == 1


# ---- #101 (R43): module-level architecture map (cross-file import edges) ----

from codingdude.callgraph import build_module_graph  # noqa: E402


def test_python_relative_import_edge(tmp_path):
    _write(tmp_path, 'main.py', 'from helpers import util\n\ndef run():\n    util()\n')
    _write(tmp_path, 'helpers.py', 'def util():\n    return 1\n')
    g = build_module_graph(tmp_path)
    ids = {n['id'] for n in g['nodes']}
    assert ids == {'main.py', 'helpers.py'}
    assert ('main.py', 'helpers.py') in {tuple(e) for e in g['edges']}


def test_python_package_relative_import(tmp_path):
    (tmp_path / 'pkg').mkdir()
    _write(tmp_path, 'pkg/__init__.py', '')
    _write(tmp_path, 'pkg/core.py', 'X = 1\n')
    _write(tmp_path, 'pkg/app.py', 'from .core import X\n')
    _write(tmp_path, 'main.py', 'from pkg.app import run\n')
    g = build_module_graph(tmp_path)
    edges = {tuple(e) for e in g['edges']}
    assert ('pkg/app.py', 'pkg/core.py') in edges
    assert ('main.py', 'pkg/app.py') in edges


def test_external_imports_not_edges(tmp_path):
    _write(tmp_path, 'm.py', 'import os\nfrom fastapi import FastAPI\n')
    g = build_module_graph(tmp_path)
    assert g['edges'] == []
    assert [n['id'] for n in g['nodes']] == ['m.py']


def test_js_relative_import_edge(tmp_path):
    _write(tmp_path, 'main.js', "import { util } from './helpers.js';\nutil();\n")
    _write(tmp_path, 'helpers.js', 'export const util = () => 1;\n')
    g = build_module_graph(tmp_path)
    assert ('main.js', 'helpers.js') in {tuple(e) for e in g['edges']}


def test_unresolvable_import_does_not_crash_or_edge(tmp_path):
    _write(tmp_path, 'm.py', 'from .missing import thing\nfrom doesnotexist import x\n')
    g = build_module_graph(tmp_path)
    assert g['edges'] == []


def test_module_graph_skips_venv_and_orphans_flagged(tmp_path):
    _write(tmp_path, 'main.py', 'import helper\n')
    _write(tmp_path, 'helper.py', 'X = 1\n')
    venv = tmp_path / '.venv' / 'lib'
    venv.mkdir(parents=True)
    _write(venv, 'site.py', 'Y = 2\n')
    g = build_module_graph(tmp_path)
    ids = {n['id'] for n in g['nodes']}
    assert 'main.py' in ids and 'helper.py' in ids
    assert not any(i.startswith('.venv') for i in ids)
    by_id = {n['id']: n for n in g['nodes']}
    assert by_id['main.py']['orphan'] is True   # nothing imports it
    assert by_id['helper.py']['orphan'] is False


def test_module_graph_capped(tmp_path):
    for i in range(12):
        _write(tmp_path, f'm{i}.py', f'X = {i}\n')
    g = build_module_graph(tmp_path, max_files=10)
    assert len(g['nodes']) <= 10
