"""Repo map: a compact, budget-sized overview of a codebase — file tree plus
key signatures (functions/classes) — auto-included at session start so the
agent orients in one hop instead of twenty tool calls.

Python signatures come from the ast module; JS/TS from tree-sitter. When the
map exceeds its budget, signature sections drop first (the file tree survives).
"""

import ast
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .tools import SKIP_DIRS

SOURCE_EXTENSIONS = {'.py', '.js', '.jsx', '.mjs', '.ts', '.tsx'}
DEFAULT_BUDGET = 6000


def _python_signatures(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except (SyntaxError, OSError):
        return []

    def args_str(node) -> str:
        try:
            names = [a.arg for a in node.args.args]
            if node.args.vararg:
                names.append(f'*{node.args.vararg.arg}')
            if node.args.kwarg:
                names.append(f'**{node.args.kwarg.arg}')
            return ', '.join(names)
        except Exception:
            return ''

    sigs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sigs.append(f'    def {node.name}({args_str(node)})')
        elif isinstance(node, ast.ClassDef):
            sigs.append(f'    class {node.name}')
    return sigs


def js_signatures(path: Path) -> list[str]:
    """Top-level JS/TS function/class signatures (tree-sitter; [] if unavailable)."""
    try:
        source = path.read_bytes()
    except OSError:
        return []
    return js_signatures_source(source, path.suffix)


def js_signatures_source(source: bytes, suffix: str) -> list[str]:
    """Same, from raw source bytes (suffix like '.ts')."""
    try:
        from tree_sitter import Parser

        from .jslang import language_for
    except ImportError:
        return []
    parser = Parser(language_for(suffix))
    try:
        tree = parser.parse(source)
    except Exception:
        return []

    def name_of(node):
        name_node = node.child_by_field_name('name')
        return name_node.text.decode() if name_node else None

    sigs = []

    def walk(node, depth):
        if node.type in ('function_declaration', 'class_declaration') and depth <= 2:
            name = name_of(node)
            if name:
                kind = 'class' if 'class' in node.type else 'function'
                sigs.append(f'    {kind} {name}')
                return
        if node.type == 'variable_declarator' and depth <= 2:
            value = node.child_by_field_name('value')
            if value is not None and value.type in ('arrow_function', 'function_expression'):
                name_node = node.child_by_field_name('name')
                if name_node:
                    sigs.append(f'    const {name_node.text.decode()} = fn')
                    return
        for child in node.children:
            walk(child, depth + 1)

    walk(tree.root_node, 0)
    return sigs


def build_repo_map(workdir: Path, budget: int = DEFAULT_BUDGET,
                   extensions: set[str] | None = None) -> str:
    """Compact map: source file tree + signatures, within budget chars."""
    exts = extensions or SOURCE_EXTENSIONS
    root = Path(workdir)
    files = []
    for f in sorted(root.rglob('*')):
        if not f.is_file() or f.suffix not in exts:
            continue
        rel = f.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        files.append(rel)

    lines: list[str] = []
    size = 0

    def add(line: str) -> bool:
        nonlocal size
        if size + len(line) + 1 > budget:
            return False
        lines.append(line)
        size += len(line) + 1
        return True

    add(f'[repo: {len(files)} source files]')
    added_dirs: set[str] = set()
    for rel in files:
        parts = rel.parts
        truncated = False
        for i in range(1, len(parts)):
            d = '/'.join(parts[:i]) + '/'
            if d not in added_dirs:
                added_dirs.add(d)
                if not add('  ' * (i - 1) + parts[i - 1] + '/'):
                    truncated = True
                    break
        if truncated:
            continue
        if not add('  ' * (len(parts) - 1) + parts[-1]):
            continue
        if rel.suffix == '.py':
            for sig in _python_signatures(root / rel):
                if not add(sig):
                    break
        elif rel.suffix in {'.js', '.jsx', '.mjs', '.ts', '.tsx'}:
            for sig in js_signatures(root / rel):
                if not add(sig):
                    break
    return '\n'.join(lines)


def build_repo_map_toolset(workdir: Path) -> FunctionToolset:
    """The `repo_map` tool: on-demand compact overview (also auto-included in
    instructions when configured)."""

    def repo_map() -> str:
        return build_repo_map(workdir) or '(empty workdir)'

    return FunctionToolset([repo_map])
