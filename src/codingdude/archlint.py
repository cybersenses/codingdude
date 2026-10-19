# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""R8: architecture linter — seam leaks and duplicated behavior, soft-block.

Findings must be fixed or explicitly waived; a waiver is recorded as a design
decision (workdir-scoped) so overturning architecture is always visible.
"""

import ast
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import FunctionToolset

from codingdude.pyparse import parse_python

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
        findings += self._missing_contract(workdir)
        findings += self._adr_contradiction(workdir)
        findings += self._spec_contracts(workdir)
        waivers = self._waivers(workdir)
        for f in findings:
            if f['fingerprint'] in waivers:
                f['waived'] = True
        return findings

    def report(self, workdir: Path | str) -> str:
        workdir = Path(workdir)
        active = [f for f in self.check(workdir) if not f.get('waived')]
        waived = [f for f in self.check(workdir) if f.get('waived')]
        stale = sorted(self._stale_waivers(workdir))
        if not active and not waived and not stale:
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
        for fingerprint in sorted(self._stale_waivers(workdir)):
            lines.append(
                f'[stale-waiver] WAIVER {fingerprint} matches no finding — '
                'retire the decision (fix shipped; the waiver is obsolete)'
            )
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

    def _spec_contracts(self, workdir: Path) -> list[dict]:
        """R14 contract-first discipline: a `## Contract` section in a spec
        (docs/specs/*.md) names exported symbols (single-word backticked
        names). Each must exist as a top-level function/class and be
        referenced by at least one test. Soft findings, waivable like any
        other rule."""
        specs_dir = workdir / 'docs' / 'specs'
        if not specs_dir.is_dir():
            return []
        names: dict[str, str] = {}  # symbol -> spec file
        for spec in sorted(specs_dir.glob('*.md')):
            try:
                text = spec.read_text(encoding='utf-8')
            except OSError:
                continue
            m = re.search(r'^##\s+Contract\s*$', text, re.MULTILINE)
            if not m:
                continue
            section = text[m.end():]
            nxt = re.search(r'^##\s+', section, re.MULTILINE)
            if nxt:
                section = section[:nxt.start()]
            for ticked in re.findall(r'`([^`]+)`', section):
                # dotted paths (pkg.mod.Name) resolve to the symbol itself
                parts = ticked.split('.')
                if all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', p) for p in parts):
                    names.setdefault(parts[-1], spec.name)
        if not names:
            return []
        defined = {
            node.name
            for _, tree in _trees(workdir)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef))
        }
        tests_dir = workdir / 'tests'
        tested_names: set[str] = set()
        if tests_dir.is_dir():
            for tf in tests_dir.rglob('*.py'):
                try:
                    ttext = tf.read_text(encoding='utf-8', errors='ignore')
                except OSError:
                    continue
                tested_names.update(n for n in names if n in ttext)
        findings: list[dict] = []
        for name, spec_file in sorted(names.items()):
            if name not in defined:
                findings.append({
                    'rule': 'spec-contract-missing',
                    'fingerprint': _fp('spec-contract-missing', name),
                    'message': (
                        f"spec {spec_file} Contract names '{name}' but no "
                        f'top-level function/class with that name exists - '
                        f'implement it or waive explicitly'
                    ),
                    'locations': [f'{spec_file}: {name}'],
                })
            elif name not in tested_names:
                findings.append({
                    'rule': 'spec-contract-untested',
                    'fingerprint': _fp('spec-contract-untested', name),
                    'message': (
                        f"spec {spec_file} Contract names '{name}' but no "
                        f'test under tests/ references it - add a test or '
                        f'waive explicitly'
                    ),
                    'locations': [f'{spec_file}: {name}'],
                })
        return findings

    # ---- waivers ----

    def _missing_contract(self, workdir: Path) -> list[dict]:
        # Contract-first codegen (R8): every public top-level function or
        # class under src/ must carry a docstring contract. Waivable like
        # any other finding.
        findings: list[dict] = []
        for path, tree in _trees(workdir):
            if 'src' not in path.parts:
                continue
            hits = [
                f'{path.name}:{node.lineno} ({node.name})'
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and not node.name.startswith('_')
                and not ast.get_docstring(node)
            ]
            if hits:
                findings.append({
                    'rule': 'missing-contract',
                    'fingerprint': _fp('missing-contract', path.name, hits),
                    'message': (
                        f'public code under src/ without a docstring contract: '
                        f'{path.name} — document the contract or waive explicitly'
                    ),
                    'locations': hits,
                })
        return findings

    def _adr_contradiction(self, workdir: Path) -> list[dict]:
        """A recorded design decision that references a module (``pkg/mod.py``
        or ``pkg.mod``) which no longer exists may be contradicted by the
        code — flagged so the decision is revisited or retired."""
        if self.db is None:
            return []
        src_root = workdir / 'src'
        search_roots = [src_root] if src_root.is_dir() else [workdir]
        findings: list[dict] = []
        for decision in RoadmapStore(self.db).list_decisions(str(workdir)):
            if decision['title'].startswith(WAIVER_PREFIX + ' '):
                continue  # waivers already have stale-waiver hygiene
            text = f"{decision['title']} {decision.get('body') or ''}"
            missing = sorted({
                ref
                for ref in _referenced_modules(text)
                if not any((root / ref).exists() for root in search_roots)
                and not any((root / ref.replace('.', '/')).with_suffix('.py').exists()
                            for root in search_roots)
            })
            if missing:
                findings.append({
                    'rule': 'adr-contradiction',
                    'fingerprint': _fp('adr-contradiction', decision['id'], missing[0]),
                    'message': (
                        f"decision #{decision['id']} '{decision['title']}' references "
                        f"{missing[0]} which no longer exists — the code may have "
                        f"moved on; revisit or retire the decision"
                    ),
                    'locations': [f"decision #{decision['id']}: {ref}" for ref in missing],
                })
        return findings

    def _stale_waivers(self, workdir: Path) -> set[str]:
        """Waivers whose finding no longer fires — the fix shipped, so the
        recorded decision should be retired (ADR hygiene)."""
        waived_fingerprints = {f['fingerprint'] for f in self.check(workdir)}
        return self._waivers(workdir) - waived_fingerprints

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
            yield path, parse_python(path.read_text(encoding='utf-8'))
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


def _referenced_modules(text: str) -> set[str]:
    """Module paths/dotted names a decision text refers to: `pkg/mod.py`,
    `pkg/mod`, ``pkg.mod`` (only multi-part dotted names count)."""
    refs: set[str] = set()
    for m in re.finditer(r'[\w./]+\.py\b', text):
        refs.add(m.group(0))
    for m in re.finditer(r'\b(?:\w+\.)+\w+\b', text):
        if not m.group(0).endswith('.py'):
            refs.add(m.group(0))
    return refs


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
