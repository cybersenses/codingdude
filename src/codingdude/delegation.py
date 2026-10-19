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
"""Delegation task briefs (R16): ship verified context with a delegated task
so the subagent doesn't burn its request budget rediscovering what the parent
already knows.

Mining is deliberately local: identifier-like tokens from the task text,
existence-verified by a bounded scan of the workdir, plus the governing
`## Contract` section from docs/specs/*.md when one references a verified
symbol. No codegraph dependency — it's an MCP server, not a library.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .ast_tools import SKIP_DIRS

_TOKEN_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{3,}')
_SUFFIXES = {'.py', '.md', '.ts', '.tsx', '.js', '.mjs'}
_MAX_FILES = 2000
_MAX_FILE_BYTES = 1_000_000


@dataclass
class DelegationBrief:
    """Verified context accompanying a delegated task (R16)."""

    task: str
    budget: int
    symbols: list[str] = field(default_factory=list)
    contract: str | None = None
    contract_source: str | None = None


def candidate_symbols(task: str) -> list[str]:
    """Identifier-like tokens in the task text, deduped, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _TOKEN_RE.finditer(task):
        tok = match.group(0)
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _iter_target_files(workdir: Path):
    count = 0
    for path in sorted(workdir.rglob('*')):
        if not path.is_file() or path.suffix not in _SUFFIXES:
            continue
        rel = path.relative_to(workdir)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if count >= _MAX_FILES:
            return
        count += 1
        yield path


def verify_symbols(workdir: Path, tokens: list[str]) -> list[str]:
    """Tokens that appear in at least one workdir file, in task order."""
    if not tokens:
        return []
    remaining = list(dict.fromkeys(tokens))
    found: set[str] = set()
    for path in _iter_target_files(workdir):
        if not remaining:
            break
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for tok in list(remaining):
            if tok in text:
                found.add(tok)
                remaining.remove(tok)
    return [t for t in dict.fromkeys(tokens) if t in found]


def find_contract(workdir: Path, symbols: list[str]) -> tuple[str | None, str | None]:
    """First `## Contract` section from docs/specs/*.md mentioning a verified
    symbol. Returns (section text, spec path relative to workdir) or (None,
    None)."""
    specs = workdir / 'docs' / 'specs'
    if not symbols or not specs.is_dir():
        return None, None
    for spec in sorted(specs.glob('*.md')):
        try:
            text = spec.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if '## Contract' not in text:
            continue
        section = text.split('## Contract', 1)[1]
        section = section.split('\n## ', 1)[0].strip()
        for sym in symbols:
            if sym in section:
                return section, spec.relative_to(workdir).as_posix()
    return None, None


def build_brief(task: str, workdir: Path, budget: int) -> DelegationBrief:
    """Gather the delegation brief: verified symbols + governing contract."""
    symbols = verify_symbols(workdir, candidate_symbols(task))
    contract, source = find_contract(workdir, symbols)
    return DelegationBrief(
        task=task, budget=budget, symbols=symbols,
        contract=contract, contract_source=source,
    )


def brief_prompt(brief: DelegationBrief) -> str:
    """The subagent run input: the task verbatim, plus verified context."""
    parts = [brief.task]
    extras: list[str] = []
    if brief.symbols:
        extras.append('Relevant symbols: ' + ', '.join(brief.symbols))
    if brief.contract:
        src = f' ({brief.contract_source})' if brief.contract_source else ''
        extras.append(f'Spec contract{src}:\n{brief.contract}')
    if extras:
        parts.append('Delegation brief:\n' + '\n'.join(extras))
    return '\n\n'.join(parts)
