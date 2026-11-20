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
"""Delegation seam: what a delegated task carries, and what it may spend.

Two halves, both about the parent-to-subagent boundary:

- **Briefs (R16)**: ship verified context with a delegated task so the
  subagent doesn't burn its request budget rediscovering what the parent
  already knows. Mining is deliberately local: identifier-like tokens from the
  task text, existence-verified by a bounded scan of the workdir, plus the
  governing `## Contract` section from docs/specs/*.md when one references a
  verified symbol. No codegraph dependency — it's an MCP server, not a library.
- **Budget (R93-A)**: the delegated run shares the parent's usage accumulator,
  so its request allowance is a *slice* of the session total rather than a
  fresh grant (`child_usage_limits`).
"""

import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from pydantic_ai.usage import UsageLimits

from .tools import skip_parts

_TOKEN_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{3,}')
_SUFFIXES = {'.py', '.md', '.ts', '.tsx', '.js', '.mjs'}
_MAX_FILES = 2000
_MAX_FILE_BYTES = 1_000_000
#: Longest function fragment allowed in a span name (`delegate.<fragment>`).
_MAX_SPAN_FUNCTION = 24


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
        if skip_parts(rel):
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


def child_usage_limits(
    used_requests: int, parent_limits: UsageLimits | None, max_requests: int,
    *, used_cost: float | Decimal | None = None, max_cost_usd: float | None = None,
) -> UsageLimits:
    """`UsageLimits` for a delegated run that shares the parent's accumulator.

    A delegated run is handed the parent's `ctx.usage` so its spend is visible
    to the run that caused it (R93-A). That accumulator already holds whatever
    the session spent, so the child cannot be given a bare
    `UsageLimits(request_limit=max_requests)`: on any session that had already
    made `max_requests` requests, the delegation's *first* request would trip
    the limit. Instead the child's cap is the session total it is allowed to
    reach — `used + max_requests` — which preserves "this delegation may spend
    at most `max_requests` more requests".

    The parent's other limits (cost, tokens) are carried over unchanged: a
    delegation that pushes the session over a cost cap must abort exactly as
    the parent would. The parent's own `request_limit`, when tighter than the
    delegation slice, still wins — a delegation may never outrun the session.

    R94-B (#346): `max_cost_usd` is now a *ceiling*, not a receipt. It is
    translated into the same slice arithmetic — `already spent + allowance`,
    min'd with the run's own cost limit — so the delegation is stopped before
    the next request instead of being told afterwards that it overspent.
    """
    cap = max(1, int(max_requests))
    budget = max(0, int(used_requests or 0)) + cap
    cost_ceiling = cost_slice(used_cost, max_cost_usd)
    if parent_limits is None:
        return UsageLimits(request_limit=budget, cost_limit=cost_ceiling)
    parent_cap = parent_limits.request_limit
    if parent_cap is not None and parent_cap > 0:
        budget = min(budget, parent_cap)
    limits = replace(parent_limits, request_limit=budget)
    if cost_ceiling is None:
        return limits
    parent_cost = parent_limits.cost_limit
    if parent_cost is None:
        return replace(limits, cost_limit=cost_ceiling)
    # Normalised to Decimal for type hygiene, NOT because the mixed comparison
    # fails: it does not, and a float ceiling is enforced correctly.
    # [probe: python -c "min(0.6, Decimal('0.75'))" -> 0.6, no TypeError;
    #  UsageLimits(cost_limit=0.6).cost_limit -> 0.6, i.e. the float is kept
    #  as-is rather than coerced; check_before_request with that limit passes
    #  at cost=Decimal('0.10') and raises UsageLimitExceeded at
    #  Decimal('1.00')]. `UsageLimits` keeps whatever type it was handed, so
    # without this the ceiling this seam returns would be a float or a Decimal
    # depending on the caller, while every other ceiling here is a Decimal.
    tighter = min(Decimal(str(parent_cost)), cost_ceiling)
    return replace(limits, cost_limit=tighter)


def delegation_slice(used_requests: int, max_requests: int) -> int:
    """The request total a delegation may reach on its own: `used + slice`."""
    return max(0, int(used_requests or 0)) + max(1, int(max_requests))


def cost_slice(
    used_cost: float | Decimal | None, max_cost_usd: float | None,
) -> Decimal | None:
    """The cost total a delegation may reach: `already spent + allowance`.

    `None` when no allowance is configured, which is the default and therefore
    the previous behaviour. Mirrors `delegation_slice`: the delegated run shares
    the parent's accumulator, so a bare `cost_limit=max_cost_usd` would trip on
    the parent's spend before the delegation made a single request.

    A non-positive allowance is *not* read as "unset": `load_config` rejects one
    (`validate_optional_cost`), and a value that slipped through would otherwise
    silently mean "unlimited" — the failure mode this ticket exists to remove.
    It becomes a ceiling the delegation is already at, which refuses the spend.
    """
    if max_cost_usd is None:
        return None
    already = Decimal(str(used_cost)) if used_cost is not None else Decimal('0')
    return already + Decimal(str(max_cost_usd))


def delegation_abort_message(
    abort_reason: str | None, limits: UsageLimits,
    used_requests: int, max_requests: int,
) -> str:
    """Why a delegation stopped, naming the limit that actually fired (R94-B).

    A pure seam: the tool body used to branch inline on the request path alone,
    so a cost or token ceiling stopped the delegation and then reported a
    *request* budget. pydantic-ai's own message names the ceiling it tripped
    ("...would exceed the `cost_limit` of 0.75"), so that is preferred whenever
    the message is not about the request limit — the library cannot know about
    the session-vs-slice distinction, which only `child_usage_limits` makes.
    """
    if abort_reason and 'request_limit' not in abort_reason:
        return (
            f'delegation aborted: {abort_reason}. Narrow the task, or raise '
            'the limit that fired ([models].max_cost_usd / '
            '[models].max_total_tokens / [delegation].max_cost_usd).'
        )
    session_cap = limits.request_limit
    slice_cap = delegation_slice(used_requests, max_requests)
    if session_cap is not None and session_cap < slice_cap:
        # The session's own limit bound the delegation, not its slice
        # (child_usage_limits takes the min) — say which one fired.
        return (
            'delegation aborted: the session request limit of '
            f'{session_cap} was reached before the delegation slice of '
            f'{max_requests} could be spent. Raise '
            '[models].request_limit or split the task.'
        )
    return (
        'delegation aborted: exceeded the delegation budget of '
        f'{max_requests} model requests. Narrow the task and '
        'delegate again with a tighter question.'
    )


def delegate_span_name(function: str | None) -> str:
    """The trace span name for a delegation (R94-A #345).

    Every delegation used to be constructed as ``name='delegate'``, so a
    designer run and a coder run — possibly on different models — produced
    indistinguishable spans and no consumer could attribute latency or cost per
    function profile. The name is ``delegate`` when no function was requested
    and ``delegate.<function>`` otherwise.

    Derived from the fixed function registry only, never from task text: a span
    name carrying model output would mint a new name per task and defeat the
    aggregation the name exists for. The sanitiser below is defensive — an
    unknown function already raises ``ModelRetry`` long before this runs — so a
    caller that skips that check still cannot emit a wild cardinality value.
    """
    if not function:
        return 'delegate'
    cleaned = re.sub(r'[^a-z0-9]+', '_', str(function).strip().lower()).strip('_')
    cleaned = cleaned[:_MAX_SPAN_FUNCTION].strip('_')
    return f'delegate.{cleaned}' if cleaned else 'delegate'


@dataclass(frozen=True)
class NetUsage:
    """A run's own spend after its delegations are charged separately."""

    requests: int
    input_tokens: int
    output_tokens: int
    cost: float | None


class DelegatedSpend:
    """What this run's delegations spent, so usage rows stay disjoint.

    R93-A hands every delegated run the parent's `ctx.usage`, so the parent's
    own `result.usage` already contains the delegated requests and tokens. The
    delegation still writes its own usage row (that's the `by_function`
    attribution from #298) — and two rows describing the same spend double-count
    in `db.session_usage`, which sums the table and is what the Budget Cap
    reads. The cap would then trip at roughly half the real spend.

    So the rows partition the spend: the delegation row carries its slice, and
    the parent's run row is charged the remainder (`net`). One ledger per run —
    `Engine.run` creates it, hands it to the delegation toolset, and subtracts
    it when billing the run.
    """

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    def add(self, spent) -> None:
        """Record one delegation's slice (any object with the four fields)."""
        self.requests += int(getattr(spent, 'requests', 0) or 0)
        self.input_tokens += int(getattr(spent, 'input_tokens', 0) or 0)
        self.output_tokens += int(getattr(spent, 'output_tokens', 0) or 0)
        cost = getattr(spent, 'cost', None)
        if cost is not None:
            self.cost += float(cost)

    def net(self, usage) -> NetUsage:
        """`usage` minus what the delegations already billed to their own rows.

        Clamped at zero: a delegation that ran without the parent's accumulator
        (a test double, or a path that bills a delegation the run's usage does
        not contain) must never make the run's own row negative.
        """
        cost = getattr(usage, 'cost', None)
        return NetUsage(
            requests=max(0, int(getattr(usage, 'requests', 0) or 0) - self.requests),
            input_tokens=max(
                0, int(getattr(usage, 'input_tokens', 0) or 0) - self.input_tokens
            ),
            output_tokens=max(
                0, int(getattr(usage, 'output_tokens', 0) or 0) - self.output_tokens
            ),
            cost=None if cost is None else max(0.0, float(cost) - self.cost),
        )
