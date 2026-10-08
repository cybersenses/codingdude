"""Dead-code detection across languages: vulture (Python) + tree-sitter (all registered languages).

`find_dead_code` reports symbols that are defined but never referenced â€”
execution-level dead weight that test coverage cannot see. Confidence and
formatting are per-language; results are merged into one report.
"""

from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .tools import SKIP_DIRS

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
    from .tools import run_captured

    cap = await run_captured(
        [sys_executable(), '-m', 'vulture', *files, '--min-confidence', str(min_confidence)],
        cwd=workdir, timeout=120)
    return cap.stdout.strip() if cap else ''


def _ts_dead_code(workdir: Path, path: str) -> str:
    """Tree-sitter scan of every registered non-Python language:
    defined-but-never-referenced functions/classes."""
    from tree_sitter import Parser

    from codingdude.langs import spec_for

    defined: set[str] = set()
    referenced: set[str] = set()
    locations: dict[str, list[tuple]] = {}
    root = Path(workdir).resolve()

    for f in _all_files(root, path):
        suffix = f.suffix.lower()
        spec = spec_for(suffix)
        if spec is None or spec.navigation_only or suffix == '.py':
            continue
        if not (spec.function_nodes or spec.class_nodes):
            continue
        rel = str(f.relative_to(root)).replace('\\', '/')
        try:
            tree = Parser(spec.grammar).parse(f.read_bytes())
        except Exception:
            continue
        def_nodes = spec.function_nodes | spec.class_nodes
        # Definition-name identifiers are the definition site, not usages —
        # exclude them by byte range (fresh node objects defeat identity).
        name_ranges: set[tuple[int, int]] = set()
        from codingdude.tsedit import _name_node

        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in def_nodes:
                name_node = _name_node(node, spec)
                if name_node is not None and name_node.text is not None:
                    name_ranges.add((name_node.start_byte, name_node.end_byte))
                    name = name_node.text.decode('utf-8', 'replace')
                    defined.add(name)
                    locations.setdefault(name, []).append(
                        (f'{rel}:{node.start_point[0] + 1}', 'def')
                    )
            elif node.type == 'identifier':
                if (node.start_byte, node.end_byte) not in name_ranges and node.text is not None:
                    referenced.add(node.text.decode('utf-8', 'replace'))
            stack.extend(node.named_children)

    dead = sorted(defined - referenced)
    results = []
    for name in dead:
        for path_line in locations.get(name, [])[:1]:
            results.append(f'dead: {path_line[0]}: {name}')
    return '\n'.join(results)


def _all_files(root: Path, path: str = '.'):
    """All files under path, containment-checked, skip-name filtered."""
    from pydantic_ai import ModelRetry

    resolved_root = root.resolve()
    target = (resolved_root / path).resolve() if path else resolved_root
    try:
        target.relative_to(resolved_root)
    except ValueError:
        raise ModelRetry(
            f'Path {path!r} is outside the Workdir. '
            'Only paths inside the Workdir are accessible.'
        ) from None
    if target.is_file():
        yield target
        return
    for f in sorted(target.rglob('*')):
        if not f.is_file():
            continue
        if any(part in SKIP_NAMES for part in f.relative_to(resolved_root).parts):
            continue
        yield f


def build_deadcode_toolset(workdir: Path) -> FunctionToolset:
    """The `find_dead_code` tool: defined-but-never-referenced symbols across
    Python (vulture, confidence-scored) and every other registered language
    (generic tree-sitter scan)."""

    async def find_dead_code(path: str = '.', min_confidence: int = 60) -> str:
        """Report defined-but-never-referenced code. Python via vulture,
        all registered languages via tree-sitter. min_confidence: 0-100
        (vulture threshold)."""
        sections = []

        py = await _vulture_python(Path(workdir), path, min_confidence)
        if py:
            sections.append(f'Python (vulture):\n{py}')

        ts = _ts_dead_code(Path(workdir), path)
        if ts:
            sections.append(f'Other languages (tree-sitter):\n{ts}')

        if not sections:
            return '(no dead code found)'
        return '\n\n'.join(sections)

    return FunctionToolset([find_dead_code])


def sys_executable() -> str:
    """Indirection over sys.executable so tests can stub the interpreter path."""
    import sys

    return sys.executable
