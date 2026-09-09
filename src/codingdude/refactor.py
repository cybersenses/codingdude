"""Rename/refactor: rename a symbol (function/class) across all project files.

Python uses the ast module (precise, no formatting damage). JS/TS uses
tree-sitter define/reference analysis — same infrastructure as dead-code
detection. Files are rewritten with targeted name replacements only.
"""

import ast
from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from .tools import SKIP_DIRS

SOURCE_EXTENSIONS = {'.py', '.js', '.jsx', '.mjs', '.ts', '.tsx'}
JS_EXTENSIONS = {'.js', '.jsx', '.mjs', '.ts', '.tsx'}


def _iter_source(workdir: Path):
    root = Path(workdir)
    for f in sorted(root.rglob('*')):
        if not f.is_file() or f.suffix not in SOURCE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in f.relative_to(root).parts):
            continue
        yield f


def _python_replace(path: Path, old: str, new: str) -> int:
    """Replace only identifier-classified occurrences via AST positions."""
    source = path.read_text(encoding='utf-8', errors='replace')
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    by_line: dict[int, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == old:
            by_line.setdefault(node.lineno - 1, []).append(node.col_offset)
        elif isinstance(node, ast.Attribute) and node.attr == old and node.end_col_offset is not None:
            by_line.setdefault(node.lineno - 1, []).append(node.end_col_offset - len(old))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == old and alias.asname is None:
                    by_line.setdefault(node.lineno - 1, []).append(alias.col_offset)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == old:
            prefix = 'async def ' if isinstance(node, ast.AsyncFunctionDef) else ('def ' if isinstance(node, ast.FunctionDef) else 'class ')
            by_line.setdefault(node.lineno - 1, []).append(node.col_offset + len(prefix))
    count = 0
    lines = source.split('\n')
    for lineno in sorted(by_line, reverse=True):
        for col in sorted(set(by_line[lineno]), reverse=True):
            line = lines[lineno]
            if line[col:col + len(old)] == old:
                lines[lineno] = line[:col] + new + line[col + len(old):]
                count += 1
    if count:
        path.write_text('\n'.join(lines), encoding='utf-8')
    return count


def _js_replace(path: Path, old: str, new: str) -> int:
    """Tree-sitter identifier replacement for JS/TS."""
    import tree_sitter_javascript as tsjs
    from tree_sitter import Language, Parser

    parser = Parser(Language(tsjs.language()))
    source = path.read_text(encoding='utf-8', errors='replace')
    try:
        tree = parser.parse(source.encode('utf-8'))
    except Exception:
        return 0
    edits: list[tuple[int, int]] = []

    def walk(node):
        if node.type == 'identifier' and node.text.decode() == old:
            edits.append((node.start_byte, node.end_byte))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    # dedupe overlapping (child scopes may report the same span)
    edits = sorted(set(edits))
    if not edits:
        return 0
    data = source.encode('utf-8')
    for start, end in sorted(edits, reverse=True):
        data = data[:start] + new.encode('utf-8') + data[end:]
    path.write_text(data.decode('utf-8'), encoding='utf-8')
    return len(edits)


def build_refactor_toolset(workdir: Path) -> FunctionToolset:
    """The `rename_symbol` tool: safe project-wide symbol rename."""

    async def rename_symbol(old_name: str, new_name: str) -> str:
        """Rename a function or class across every project file. Reports the
        number of replacements per language."""
        if not old_name or not new_name or old_name == new_name:
            raise ModelRetry('Provide distinct non-empty old_name and new_name.')
        total = {'python': 0, 'js': 0}
        for f in _iter_source(Path(workdir)):
            if f.suffix == '.py':
                total['python'] += _python_replace(f, old_name, new_name)
            elif f.suffix in JS_EXTENSIONS:
                total['js'] += _js_replace(f, old_name, new_name)
        if total['python'] == 0 and total['js'] == 0:
            raise ModelRetry(
                f'No occurrences of {old_name!r} found to rename. '
                'Check the spelling with grep first.'
            )
        return (
            f'Renamed {old_name!r} → {new_name!r}: '
            f"{total['python'] + total['js']} replacements."
        )

    return FunctionToolset([rename_symbol])
