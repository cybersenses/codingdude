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
import os
import re
from collections.abc import Iterator
from pathlib import Path

from codingdude.pyparse import parse_python

from .tools import skip_dir

SOURCE_EXTS = {'.py', '.js', '.jsx', '.ts', '.tsx'}


def _module_name(rel: str) -> str:
    """'src/pkg/mod.py' -> 'pkg.mod' (repo top-level dir treated as root)."""
    parts = Path(rel).with_suffix('').parts
    if parts and parts[-1] == '__init__':
        parts = parts[:-1]
    if len(parts) > 1:
        parts = parts[1:]
    return '.'.join(parts)


def _package_of(rel: str) -> str:
    """The package a file's relative imports resolve against.

    'src/pkg/b.py' -> 'pkg'; 'src/pkg/sub/deep.py' -> 'pkg.sub';
    'src/pkg/__init__.py' -> 'pkg' (a package's own module name *is* its
    package, so `from . import x` there means `pkg.x`).

    A module the top-level-dir rule leaves bare ('src/mod.py' -> 'mod') has
    package '' — and a level-1 relative import in it resolves to its bare
    name, which is what :func:`_module_name` also yields. The two agree on
    purpose: this repo's `src/` layout and a flat layout both produce edges.
    """
    if Path(rel).stem == '__init__':
        return _module_name(rel)
    name = _module_name(rel)
    return name.rpartition('.')[0] if '.' in name else ''


def _relative_base(package: str, level: int) -> str | None:
    """The package `level` dots up from `package`; None if that leaves the root.

    `level` 1 is the importing module's own package, 2 its parent, and so on.
    Climbing past the root is an ImportError at runtime, not an edge — the
    graph must not invent one.
    """
    parts = package.split('.') if package else []
    drop = level - 1
    if drop > len(parts):
        return None
    return '.'.join(parts[: len(parts) - drop] if drop else parts)


def _py_imports_of(text: str, package: str = '') -> set[str]:
    """Absolute dotted module names this Python source imports.

    `package` is the importing file's own package (:func:`_package_of`), which
    is what makes a relative import comparable at all: `from .tools import X`
    in `pkg/a.py` imports `pkg.tools`, and dropping the level (`node.level`)
    yields a bare `'tools'` that never equals `_module_name('src/pkg/tools.py')`
    — the #373 defect, which left 49 of this repo's 80 modules with no
    intra-package edges at all.
    """
    try:
        tree = parse_python(text)
    except SyntaxError:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            base = _relative_base(package, node.level)
            if base is None:
                continue
            if node.module:
                mods.add(f'{base}.{node.module}' if base else node.module)
            else:
                # `from . import x`: Python imports the submodule `pkg.x` when
                # one exists, falling back to an attribute of `pkg`. The graph
                # asks what is imported, so the submodule spelling is the one
                # that can match a changed file.
                mods.update(
                    f'{base}.{a.name}' if base else a.name for a in node.names
                )
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


def _source_files(workdir: Path, suffixes: set[str]) -> Iterator[Path]:
    """Every file under workdir with one of `suffixes`, minus skipped subtrees.

    os.walk rather than rglob: rglob descends into .venv/node_modules/.git and
    hands back every entry, so the caller pays for ~30k directory entries and
    stat() calls it then discards (#371). Pruning dirnames in place skips the
    subtree outright. Order is left as the filesystem gives it — the result is
    sorted where it is returned, so walk order cannot leak.

    The skip test is `tools.skip_dir`, the name-level half of the rule — this
    walker prunes directories, so the parts-aware half (`tools.skip_parts`,
    used by the rglob walkers) would be the wrong shape here. Either way the
    answer covers SKIP_DIRS, the .venv-* side venvs and plain `venv`
    (R75/#255); SKIP_DIRS alone walked 24736 of this repo's 25122 source files
    out of .venv-harness/.venv-verify — 98% of the cost this fix targets.
    """
    for root, dirnames, filenames in os.walk(workdir):
        dirnames[:] = [d for d in dirnames if not skip_dir(d)]
        for name in filenames:
            path = Path(root) / name
            if path.suffix in suffixes:
                yield path


def impact_graph(workdir: Path, changed: list[str]) -> dict:
    """{'edges': [{path, dependents:[...]}], 'orphans': changed with none}."""
    workdir = Path(workdir)
    # Nothing changed has a known answer. Returning before the walk matters:
    # the Diff panel polls this every 2s, and on a repo carrying a venv the
    # walk cost ~62s to prove the empty result (#371).
    if not changed:
        return {'edges': [], 'orphans': []}

    changed_set = set(changed)
    py_changed = [(c, _module_name(c)) for c in changed if c.endswith('.py')]
    js_changed = [(c, _js_stems(c)) for c in changed if c not in {x for x, _ in py_changed}]

    dependents_of: dict[str, set[str]] = {c: set() for c in changed}

    # Only files in a changed file's own language can name it, so neither
    # language pays for the other's tree.
    suffixes: set[str] = set()
    if py_changed:
        suffixes.add('.py')
    if js_changed:
        suffixes.update(SOURCE_EXTS - {'.py'})
    py_tails = {mod.rsplit('.', 1)[-1] for _, mod in py_changed}
    js_words = {stem.rsplit('/', 1)[-1] for _, stems in js_changed for stem in stems}

    # A dependent must spell the changed module out in its own source, and one
    # segment of that name is enough: every import the AST scan can match
    # contains the module's LAST segment as an identifier (`from .b import V`,
    # `from pkg.b import V`, `import pkg.b`, `from . import b`). Checking that
    # first keeps ast.parse off the files that cannot possibly answer —
    # 61s -> 6s on this repo, with identical dependents.
    #
    # The last segment, not the first (#373): resolving relative imports means
    # `from .b import V` now *is* an edge on `pkg.b`, and its text contains
    # `.b`, never `pkg`. Filtering on `pkg` would have silently dropped the
    # very dependents the fix adds. Word boundaries, not a bare substring: a
    # one-letter module name must not match every word in the file, or the
    # filter stops filtering and the walk pays full parse cost again.
    py_prefilter = (
        re.compile(
            r'(?<!\w)(?:'
            + '|'.join(re.escape(t) for t in sorted(py_tails))
            + r')(?!\w)'
        )
        if py_tails else None
    )

    for f in _source_files(workdir, suffixes):
        try:
            rel = f.relative_to(workdir).as_posix()
        except ValueError:
            continue
        if rel in changed_set:
            continue
        try:
            text = f.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if f.suffix == '.py':
            if py_prefilter is not None and not py_prefilter.search(text):
                continue
            mods = _py_imports_of(text, _package_of(rel))
            for c, mod in py_changed:
                if mod in mods:
                    dependents_of[c].add(rel)
        else:
            if not any(word in text for word in js_words):
                continue
            targets = _js_targets_of(text)
            for c, stems in js_changed:
                if targets & stems:
                    dependents_of[c].add(rel)

    return {
        'edges': [{'path': c, 'dependents': sorted(dependents_of[c])} for c in changed],
        'orphans': [c for c in changed if not dependents_of[c]],
    }
