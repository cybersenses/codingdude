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
    assert by_id['entry']['orphan'] is False
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


def test_node_carries_line_numbers(tmp_path):
    _write(tmp_path, 'm.py', 'def a():\n    pass\n')
    g = build_call_graph(tmp_path / 'm.py')
    assert g['nodes'][0]['line'] == 1
