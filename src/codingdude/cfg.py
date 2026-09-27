"""Static control-flow graph analysis for Python source.

Builds a CFG of basic blocks for each top-level function in a module,
marks blocks unreachable from the function entry (dead code), and can
render the result as a standalone Mermaid HTML page.

V1 scope (deliberate): per-function CFGs, structured control flow
(if/while/for/break/continue/return/raise). ``try`` bodies are treated
as linear flow — exception edges are not modeled.
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
        or a block that has already terminated.
        already terminated."""
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
    reach = _reachable(b.fn, entry.id)
    # Drop empty unreachable blocks: they are the implicit slot created after
    # return/raise/break/continue, not real dead code (real dead code has lines).
    kept = [x for x in b.fn.blocks if x.lines or x.id in reach]
    renumber = {x.id: i for i, x in enumerate(kept)}
    b.fn.blocks = [x for x in kept]
    for x in b.fn.blocks:
        x.id = renumber[x.id]
    b.fn.edges = [
        {"src": renumber[e["src"]], "dst": renumber[e["dst"]], "kind": e["kind"]}
        for e in b.fn.edges
    ]
    for blk in b.fn.blocks:
        blk.reachable = blk.id in {renumber[i] for i in reach}
    return {
        "function": b.fn.name,
        "blocks": [
            {"id": x.id, "lines": x.lines, "reachable": bool(x.reachable)}
            for x in b.fn.blocks
        ],
        "edges": b.fn.edges,
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
        try:
            return _summarize(build_cfg(source, function))
        except (SyntaxError, ValueError) as exc:
            raise ModelRetry(f"cannot analyze {path!r}: {exc}") from exc

    return FunctionToolset([analyze_control_flow])
