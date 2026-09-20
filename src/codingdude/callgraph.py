"""User-facing call graph of a source file (R42 #94).

Pure seam: parses one file (Python via ast, JS/TS via tree-sitter) and
returns {"nodes": [...], "edges": [[caller, callee], ...]} where nodes carry
id/name/line and an `orphan` flag (no incoming AND no outgoing edges). The
frontend renders this as a Mermaid graph for humans reviewing generated code.
"""

import ast
from pathlib import Path

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
    degree: dict[str, int] = {}
    for a, b in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    for n in nodes:
        n['orphan'] = degree.get(n['id'], 0) == 0
    return {'nodes': nodes, 'edges': edges}


def _python_graph(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding='utf-8', errors='strict'))
    nodes: list[dict] = []
    edges: list[list[str]] = []
    defined: dict[str, str] = {}  # bare name -> qualified id

    def qual(prefix: str, name: str) -> str:
        return f'{prefix}.{name}' if prefix else name

    def collect(node, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qid = qual(prefix, child.name)
                defined.setdefault(child.name, qid)
                nodes.append({'id': qid, 'name': child.name, 'line': child.lineno})
                collect(child, qid)
            elif isinstance(child, ast.ClassDef):
                qid = qual(prefix, child.name)
                defined.setdefault(child.name, qid)
                collect(child, qid)

    # Pass 1: collect all definitions so forward/self references resolve.
    collect(tree, '')

    # Pass 2: resolve call edges.
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

    # Resolve edges using the qualified ids from nodes directly.
    for n in nodes:
        fn = _find_fn(tree, n['id'])
        if fn is not None:
            calls_of(fn, n['id'])
    return _finish(nodes, edges)


def _find_fn(tree: ast.AST, qid: str):
    parts = qid.split('.')

    def descend(node, i: int):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)) and child.name == parts[i]:
                if i == len(parts) - 1:
                    return child
                return descend(child, i + 1)
        return None

    return descend(tree, 0)


def _js_graph(path: Path) -> dict:
    from tree_sitter import Parser

    from .jslang import language_for

    parser = Parser(language_for(path.suffix))
    tree = parser.parse(path.read_bytes())
    nodes: list[dict] = []
    edges: list[list[str]] = []
    defined: set[str] = set()

    def name_of(node):
        n = node.child_by_field_name('name')
        return n.text.decode() if n else None

    def collect(node) -> None:
        if node.type in ('function_declaration', 'class_declaration',
                         'method_definition'):
            name = name_of(node)
            if name:
                defined.add(name)
                nodes.append({'id': name, 'name': name, 'line': node.start_point[0] + 1})
        for child in node.children:
            collect(child)

    collect(tree.root_node)

    def walk_calls(node, current: str | None) -> None:
        if node.type in ('function_declaration', 'method_definition',
                         'arrow_function', 'function_expression'):
            name = name_of(node) if node.type != 'arrow_function' else current
            current = name or current
        if node.type == 'call_expression':
            fn = node.child_by_field_name('function')
            if fn is not None and fn.type == 'identifier':
                name = fn.text.decode()
                if name in defined and name != current:
                    edges.append([current or name, name])
        for child in node.children:
            walk_calls(child, current)

    walk_calls(tree.root_node, None)
    return _finish(nodes, edges)
