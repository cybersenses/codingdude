"""AST tools: find_definition / find_references for Python via tree-sitter."""

from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from .tools import SKIP_DIRS

MAX_RESULTS = 50


def _python_files(root: Path, path: str = '.'):
    import re

    target = (root / path).resolve()
    if target.is_file():
        yield target
        return
    for f in sorted(target.rglob('*.py')):
        if any(part in SKIP_DIRS for part in f.relative_to(root).parts):
            continue
        yield f


def _parse(source: bytes):
    import tree_sitter_python
    from tree_sitter import Language, Parser

    parser = Parser(Language(tree_sitter_python.language()))
    return parser.parse(source)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def build_ast_toolset(workdir: Path) -> FunctionToolset:
    """AST-accurate navigation for Python; graceful degradation for other languages."""

    def _check_python(path: str) -> None:
        if not str(path).endswith('.py'):
            raise ModelRetry(
                f'{path} is not a Python file. AST tools currently support Python '
                'only; use grep for other languages.'
            )

    def find_definition(symbol: str, path: str = '.') -> str:
        """Locate where a function/class is defined (file:line). Python only."""
        _check_python(path)
        results = []
        for f in _python_files(workdir, path):
            tree = _parse(f.read_bytes())
            for node in _walk(tree.root_node):
                if node.type in ('function_definition', 'class_definition'):
                    name_node = node.child_by_field_name('name')
                    if name_node and name_node.text == symbol.encode():
                        rel = f.relative_to(workdir)
                        line = node.start_point[0] + 1
                        results.append(f'definition: {rel}:{line}: {symbol}')
                        if len(results) >= MAX_RESULTS:
                            break
            if len(results) >= MAX_RESULTS:
                break
        return '\n'.join(results) or f'(no definition of {symbol!r} found)'

    def find_references(symbol: str, path: str = '.') -> str:
        """Find usages of a symbol (imports, calls, names) across files. Python only."""
        _check_python(path)
        results = []
        for f in _python_files(workdir, path):
            tree = _parse(f.read_bytes())
            for node in _walk(tree.root_node):
                if node.type != 'identifier' or node.text != symbol.encode():
                    continue
                parent = node.parent
                if parent and parent.type in (
                    'function_definition',
                    'class_definition',
                ) and parent.child_by_field_name('name') is node:
                    continue  # the definition itself, not a reference
                rel = f.relative_to(workdir)
                line = node.start_point[0] + 1
                results.append(f'reference: {rel}:{line}')
                if len(results) >= MAX_RESULTS:
                    break
            if len(results) >= MAX_RESULTS:
                break
        return '\n'.join(results) or f'(no references to {symbol!r} found)'

    return FunctionToolset([find_definition, find_references])
