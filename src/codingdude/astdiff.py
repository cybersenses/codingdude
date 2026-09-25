"""AST-aware diff summary (R22 #41).

Parses before/after source with stdlib ast and reports semantic changes —
symbols added/removed/changed and signature changes — so post-edit feedback
is verifiable without re-reading the file.
"""

import ast

from codingdude.pyparse import parse_python


def _signature(node) -> str:
    """Rendered signature like 'def f(a, b=1)' / 'class C'."""
    if isinstance(node, ast.ClassDef):
        return f'class {node.name}'
    args = node.args
    defaults: list = [None] * (
        len(args.posonlyargs + args.args) - len(args.defaults)
    ) + list(args.defaults)
    kwdefaults = dict(
        zip((a.arg for a in args.kwonlyargs), args.kw_defaults, strict=False)
    )

    def fmt(a, default) -> str:
        text = ast.unparse(a)
        return f'{text}={ast.unparse(default)}' if default is not None else text

    parts = [
        fmt(a, d)
        for a, d in zip(args.posonlyargs + args.args, defaults, strict=True)
    ]
    if args.vararg:
        parts.append(f'*{args.vararg.arg}')
    elif args.kwonlyargs:
        parts.append('*')
    parts += [fmt(a, kwdefaults.get(a.arg)) for a in args.kwonlyargs]
    if args.kwarg:
        parts.append(f'**{args.kwarg.arg}')
    kind = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
    return f'{kind} {node.name}({", ".join(parts)})'


def _collect(tree: ast.AST) -> dict[str, tuple[str, str]]:
    """Qualified symbol name -> (signature, source hash) for defs/classes."""
    found: dict[str, tuple[str, str]] = {}

    def walk(node, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                qual = f'{prefix}{child.name}'
                body = ast.dump(
                    ast.Module(body=child.body, type_ignores=[])
                )
                found[qual] = (_signature(child), body)
                walk(child, f'{qual}.')

    walk(tree, '')
    return found


def describe_ast_change(before: str, after: str) -> str:
    """One line per semantic change, or '' when nothing structural changed."""
    try:
        old = _collect(parse_python(before))
        new = _collect(parse_python(after))
    except SyntaxError:
        return '(file no longer parses as Python)'

    changes: list[str] = []
    for name in sorted(set(old) - set(new)):
        changes.append(f'removed {name}')
    for name in sorted(set(new) - set(old)):
        changes.append(f'added {name} ({new[name][0]})')
    for name in sorted(set(old) & set(new)):
        if old[name] != new[name]:
            if old[name][0] != new[name][0]:
                changes.append(
                    f'changed {name}: {old[name][0]} -> {new[name][0]}'
                )
            else:
                changes.append(f'changed body of {name}')
    return '; '.join(changes)
