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
"""Project structure overview (R42 #95): per-file symbol outlines for humans.

Reuses repo_map's parsers (ast for Python, tree-sitter for JS/TS) but returns
structured JSON — path, line count, symbols with kinds and line numbers —
instead of a budget-capped text map.
"""

import ast as _ast
from pathlib import Path

from codingdude.pyparse import parse_python

from .tools import SKIP_DIRS

SOURCE_EXTENSIONS = {'.py', '.js', '.jsx', '.mjs', '.ts', '.tsx'}


def project_structure(workdir: Path, max_files: int = 200) -> dict:
    """Per-file symbol outlines (kind/name/size) for the project tree."""
    root = Path(workdir)
    files: list[dict] = []
    for f in sorted(root.rglob('*')):
        if not f.is_file() or f.suffix not in SOURCE_EXTENSIONS:
            continue
        rel = f.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in f.relative_to(root).parts):
            continue
        try:
            lines = f.read_text(encoding='utf-8', errors='replace').count('\n') + 1
        except OSError:
            continue
        files.append({
            'path': rel,
            'lines': lines,
            'symbols': _python_symbols(f) if f.suffix == '.py' else _js_symbols(f),
        })
        if len(files) >= max_files:
            break
    return {'files': files}


def _python_symbols(path: Path) -> list[dict]:
    try:
        tree = parse_python(path.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError:
        return []
    out: list[dict] = []
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            out.append({'kind': 'function', 'name': node.name, 'line': node.lineno})
        elif isinstance(node, _ast.ClassDef):
            out.append({'kind': 'class', 'name': node.name, 'line': node.lineno})
    return out


def _js_symbols(path: Path) -> list[dict]:
    from .repo_map import js_symbols_source

    return [
        {'kind': s.kind, 'name': s.name, 'line': s.line}
        for s in js_symbols_source(path.read_bytes(), path.suffix)
    ]
