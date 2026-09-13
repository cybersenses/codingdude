"""R8: architecture linter — seam leaks and duplicated behavior, soft-block.

Findings must be fixed or explicitly waived; a waiver is recorded as a design
decision (workdir-scoped) so overturning architecture is always visible.
"""

import ast
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import FunctionToolset

from .db import Database
from .roadmap import RoadmapStore

WAIVER_PREFIX = 'ARCH-WAIVER'


@dataclass
class _Fn:
    file: str
    line: int
    name: str
    body_key: str


@dataclass
class ArchLint:
    """Deterministic AST linter over a workdir's Python sources."""

    db: Database | None = None  # waiver carrier, workdir-scoped decisions
    workdir: str = ''

    # ---- public surface ----

    def check(self, workdir: Path | str) -> list[dict]:
        """Active findings (rule, fingerprint, message, locations), with
        waived findings attached as {'waived': True, ...}."""
        workdir = Path(workdir)
        findings: list[dict] = []
        findings += self._private_access(workdir)
        findings += self._duplicate_bodies(workdir)
        waivers = self._waivers(workdir)
        for f in findings:
            if f['fingerprint'] in waivers:
                f['waived'] = True
        return findings

    def report(self, workdir: Path | str) -> str:
        active = [f for f in self.check(workdir) if not f.get('waived')]
        waived = [f for f in self.check(workdir) if f.get('waived')]
        if not active and not waived:
            return 'arch_lint: clean — no seam leaks or duplicated bodies found.'
        lines = []
        for f in active:
            lines.append(f"[{f['rule']}] {f['message']}")
            lines += [f'  - {loc}' for loc in f['locations']]
            lines.append(
                f"  fix this or waive explicitly: waive_finding("
                f"'{f['fingerprint']}', reason)"
            )
        for f in waived:
            lines.append(f"[{f['rule']}] WAIVED ({f['fingerprint']}): {f['message']}")
        return '\n'.join(lines)

    def waive(self, fingerprint: str, reason: str) -> str:
        if self.db is None:
            raise RuntimeError('waivers need a database (ArchLint(db=...))')
        decision_id = RoadmapStore(self.db).create_decision(
            self.workdir, f'{WAIVER_PREFIX} {fingerprint}', reason
        )
        return f'finding {fingerprint} waived (decision #{decision_id})'

    # ---- rules ----

    def _private_access(self, workdir: Path) -> list[dict]:
        # A module reaches into ANOTHER module's _private surface:
        # `import mod` + `mod._x`, or `from pkg import mod` + `mod._x`.
        stems = {p.stem for p, _ in _trees(workdir)}
        findings: list[dict] = []
        for path, tree in _trees(workdir):
            hits: list[str] = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute) or not node.attr.startswith('_'):
                    continue
                value = node.value
                root = None
                if isinstance(value, ast.Name):
                    root = value.id
                elif isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                    root = value.attr  # pkg.mod._x -> mod
                if root is not None and root in stems and root != path.stem:
                    hits.append(f'{path.name}:{node.lineno}')
            if hits:
                findings.append({
                    'rule': 'private-access',
                    'fingerprint': _fp('private-access', path.name, hits),
                    'message': (
                        f'{path.stem} reaches into module {hits[0].split(".")[0]}'
                        f"'s _private surface — not a seam"
                    ),
                    'locations': hits,
                })
        return findings

    def _duplicate_bodies(self, workdir: Path) -> list[dict]:
        functions: list[_Fn] = []
        for path, tree in _trees(workdir):
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(_Fn(
                        file=str(path.relative_to(workdir)),
                        line=node.lineno,
                        name=node.name,
                        body_key=_body_key(node),
                    ))
        by_body: dict[str, list[_Fn]] = defaultdict(list)
        for fn in functions:
            by_body[fn.body_key].append(fn)
        findings: list[dict] = []
        for group in by_body.values():
            if len(group) < 2:
                continue
            locations = [f'{fn.file}:{fn.line} ({fn.name})' for fn in group]
            findings.append({
                'rule': 'duplicate-body',
                'fingerprint': _fp('duplicate-body', group[0].body_key),
                'message': (
                    f'identical function body duplicated {len(group)}x: '
                    + ', '.join(fn.name for fn in group)
                ),
                'locations': locations,
            })
        return findings

    # ---- waivers ----

    def _waivers(self, workdir: Path) -> set[str]:
        if self.db is None:
            return set()
        store = RoadmapStore(self.db)
        return {
            d['title'].split(' ', 1)[1]
            for d in store.list_decisions(str(workdir))
            if d['title'].startswith(WAIVER_PREFIX + ' ')
        }


def _trees(workdir: Path):
    for path in sorted(workdir.rglob('*.py')):
        if any(part in ('.venv', 'venv', 'node_modules', '.git') for part in path.parts):
            continue
        try:
            yield path, ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:
            continue  # unparseable file: not this linter's job


def _body_key(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Normalize a function body: parameters renamed positionally, docstrings
    dropped — so call-site naming can't mask identical behavior."""

    class _Canonicalize(ast.NodeTransformer):
        def __init__(self) -> None:
            self.names: dict[str, str] = {}

        def visit_arg(self, node: ast.arg) -> ast.arg:  # noqa: N802
            pos = len(self.names)
            self.names[node.arg] = f'arg{pos}'
            node.arg = f'arg{pos}'
            return node

        def visit_Name(self, node: ast.Name) -> ast.Name:  # noqa: N802
            node.id = self.names.get(node.id, node.id)
            return node

    stripped = [
        s for s in node.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
    ]
    copy = ast.FunctionDef(
        name='f', args=node.args, body=stripped, decorator_list=[],
        returns=None, type_params=[], lineno=1, col_offset=0,
        end_lineno=1, end_col_offset=0,
    )
    _Canonicalize().visit(copy)
    norm = ast.dump(ast.Module(body=[copy], type_ignores=[]), include_attributes=False)
    return hashlib.sha256(norm.encode()).hexdigest()[:12]


def _fp(rule: str, *parts: object) -> str:
    payload = json.dumps([rule, *(str(p) for p in parts)])
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def build_archlint_toolset(workdir: Path | str, lint: ArchLint) -> FunctionToolset:
    """Agent tools: run the linter before finishing; fix or explicitly waive."""

    async def arch_lint() -> str:
        """Run the architecture linter (seam leaks, duplicated bodies). Fix every finding or waive it explicitly — never ignore one."""
        return lint.report(workdir)

    async def waive_finding(fingerprint: str, reason: str) -> str:
        """Explicitly waive an architecture-lint finding; recorded as a design decision."""
        return lint.waive(fingerprint, reason)

    return FunctionToolset([arch_lint, waive_finding])
