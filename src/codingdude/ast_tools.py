"""AST tools: find_definition / find_references for Python via tree-sitter."""

from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from .tools import SKIP_DIRS

MAX_RESULTS = 50


def _resolve_contained(workdir: Path, path: str) -> Path:
    """Containment-checked resolution - symlink-safe, Workdir-confined."""
    root_r = workdir.resolve()
    target = (root_r / path).resolve()
    try:
        target.relative_to(root_r)
    except ValueError:
        raise ModelRetry(
            f'Path {path!r} is outside the Workdir. '
            'Only paths inside the Workdir are accessible.'
        ) from None
    return target


def _python_files(workdir: Path, path: str = "."):
    root = workdir.resolve()
    target = _resolve_contained(workdir, path)
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
    """AST-accurate navigation: Python via its own path, all other registered
    languages via the langs registry; graceful degradation elsewhere."""

    _IDENT_TYPES = frozenset(
        {
            'identifier',
            'property_identifier',
            'type_identifier',
            'field_identifier',
            'class_name',
            'id_name',
        }
    )

    def _check_python(path: str) -> None:
        target = (workdir / path).resolve()
        if target.is_file() and target.suffix != '.py':
            raise ModelRetry(
                f'{path} is not a Python file. AST tools support Python and '
                'registered languages; use grep for other file types.'
            )

    def _nav_spec_for(target: Path):
        """Registry spec for navigation-only suffixes, else None."""
        from codingdude.langs import spec_for

        suffix = target.suffix.lower() if target.is_file() else ''
        spec = spec_for(suffix) if suffix else None
        return spec if spec is not None and spec.navigation_only else None

    def _nav_files(path: str = '.'):
        """All navigation-only files under path, sorted."""
        from codingdude.langs import NAV_SUFFIXES

        root = workdir.resolve()
        target = _resolve_contained(workdir, path)
        if target.is_file():
            yield target
            return
        for f in sorted(target.rglob('*')):
            if f.suffix.lower() not in NAV_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in f.relative_to(root).parts):
                continue
            yield f

    def _registered_files(path: str = '.'):
        """Files with registered (non-Python, non-navigation) suffixes."""
        from codingdude.langs import spec_for

        root = workdir.resolve()
        target = _resolve_contained(workdir, path)
        if target.is_file():
            yield target
            return
        for f in sorted(target.rglob('*')):
            if not f.is_file():
                continue
            spec = spec_for(f.suffix.lower())
            if (
                spec is None
                or spec.navigation_only
                or f.suffix.lower() == '.py'
            ):
                continue
            if any(part in SKIP_DIRS for part in f.relative_to(root).parts):
                continue
            yield f

    def _parse_generic(source: bytes, spec):
        from tree_sitter import Parser

        return Parser(spec.grammar).parse(source)

    def find_definition(symbol: str, path: str = '.') -> str:
        """Locate where a function/class is defined (file:line)."""
        from codingdude.langs import spec_for
        from codingdude.tsedit import _collect, nav_symbols

        target = _resolve_contained(workdir, path)
        nav_spec = _nav_spec_for(target)
        if nav_spec is not None:
            rel = target.relative_to(workdir)
            for name, line in nav_symbols(target.read_bytes(), nav_spec):
                if name == symbol or name.lstrip('.#') == symbol:
                    return f'definition: {rel}:{line}: {symbol}'
            return f'(no definition of {symbol!r} found)'

        results: list[str] = []
        for f in _registered_files(path):
            spec = spec_for(f.suffix.lower())
            if spec is None or spec.navigation_only:
                continue
            source = f.read_bytes()
            rel = f.relative_to(workdir)
            for name, info in _collect(source, spec).items():
                if name == symbol or name.rsplit('.', 1)[-1] == symbol:
                    line = source[: info.start_byte].count(b'\n') + 1
                    results.append(f'definition: {rel}:{line}: {name}')
                    if len(results) >= MAX_RESULTS:
                        break
            if len(results) >= MAX_RESULTS:
                break
        if results:
            return '\n'.join(results)

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
        """Find usages of a symbol (imports, calls, names) across files."""
        from codingdude.langs import spec_for
        from codingdude.tsedit import _is_symbol, _node_name

        results: list[str] = []
        for f in _registered_files(path):
            spec = spec_for(f.suffix.lower())
            if spec is None or spec.navigation_only:
                continue
            source = f.read_bytes()
            rel = f.relative_to(workdir)
            tree = _parse_generic(source, spec)
            for node in _walk(tree.root_node):
                if node.type not in _IDENT_TYPES:
                    continue
                if node.text != symbol.encode():
                    continue
                parent = node.parent
                if (
                    parent is not None
                    and _is_symbol(parent, spec)
                    and _node_name(parent, spec)
                    == node.text.decode('utf-8', 'replace')
                ):
                    continue  # the definition itself, not a reference
                line = node.start_point[0] + 1
                results.append(f'reference: {rel}:{line}')
                if len(results) >= MAX_RESULTS:
                    break
            if len(results) >= MAX_RESULTS:
                break

        from codingdude.tsedit import nav_symbols

        for f in _nav_files(path):
            spec = spec_for(f.suffix.lower())
            if spec is None or not spec.navigation_only:
                continue
            for name, line in nav_symbols(f.read_bytes(), spec):
                if name == symbol or name.lstrip('.#') == symbol:
                    results.append(f'reference: {f.relative_to(workdir)}:{line}')
                    if len(results) >= MAX_RESULTS:
                        break
            if len(results) >= MAX_RESULTS:
                break

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

    def list_languages() -> str:
        """List supported languages: full AST tool support vs navigation-only,
        plus the tree-sitter-language-pack coverage."""
        from codingdude.langs import (
            PINNED_FULL_SUFFIXES,
            PINNED_NAV_SUFFIXES,
            supported_languages,
        )

        info = supported_languages()
        pack = sorted(str(x) for x in info['pack_languages'])  # type: ignore[union-attr,attr-defined]
        total = int(info['pack_manifest_total'])  # type: ignore[arg-type,call-overload]
        lines = [
            'Full support (find_definition/find_references/edits): '
            + ', '.join(sorted(PINNED_FULL_SUFFIXES)),
            'Navigation-only (find_definition on symbols/keys): '
            + ', '.join(sorted(PINNED_NAV_SUFFIXES)),
            f'tree-sitter-language-pack: {len(pack)} locally available of '
            f'{total} in the manifest '
            + ', '.join(pack)
            + ' — parse/navigation only, tools degrade gracefully.',
        ]
        return '\n'.join(lines)

    return FunctionToolset([find_definition, find_references, list_languages])
