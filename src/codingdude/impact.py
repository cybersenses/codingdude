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
"""Edited-file dependency/impact graph (#86, R38 phase 3).

For each changed source file, find which other files in the repo depend on
it (reverse import/reference edges), so the UI can render "if you break
this, what else breaks" as a Mermaid flowchart.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from codingdude.pyparse import parse_python

from .repo_map import SKIP_DIRS

SOURCE_EXTS = {'.py', '.js', '.jsx', '.ts', '.tsx'}


def _module_name(rel: str) -> str:
    """'src/pkg/mod.py' -> 'pkg.mod' (repo top-level dir treated as root)."""
    parts = Path(rel).with_suffix('').parts
    if parts and parts[-1] == '__init__':
        parts = parts[:-1]
    if len(parts) > 1:
        parts = parts[1:]
    return '.'.join(parts)


def _py_imports_of(text: str) -> set[str]:
    try:
        tree = parse_python(text)
    except SyntaxError:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


_JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\s+)['"]([^'"]+)['"]""")


def _js_targets_of(text: str) -> set[str]:
    """Import specifiers from a JS/TS file ('./x', 'react', ...)."""
    return set(_JS_IMPORT.findall(text))


def _js_stems(rel: str) -> set[str]:
    """Plausible relative-import specifiers for a JS/TS file path."""
    p = Path(rel).with_suffix('')
    if not p.parts:
        return set()
    return {f'./{p.as_posix()}', f'./{p.parts[-1]}'}


def impact_graph(workdir: Path, changed: list[str]) -> dict:
    """{'edges': [{path, dependents:[...]}], 'orphans': changed with none}."""
    workdir = Path(workdir)
    changed_set = set(changed)
    py_changed = [(c, _module_name(c)) for c in changed if c.endswith('.py')]
    js_changed = [(c, _js_stems(c)) for c in changed if c not in {x for x, _ in py_changed}]

    dependents_of: dict[str, set[str]] = {c: set() for c in changed}

    for f in sorted(workdir.rglob('*')):
        if not f.is_file() or f.suffix not in SOURCE_EXTS:
            continue
        try:
            rel = f.relative_to(workdir).as_posix()
        except ValueError:
            continue
        if rel in changed_set or any(part in SKIP_DIRS for part in f.relative_to(workdir).parts):
            continue
        try:
            text = f.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if f.suffix == '.py':
            mods = _py_imports_of(text)
            for c, mod in py_changed:
                if mod in mods:
                    dependents_of[c].add(rel)
        else:
            targets = _js_targets_of(text)
            for c, stems in js_changed:
                if targets & stems:
                    dependents_of[c].add(rel)

    return {
        'edges': [{'path': c, 'dependents': sorted(dependents_of[c])} for c in changed],
        'orphans': [c for c in changed if not dependents_of[c]],
    }
