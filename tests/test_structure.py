"""Tests for the project structure seam (R42 #95, #100 hardening)."""

from pathlib import Path

from codingdude.structure import project_structure


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    return p


def test_python_symbols_with_lines(tmp_path):
    _write(tmp_path, 'm.py', 'class A:\n    def go(self):\n        pass\n')
    files = project_structure(tmp_path)['files']
    syms = {s['name']: s for s in files[0]['symbols']}
    assert syms['A']['kind'] == 'class' and syms['A']['line'] == 1
    assert syms['go']['kind'] == 'function' and syms['go']['line'] == 2


def test_js_arrow_functions_are_symbols_with_lines(tmp_path):
    _write(tmp_path, 'm.jsx', 'const App = () => 1;\nconst helper = () => 2;\n')
    files = project_structure(tmp_path)['files']
    syms = {s['name']: s for s in files[0]['symbols']}
    assert syms['App']['kind'] == 'const'
    assert syms['App']['line'] == 1
    assert syms['helper']['line'] == 2


def test_skip_dirs_and_non_source(tmp_path):
    _write(tmp_path, 'node_modules/pkg/x.js', 'function a() {}\n')
    _write(tmp_path, 'notes.txt', 'hello\n')
    assert project_structure(tmp_path)['files'] == []


def test_unparseable_python_yields_no_symbols_not_crash(tmp_path):
    _write(tmp_path, 'bad.py', 'def broken(:\n')
    files = project_structure(tmp_path)['files']
    assert files[0]['symbols'] == []
