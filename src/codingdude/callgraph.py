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
    callers: set[str] = set()
    for _a, b in edges:
        callers.add(b)
    # orphan = dead code: no caller anywhere in the file (in-degree 0).
    for n in nodes:
        n['orphan'] = n['id'] not in callers
    return {'nodes': nodes, 'edges': edges}


def _python_graph(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding='utf-8', errors='strict'))
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
