"""User-facing call graph of a source file (R42 #94).

Pure seam: parses one file (Python via ast, JS/TS via tree-sitter) and
returns {"nodes": [...], "edges": [[caller, callee], ...]} where nodes carry
id/name/line and an `orphan` flag (no incoming AND no outgoing edges). The
frontend renders this as a Mermaid graph for humans reviewing generated code.
"""

import ast
import re as _re
from pathlib import Path

from codingdude.pyparse import parse_python

from .tools import SKIP_DIRS

PY = '.py'
JS_EXTENSIONS = {'.js', '.jsx', '.mjs', '.ts', '.tsx'}


def build_call_graph(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'no such file: {path}')
    if path.suffix == PY:
        return _python_graph(path)
    if path.suffix in JS_EXTENSIONS:
        return _js_graph(path)
    raise ValueError(f'unsupported file type: {path.suffix}')


def _finish(nodes: list[dict], edges: list[list[str]]) -> dict:
    callers: set[str] = set()
    for _a, b in edges:
        callers.add(b)
    # orphan = dead code: no caller anywhere in the file (in-degree 0).
    for n in nodes:
        n['orphan'] = n['id'] not in callers
    return {'nodes': nodes, 'edges': edges}


def _python_graph(path: Path) -> dict:
    tree = parse_python(path.read_text(encoding='utf-8', errors='strict'))
    nodes: list[dict] = []
    edges: list[list[str]] = []
    defined: dict[str, str] = {}  # bare name -> qualified id
    fn_nodes: list[tuple[ast.AST, str]] = []  # (node, qualified id), one pass

    def qual(prefix: str, name: str) -> str:
        return f'{prefix}.{name}' if prefix else name

    def collect(node, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qid = qual(prefix, child.name)
                defined.setdefault(child.name, qid)
                nodes.append({'id': qid, 'name': child.name, 'line': child.lineno})
                fn_nodes.append((child, qid))
                collect(child, qid)
            elif isinstance(child, ast.ClassDef):
                qid = qual(prefix, child.name)
                defined.setdefault(child.name, qid)
                collect(child, qid)

    # Single pass: collect definitions (so forward/self references resolve)
    # and remember each function node with its qualified id for edge resolution.
    collect(tree, '')

    def calls_of(fn, fn_id: str) -> None:
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                name = None
                if isinstance(sub.func, ast.Name):
                    name = sub.func.id
                elif isinstance(sub.func, ast.Attribute):
                    name = sub.func.attr
                if name and name in defined and defined[name] != fn_id:
                    edges.append([fn_id, defined[name]])

    for fn, qid in fn_nodes:
        calls_of(fn, qid)
    return _finish(nodes, edges)


def _js_graph(path: Path) -> dict:
    from tree_sitter import Parser

    from .jslang import language_for

    parser = Parser(language_for(path.suffix))
    tree = parser.parse(path.read_bytes())
    nodes: list[dict] = []
    edges: list[list[str]] = []
    defined: set[str] = set()

    # A callable is a declared function/method/class OR a variable holding an
    # arrow/function expression (the dominant style in generated React/TS).
    DECL_TYPES = ('function_declaration', 'class_declaration',
                  'method_definition')
    ARROW_TYPES = ('arrow_function', 'function_expression')

    def name_of(node):
        n = node.child_by_field_name('name')
        return n.text.decode() if n else None

    def callable_name(node) -> str | None:
        if node.type in DECL_TYPES:
            return name_of(node)
        if node.type == 'variable_declarator':
            value = node.child_by_field_name('value')
            if value is not None and value.type in ARROW_TYPES:
                return name_of(node)
        return None

    def collect(node) -> None:
        name = callable_name(node)
        if name:
            defined.add(name)
            nodes.append({'id': name, 'name': name,
                          'line': node.start_point[0] + 1})
        for child in node.children:
            collect(child)

    collect(tree.root_node)

    def walk_calls(node, current: str | None) -> None:
        inner = callable_name(node) or current
        if node.type == 'call_expression':
            fn = node.child_by_field_name('function')
            if fn is not None and fn.type == 'identifier':
                name = fn.text.decode()
                if name in defined and name != inner:
                    edges.append([inner or name, name])
        for child in node.children:
            walk_calls(child, inner)

    walk_calls(tree.root_node, None)
    return _finish(nodes, edges)


# ---- #101 (R43): module-level architecture map ------------------------------
# C4-lite: every source file is a node; a cross-file import is an edge. Humans
# read the shape of a generated project without opening every file.

_SOURCE_EXTENSIONS = ('.py', '.js', '.jsx', '.mjs', '.ts', '.tsx')
_JS_IMPORT_RE = _re.compile(
    r"""(?:from\s+|import\s*\(\s*|require\s*\(\s*)['"]([^'"]+)['"]""")
_JS_EXTS = ('.js', '.jsx', '.mjs', '.ts', '.tsx')


def _iter_source_files(root: Path, max_files: int):
    count = 0
    for f in sorted(root.rglob('*')):
        if not f.is_file() or f.suffix not in _SOURCE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in f.relative_to(root).parts):
            continue
        yield f
        count += 1
        if count >= max_files:
            return


def _module_names(files: list[Path], root: Path) -> dict[str, Path]:
    """Dotted module name -> file, for import resolution (e.g. pkg.core)."""
    names: dict[str, Path] = {}
    for f in files:
        rel = f.relative_to(root)
        parts = list(rel.with_suffix('').parts)
        if parts[-1] == '__init__':
            parts = parts[:-1]
        names['.'.join(parts)] = f
    return names


def build_module_graph(workdir: Path, max_files: int = 200) -> dict:
    """Architecture map of a project: files as nodes, imports as edges (#101).

    Mirrors build_call_graph's shape: {"nodes": [...], "edges": [[a, b]]},
    with orphan flagging (in-degree 0) via _finish.
    """
    root = Path(workdir)
    files = list(_iter_source_files(root, max_files))
    by_module = _module_names(files, root)
    rel_of = {f: f.relative_to(root).as_posix() for f in files}

    nodes = []
    for f in files:
        try:
            lines = f.read_text(encoding='utf-8', errors='replace').count('\n') + 1
        except OSError:
            lines = 0
        nodes.append({'id': rel_of[f], 'name': rel_of[f], 'line': lines})

    edges: list[list[str]] = []
    for f in files:
        src = rel_of[f]
        targets = (
            _python_import_targets(f, root, by_module)
            if f.suffix == '.py'
            else _js_import_targets(f, root, files)
        )
        for dst_rel in sorted(targets):
            if dst_rel != src:
                edges.append([src, dst_rel])
    return _finish(nodes, edges)


def _python_import_targets(f: Path, root: Path,
                           by_module: dict[str, Path]) -> set[str]:
    try:
        tree = parse_python(f.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError:
        return set()
    rel = f.relative_to(root)
    targets: set[str] = set()

    def resolve(dotted: str) -> str | None:
        """Longest-prefix match of a dotted name against project modules."""
        parts = dotted.split('.')
        while parts:
            candidate = by_module.get('.'.join(parts))
            if candidate is not None:
                return candidate.relative_to(root).as_posix()
            parts.pop()
        return None

    for node in ast.walk(tree):
        level = getattr(node, 'level', 0)
        module = getattr(node, 'module', None)
        if isinstance(node, ast.ImportFrom):
            if level:
                base = list(rel.parent.parts[: max(0, len(rel.parent.parts) - (level - 1))])
                mod_parts = module.split('.') if module else []
                dotted = '.'.join(base + mod_parts)
                if not node.names:  # from . import sibling
                    for alias in node.names:
                        t = resolve(f'{dotted}.{alias.name}')
                        if t:
                            targets.add(t)
                    continue
                t = resolve(dotted)
            else:
                t = resolve(module or '')
            if t:
                targets.add(t)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                t = resolve(alias.name)
                if t:
                    targets.add(t)
    return targets


def _js_import_targets(f: Path, root: Path, files: list[Path]) -> set[str]:
    try:
        text = f.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return set()
    file_set = {g.relative_to(root).as_posix() for g in files}
    targets: set[str] = set()
    for spec in _JS_IMPORT_RE.findall(text):
        if not spec.startswith('.'):
            continue  # bare package import (npm) — not a project file
        base = (f.parent / spec).resolve()
        candidates = [base.with_suffix(e) for e in _JS_EXTS]
        candidates += [base / f'index{e}' for e in _JS_EXTS]
        for cand in candidates:
            rel = cand.relative_to(root).as_posix()
            if cand.is_file() and rel in file_set:
                targets.add(rel)
                break
    return targets
