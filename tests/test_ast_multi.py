"""R26 #47: find_definition / find_references multi-language (registry-driven).

Python keeps its dedicated path; all other registered Tier-3 languages
resolve definitions via the langs registry and tsedit spans. References
scan grammar identifier nodes, excluding definition sites.
"""

from codingdude.ast_tools import build_ast_toolset


def _tool(workdir, name):
    return build_ast_toolset(workdir).tools[name].function


def test_find_definition_rust(tmp_path):
    (tmp_path / 'lib.rs').write_text(
        'fn add(a: i32, b: i32) -> i32 {\n  a + b\n}\n'
    )
    out = _tool(tmp_path, 'find_definition')('add')
    assert 'lib.rs:1' in out


def test_find_definition_go(tmp_path):
    (tmp_path / 'main.go').write_text(
        'package main\n\nfunc add(a int, b int) int {\n\treturn a + b\n}\n'
    )
    out = _tool(tmp_path, 'find_definition')('add')
    assert 'main.go:3' in out


def test_find_definition_c(tmp_path):
    (tmp_path / 'm.c').write_text('int add(int a, int b) {\n  return a+b;\n}\n')
    out = _tool(tmp_path, 'find_definition')('add')
    assert 'm.c:1' in out


def test_find_references_rust_excludes_definition(tmp_path):
    (tmp_path / 'lib.rs').write_text(
        'fn add(a: i32, b: i32) -> i32 {\n  a + b\n}\n\n'
        'fn use_add() -> i32 {\n  add(1, 2)\n}\n'
    )
    out = _tool(tmp_path, 'find_references')('add')
    assert 'lib.rs:6' in out   # the call site
    assert 'lib.rs:1' not in out  # the definition itself


def test_python_path_unchanged(tmp_path):
    (tmp_path / 'm.py').write_text('def add(a, b):\n    return a + b\n')
    out = _tool(tmp_path, 'find_definition')('add')
    assert 'm.py:1' in out
