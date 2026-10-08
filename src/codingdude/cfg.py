"""Static control-flow graph analysis: Python (precise ast path) and, since
the full-language rollout, a best-effort generic path for every tree-sitter
language in the registry.

Builds a CFG of basic blocks for each top-level function in a module,
marks blocks unreachable from the function entry (dead code), and can
render the result as a standalone Mermaid HTML page (Python only).

V1 scope (deliberate): per-function CFGs, structured control flow
(if/while/for/break/continue/return/raise). ``try`` bodies are treated
as linear flow — exception edges are not modeled. The generic tree-sitter
path maps the shared control-flow node types of the grammars
(``if_statement``, ``for_statement``, ``return_statement``, ...) with
per-family aliases (e.g. Ruby's bare ``if``/``until``/``next``); results
are best-effort, not compiler-grade.
"""

from __future__ import annotations

import ast
import html
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _Block:
    id: int
    lines: list[str] = field(default_factory=list)
    reachable: bool | None = None  # None until reachability pass


@dataclass
class _Fn:
    name: str
    blocks: list[_Block] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    entry: int = 0


class _Builder:
    def __init__(self, source_lines: list[str]) -> None:
        self._lines = source_lines
        self.fn = _Fn(name="")
        self._unreach: list[int] = []
        self._breaks: list[int] = []
        self._terminated: set[int] = set()  # blocks ending in return/raise/break/continue

    def _new_block(self) -> _Block:
        b = _Block(id=len(self.fn.blocks))
        self.fn.blocks.append(b)
        return b

    def _edge(self, src: int, dst: int, kind: str) -> None:
        self.fn.edges.append({"src": src, "dst": dst, "kind": kind})

    def _src(self, node: ast.stmt) -> list[str]:
        lo = max(node.lineno - 1, 0)
        hi = getattr(node, "end_lineno", node.lineno) or node.lineno
        return [ln for ln in self._lines[lo:hi]]

    def emit_body(
        self,
        stmts: list[ast.stmt],
        *,
        break_target: int | None,
        continue_target: int | None,
        entry_block: _Block | None = None,
    ) -> _Block:
        """Emit a statement list; returns the block where control exits
        or a block that has already terminated."""
        cur = entry_block if entry_block is not None else self._new_block()
        for idx, stmt in enumerate(stmts):
            last = idx == len(stmts) - 1
            if isinstance(stmt, (ast.Return, ast.Raise)):
                cur.lines.extend(self._src(stmt))
                self._terminated.add(cur.id)
                if not last:
                    cur = self._new_block()  # unreachable until proven otherwise
                    self._unreach.append(cur.id)
            elif isinstance(stmt, ast.If):
                cur.lines.append(self._src(stmt)[0])
                then_b = self.emit_body(
                    stmt.body,
                    break_target=break_target,
                    continue_target=continue_target,
                )
                else_b = (
                    self.emit_body(
                        stmt.orelse,
                        break_target=break_target,
                        continue_target=continue_target,
                        )
                    if stmt.orelse
                    else None
                )
                join = self._new_block()
                self._edge(cur.id, then_b.id, "true")
                self._edge(cur.id, (else_b or join).id, "false")
                self._close_branch(then_b, join)
                if else_b is not None:
                    self._close_branch(else_b, join)
                cur = join
            elif isinstance(stmt, (ast.While, ast.For)):
                head = self._new_block()
                head.lines.append(self._src(stmt)[0])
                self._edge(cur.id, head.id, "flow")
                body_entry = self._new_block()
                body = self.emit_body(
                    stmt.body,
                    break_target=None,  # patched after exit exists
                    continue_target=head.id,
                    entry_block=body_entry,
                )
                after = self._new_block()
                self._edge(head.id, body_entry.id, "true")
                self._edge(head.id, after.id, "false")
                self._close_branch(body, head, back=True)
                self._patch_breaks(after)
                cur = after
            elif isinstance(stmt, ast.Break):
                cur.lines.extend(self._src(stmt))
                self._breaks.append(cur.id)
                self._terminated.add(cur.id)
                if not last:
                    cur = self._new_block()
                    self._unreach.append(cur.id)
            elif isinstance(stmt, ast.Continue):
                cur.lines.extend(self._src(stmt))
                if continue_target is not None:
                    self._edge(cur.id, continue_target, "back")
                self._terminated.add(cur.id)
                if not last:
                    cur = self._new_block()
                    self._unreach.append(cur.id)
            else:
                cur.lines.extend(self._src(stmt))
        return cur

    # -- plumbing ---------------------------------------------------------

    def _close_branch(self, tail: _Block, join: _Block, back: bool = False) -> None:
        """Wire an exiting block of a branch to the join (or loop head).
        Terminated blocks (return/raise/break/continue) keep their own edges."""
        if tail.id in self._terminated:
            return
        has_out = any(e["src"] == tail.id for e in self.fn.edges)
        if not has_out and tail.lines:
            self._edge(tail.id, join.id, "back" if back else "flow")

    def _patch_breaks(self, after: _Block) -> None:
        for bid in self._breaks:
            self._edge(bid, after.id, "flow")
        self._breaks = []


def build_cfg(source: str, function: str | None = None) -> dict:
    """Build the CFG for ``function`` (first function if None).

    Returns ``{"function", "blocks", "edges"}`` where each block is
    ``{id, lines, reachable}`` and each edge is ``{src, dst, kind}``.
    Raises SyntaxError on unparseable source (fail fast).
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if function is None or node.name == function:
                fn_node = node
                break
    if fn_node is None:
        raise ValueError(f"function not found: {function!r}")

    b = _Builder(lines)
    b.fn.name = fn_node.name
    entry = b._new_block()
    b.emit_body(
        fn_node.body, break_target=None, continue_target=None,
        entry_block=entry,
    )
    return _finalize(b.fn, entry.id)


def _finalize(fn: _Fn, entry_id: int) -> dict:
    """Reachability pass + empty-block pruning + renumbering, shared by the
    Python (ast) and generic (tree-sitter) builders."""
    reach = _reachable(fn, entry_id)
    # Drop empty unreachable blocks: they are the implicit slot created after
    # return/raise/break/continue, not real dead code (real dead code has lines).
    kept = [x for x in fn.blocks if x.lines or x.id in reach]
    renumber = {x.id: i for i, x in enumerate(kept)}
    fn.blocks = kept
    for x in fn.blocks:
        x.id = renumber[x.id]
    # Edges anchored to pruned blocks (empty + unreachable joins) die with
    # them — otherwise renumbering raises KeyError downstream of the prune.
    fn.edges = [
        {"src": renumber[e["src"]], "dst": renumber[e["dst"]], "kind": e["kind"]}
        for e in fn.edges
        if e["src"] in renumber and e["dst"] in renumber
    ]
    for blk in fn.blocks:
        blk.reachable = blk.id in {renumber[i] for i in reach}
    return {
        "function": fn.name,
        "blocks": [
            {"id": x.id, "lines": x.lines, "reachable": bool(x.reachable)}
            for x in fn.blocks
        ],
        "edges": fn.edges,
    }


def _reachable(fn: _Fn, entry: int) -> set[int]:
    seen = {entry}
    frontier = [entry]
    while frontier:
        cur = frontier.pop()
        for e in fn.edges:
            if e["src"] == cur and e["dst"] not in seen:
                seen.add(e["dst"])
                frontier.append(e["dst"])
    return seen


_GREEN, _RED = "#baf7d0", "#f8d0d0"


def render_mermaid_html(source: str, title: str = "cfg.py") -> str:
    """Standalone HTML page: CFG per function, green = reachable, red = dead."""
    tree = ast.parse(source)
    sections: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        cfg = build_cfg(source, node.name)
        rows = [
            f'    B{b["id"]}["{html.escape(chr(10).join(b["lines"][:4]) or "(empty)")}"]'
            for b in cfg["blocks"]
        ]
        styles = [
            f"    style B{b['id']} fill:{_GREEN if b['reachable'] else _RED}"
            for b in cfg["blocks"]
        ]
        arrows = [
            f'    B{e["src"]} -->|{e["kind"]}| B{e["dst"]}' for e in cfg["edges"]
        ]
        dead = sum(1 for b in cfg["blocks"] if not b["reachable"])
        sections.append(
            f"<h2>{html.escape(node.name)}</h2>\n"
            f"<p>{dead} dead block(s)</p>\n"
            f'<div class="mermaid">\nflowchart TD\n'
            + "\n".join(rows + arrows + styles)
            + "\n</div>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)} — control-flow graph</title>"
        "<script src='https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js'>"
        "</script><script>mermaid.initialize({startOnLoad:true});</script>"
        "<style>body{font-family:system-ui;margin:2rem;background:#111;color:#eee}"
        ".mermaid{background:#fff;padding:1rem;border-radius:8px}</style>"
        f"</head><body><h1>{html.escape(title)}</h1>\n"
        + "\n".join(sections)
        + "\n</body></html>"
    )


# --- generic tree-sitter path (all registered languages) ---------------------

# node type -> control-flow role. Shared names first, then per-family aliases.
_TS_ROLES: dict[str, str] = {
    # branching
    'if_statement': 'if', 'if_expression': 'if', 'if': 'if',
    'unless_statement': 'if', 'elif_clause': 'if', 'elseif_clause': 'if',
    'else_clause': 'else_block', 'else': 'else_block',
    # loops
    'for_statement': 'loop', 'for_in_statement': 'loop',
    'foreach_statement': 'loop', 'foreach_clause': 'loop',
    'while_statement': 'loop', 'while': 'loop', 'until': 'loop',
    'do_statement': 'loop', 'repeat_statement': 'loop',
    'for_range_clause': 'loop',
    # terminators
    'return_statement': 'terminate', 'return': 'terminate',
    'throw_statement': 'terminate', 'raise_statement': 'terminate',
    'raise': 'terminate', 'exit_statement': 'terminate',
    # loop exits / continuations
    'break_statement': 'break', 'break': 'break',
    'continue_statement': 'continue', 'next': 'continue',
    'goto_statement': 'terminate',
}

# statement-list container node types (bodies, blocks, programs).
_TS_BLOCK_TYPES = frozenset({
    'block', 'statement_block', 'compound_statement', 'translation_unit',
    'source_file', 'program', 'then', 'consequence', 'alternative',
    'else', 'body', 'else_body',
})


def _ts_child_fields(node) -> list:
    """Named children that are statements (skip identifier/comment noise)."""
    return [
        c for c in node.named_children
        if c.type not in ('identifier', 'comment', 'line_comment')
    ]


def _ts_stmts(node) -> list:
    """The statement list of a block-ish node."""
    if node.type in _TS_BLOCK_TYPES:
        return _ts_child_fields(node)
    return [node]


def _ts_fn_body(fn_node):
    """A function's statement container: 'body' field where the grammar has
    one, else the first block-ish descendant (Odin nests the block inside a
    `procedure` wrapper node)."""
    body = fn_node.child_by_field_name('body')
    if body is not None:
        return body
    stack = list(fn_node.named_children)
    while stack:
        n = stack.pop(0)
        if n.type in _TS_BLOCK_TYPES:
            return n
        stack.extend(n.named_children)
    return fn_node


class _TSBuilder:
    """Best-effort CFG over tree-sitter nodes using shared control-flow
    node-type names. Mirrors the Python _Builder's block/edge model."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.fn = _Fn(name="")
        self._breaks: list[int] = []
        self._terminated: set[int] = set()
        self._entry_hint: int | None = None  # entry block of last cur=None emit

    def _new_block(self) -> _Block:
        b = _Block(id=len(self.fn.blocks))
        self.fn.blocks.append(b)
        return b

    def _edge(self, src: int, dst: int, kind: str) -> None:
        self.fn.edges.append({"src": src, "dst": dst, "kind": kind})

    def _src(self, node, max_lines: int | None = None) -> list[str]:
        out = self._lines[node.start_point[0]:node.end_point[0] + 1]
        return out if max_lines is None else out[:max_lines]

    def _field(self, node, *names: str):
        for n in names:
            child = node.child_by_field_name(n)
            if child is not None:
                return child
        return None

    def _branch_body(self, node, *field_names: str):
        """Body of a branch/loop: prefer the named field, else first block-ish
        named child (Ruby attaches bodies without a field)."""
        got = self._field(node, *field_names)
        if got is not None:
            return got
        for c in node.named_children:
            if c.type in _TS_BLOCK_TYPES:
                return c
        return None

    def emit(self, stmts: list, *, break_target: int | None,
             continue_target: int | None, cur: _Block | None = None) -> _Block:
        outer_hint = self._entry_hint
        own_entry: int | None = None
        if cur is None:
            cur = self._new_block()
            own_entry = cur.id
        for idx, stmt in enumerate(stmts):
            last = idx == len(stmts) - 1
            role = _TS_ROLES.get(stmt.type)
            if role == 'terminate':
                cur.lines.extend(self._src(stmt))
                self._terminated.add(cur.id)
                if not last:
                    cur = self._new_block()
            elif role == 'break':
                cur.lines.extend(self._src(stmt))
                if break_target is not None:
                    self._breaks.append(cur.id)
                self._terminated.add(cur.id)
                if not last:
                    cur = self._new_block()
            elif role == 'continue':
                cur.lines.extend(self._src(stmt))
                if continue_target is not None:
                    self._edge(cur.id, continue_target, "back")
                self._terminated.add(cur.id)
                if not last:
                    cur = self._new_block()
            elif role == 'if':
                cur.lines.append(self._src(stmt, max_lines=1)[0])
                then_node = self._branch_body(stmt, 'then', 'consequence', 'body')
                join = self._new_block()
                if then_node is not None:
                    then_b = self.emit(
                        _ts_stmts(then_node), break_target=break_target,
                        continue_target=continue_target,
                    )
                    # then_b is the body's EXIT; a body that allocates its
                    # own blocks (loop/if) is entered at the hinted entry.
                    entry = self._entry_hint
                    self._edge(cur.id, entry if entry is not None else then_b.id, "true")
                    self._close_branch(then_b, join)
                else:
                    self._edge(cur.id, join.id, "true")
                # else/elsif chain: named field first, then sibling clause
                else_node = self._field(stmt, 'alternative', 'else')
                if else_node is not None:
                    else_node = _unwrap_else(else_node)
                else:
                    for c in stmt.named_children:
                        if _TS_ROLES.get(c.type) in ('if', 'else_block'):
                            else_node = _unwrap_else(c)
                            break
                if else_node is not None:
                    else_b = self.emit(
                        _ts_stmts(else_node), break_target=break_target,
                        continue_target=continue_target,
                    )
                    entry = self._entry_hint
                    self._edge(cur.id, entry if entry is not None else else_b.id, "false")
                    self._close_branch(else_b, join)
                else:
                    self._edge(cur.id, join.id, "false")
                cur = join
            elif role == 'loop':
                # A branch body's fresh entry block (cur empty, nothing
                # points at it yet) can serve as the loop head directly —
                # allocating a new one leaves both unreachable from entry.
                if not cur.lines and not any(
                    e["dst"] == cur.id for e in self.fn.edges
                ):
                    head = cur
                    head.lines.append(self._src(stmt, max_lines=1)[0])
                else:
                    head = self._new_block()
                    head.lines.append(self._src(stmt, max_lines=1)[0])
                    self._edge(cur.id, head.id, "flow")
                body_node = self._branch_body(stmt, 'body')
                after = self._new_block()
                if body_node is not None:
                    body_entry = self._new_block()
                    body = self.emit(
                        _ts_stmts(body_node), break_target=None,
                        continue_target=head.id, cur=body_entry,
                    )
                    self._edge(head.id, body_entry.id, "true")
                    self._close_branch(body, head, back=True)
                else:
                    self._edge(head.id, after.id, "true")
                self._edge(head.id, after.id, "false")
                self._patch_breaks(after)
                cur = after
            else:
                cur.lines.extend(self._src(stmt, max_lines=1))
                for child in _ts_child_fields(stmt):
                    if _TS_ROLES.get(child.type) is not None or child.type in _TS_BLOCK_TYPES:
                        cur = self.emit(
                            _ts_stmts(child), break_target=break_target,
                            continue_target=continue_target, cur=cur,
                        )
        # Restore the hint so an enclosing branch reads ITS entry, not one
        # allocated by a nested cur=None emit.
        self._entry_hint = own_entry if own_entry is not None else outer_hint
        return cur

    def _close_branch(self, tail: _Block, join: _Block, back: bool = False) -> None:
        if tail.id in self._terminated:
            return
        if not any(e["src"] == tail.id for e in self.fn.edges) and tail.lines:
            self._edge(tail.id, join.id, "back" if back else "flow")

    def _patch_breaks(self, after: _Block) -> None:
        for bid in self._breaks:
            self._edge(bid, after.id, "flow")
        self._breaks = []


_DEFAULT_FN_NODES = frozenset({
    'method', 'method_definition', 'function_definition',
    'function_declaration', 'function_item', 'function',
})


def _unwrap_else(node):
    """An else branch: if the node is a clause wrapper (C's else_clause),
    step down to its block-ish child."""
    if node.type == 'else_clause':
        for c in node.named_children:
            if c.type in _TS_BLOCK_TYPES or c.type == 'else':
                return c
    return node


def ts_fn_name(node, spec) -> str | None:
    """Function name: 'name' field (most grammars), or the C/C++ declarator
    chain (function_definition > function_declarator > identifier)."""
    name_node = node.child_by_field_name(spec.name_field)
    if name_node is None:
        declarator = node.child_by_field_name('declarator')
        if declarator is not None:
            name_node = declarator.child_by_field_name('declarator')
    if name_node is None or not name_node.text:
        # Odin-style `name :: proc...`: first `identifier` named child.
        from codingdude.tsedit import _name_node

        name_node = _name_node(node, spec)
    if name_node is None or not name_node.text:
        return None
    return name_node.text.decode('utf-8', 'replace')


def ts_build_cfg(source: bytes, spec, function: str | None = None) -> dict:
    """Best-effort CFG for a non-Python file via its LanguageSpec.

    Finds the target function with the spec's function_nodes/name_field,
    then maps shared tree-sitter control-flow node types. Same result shape
    as build_cfg. Raises ValueError when the function isn't found.
    """
    from tree_sitter import Parser

    tree = Parser(spec.grammar).parse(source)
    lines = source.decode('utf-8', errors='replace').splitlines()
    fn_node = None
    fn_name = ''
    stack = [tree.root_node]
    while stack:
        n = stack.pop()
        if n.type in (spec.function_nodes or _DEFAULT_FN_NODES):
            name = ts_fn_name(n, spec)
            if name is not None and (function is None or name == function):
                fn_node = n
                fn_name = name
                break
        stack.extend(n.named_children)
    if fn_node is None:
        raise ValueError(f"function not found: {function!r}")

    b = _TSBuilder(lines)
    b.fn.name = fn_name
    entry = b._new_block()
    body = _ts_fn_body(fn_node)
    b.emit(_ts_stmts(body), break_target=None, continue_target=None, cur=entry)
    return _finalize(b.fn, entry.id)


def build_cfg_toolset(workdir: Path):
    """The `analyze_control_flow` tool: basic-block CFG + dead-code verdict
    for one function in one workdir file (#153, R46)."""
    from pydantic_ai import ModelRetry
    from pydantic_ai.toolsets import FunctionToolset

    from .tools import resolve_workdir_path

    root = Path(workdir)

    def _summarize(cfg: dict) -> str:
        dead = [b for b in cfg["blocks"] if not b["reachable"]]
        lines = [f"function {cfg['function']}: {len(cfg['blocks'])} block(s)."]
        if not dead:
            lines.append("No unreachable blocks — control flow is fully reachable.")
        else:
            lines.append(f"{len(dead)} unreachable block(s):")
            for b in dead:
                lines.append(f"  block {b['id']}: {' | '.join(b['lines'][:3])!r}")
        return "\n".join(lines)

    async def analyze_control_flow(path: str, function: str | None = None) -> str:
        """Static control-flow analysis of one function in a project file.

        Builds the basic-block graph and reports unreachable (dead) blocks
        with their source lines. `function` optional — first function in the
        file when omitted. Read-only.
        """
        target, error = resolve_workdir_path(root, path)
        if error or target is None:
            raise ModelRetry(f"cannot read {path!r}: {error or 'bad path'}")
        try:
            source = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ModelRetry(f"cannot read {path!r}: {exc}") from exc
        if target.suffix.lower() == '.py':
            try:
                return _summarize(build_cfg(source, function))
            except (SyntaxError, ValueError) as exc:
                raise ModelRetry(f"cannot analyze {path!r}: {exc}") from exc
        # Best-effort generic path for every registered non-Python language.
        from codingdude.langs import spec_for

        spec = spec_for(target.suffix.lower())
        if spec is None or spec.navigation_only:
            raise ModelRetry(
                f"cannot analyze {path!r}: no language support for "
                f"{target.suffix or 'this file type'}"
            )
        try:
            cfg = ts_build_cfg(source.encode('utf-8'), spec, function)
        except ValueError as exc:
            raise ModelRetry(f"cannot analyze {path!r}: {exc}") from exc
        return _summarize(cfg) + (
            '\n(best-effort generic CFG — not compiler-grade for this language)'
        )

    return FunctionToolset([analyze_control_flow])
