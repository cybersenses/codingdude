"""Dead-code detection across languages: vulture (Python) + tree-sitter (JS/TS).

`find_dead_code` reports symbols that are defined but never referenced —
execution-level dead weight that test coverage cannot see. Confidence and
formatting are per-language; results are merged into one report.
"""

import asyncio
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .tools import SKIP_DIRS

JS_EXTENSIONS = {'.js', '.jsx', '.mjs', '.ts', '.tsx'}
SKIP_NAMES = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache', 'dist', '.next', 'build'}


def _iter_source_files(workdir: Path, extensions: set[str], path: str = '.'):
    root = Path(workdir).resolve()
    target = (root / path).resolve() if path else root
    try:
        target.relative_to(root)
    except ValueError:
        from pydantic_ai import ModelRetry

        raise ModelRetry(
            f'Path {path!r} is outside the Workdir. '
            'Only paths inside the Workdir are accessible.'
        ) from None
    if target.is_file():
        yield target
        return
    for f in sorted(target.rglob('*')):
        if not f.is_file() or f.suffix not in extensions:
            continue
        if any(part in SKIP_DIRS for part in f.relative_to(root).parts):
            continue
        yield f


async def _vulture_python(workdir: Path, path: str, min_confidence: int) -> str:
    files = [str(f) for f in _iter_source_files(workdir, {'.py'}, path)]
    if not files:
        return ''
    proc = await asyncio.create_subprocess_exec(
        sys_executable(), '-m', 'vulture', *files, '--min-confidence', str(min_confidence),
        cwd=workdir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    return stdout.decode(errors='replace').strip()


def _tree_sitter_definitions_and_refs(source: bytes, lang_module) -> tuple[set[str], set[str], dict[str, list[tuple]]]:
    """Returns (defined, referenced, def_locations) for functions and classes.

    Definition name nodes are excluded from references by skipping the name
    child when recursing into a declaration's children.
    """
    from tree_sitter import Parser

    parser = Parser(lang_module)
    tree = parser.parse(source)
    defined: set[str] = set()
    referenced: set[str] = set()
    locations: dict[str, list[tuple[str, int]]] = {}

    def walk(node):
        if node.type in ('function_declaration', 'function_definition', 'method_definition',
                         'class_declaration', 'class_definition'):
            name_node = node.child_by_field_name('name')
            if name_node:
                defined.add(name_node.text.decode())
                locations.setdefault(name_node.text.decode(), []).append(
                    ('def', node.start_point[0] + 1)
                )
                # Walk children but skip the name identifier — it's the
                # definition site, not a usage. Compare by byte range since
                # tree-sitter creates fresh wrapper objects on each access.
                name_start = name_node.start_byte
                name_end = name_node.end_byte
                for child in node.children:
                    if child.start_byte == name_start and child.end_byte == name_end:
                        continue
                    walk(child)
                return
        if node.type == 'identifier':
            referenced.add(node.text.decode())
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return defined, referenced, locations


def _js_dead_code(workdir: Path, path: str, min_confidence: int) -> str:
    """Tree-sitter scan of JS/TS files: defined-but-never-referenced symbols."""
    from .jslang import language_for

    defined: set[str] = set()
    referenced: set[str] = set()
    locations: dict[str, list[tuple[str, int]]] = {}

    files = list(_iter_source_files(workdir, JS_EXTENSIONS, path))
    for f in files:
        rel = str(f.relative_to(Path(workdir).resolve())).replace('\\', '/')
        try:
            defined_l, referenced_l, locs = _tree_sitter_definitions_and_refs(
                f.read_bytes(), language_for(f.suffix)
            )
        except Exception:
            continue
        defined |= defined_l
        referenced |= referenced_l
        for name, locs_list in locs.items():
            for kind, line in locs_list:
                locations.setdefault(name, []).append((f'{rel}:{line}', kind))

    dead = sorted(defined - referenced)
    results = []
    for name in dead:
        for path_line in locations.get(name, [])[:1]:
            results.append(f'dead: {path_line}: {name}')
    return '\n'.join(results)


def build_deadcode_toolset(workdir: Path) -> FunctionToolset:
    """The `find_dead_code` tool: defined-but-never-referenced symbols across
    Python (vulture, confidence-scored) and JS/TS (tree-sitter analysis)."""

    async def find_dead_code(path: str = '.', min_confidence: int = 60) -> str:
        """Report defined-but-never-referenced code. Python via vulture,
        JS/TS via tree-sitter. min_confidence: 0-100 (vulture threshold)."""
        sections = []

        py = await _vulture_python(Path(workdir), path, min_confidence)
        if py:
            sections.append(f'Python (vulture):\n{py}')

        js = _js_dead_code(Path(workdir), path, min_confidence)
        if js:
            sections.append(f'JavaScript/TypeScript (tree-sitter):\n{js}')

        if not sections:
            return '(no dead code found)'
        return '\n\n'.join(sections)

    return FunctionToolset([find_dead_code])


def sys_executable() -> str:
    import sys

    return sys.executable
