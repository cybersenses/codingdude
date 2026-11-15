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
"""What one `agent.run()` may spend (R94-B #346).

One definition for every seam that builds `UsageLimits`. Before this module
existed, only request *counts* were bounded: the main run, the fix loop, the
evaluator, the planning reviewer, the summariser, memory extraction, the claims
auditor and the vision inspector each either constructed a bare
`UsageLimits(request_limit=...)` or passed nothing at all. A run could therefore
carry a cost ceiling while the agents it triggered spent without one — the cap
would be a claim, not a limit.

Deliberately not in `delegation.py`: nothing here is delegation-specific, and
that module already owns brief mining, delegation budget arithmetic and span
naming.

Scope, stated: these are per-`agent.run()` ceilings. pydantic-ai checks them
against that call's own usage, and one-shot agents bill their spend to the
session ledger separately (`record_model_usage`). The *total* across a run
remains the session Budget Cap over `db.session_usage`; this bounds a single
call.
"""

from decimal import Decimal

from pydantic_ai.usage import UsageLimits


def spend_limits(models, request_limit: int | None = None) -> UsageLimits | None:
    """Ceilings for one `agent.run()`, or None when nothing is configured.

    `request_limit=None` leaves the request cap exactly as the caller had it —
    pydantic-ai's own default — so a seam that never bounded requests does not
    start doing so. That keeps an unconfigured install byte-identical in
    behaviour, which is the acceptance condition for R94-B.

    Returning `None` rather than an all-empty `UsageLimits` is what preserves
    that: `agent.run(usage_limits=None)` is the library default, whereas an
    explicitly constructed limits object could differ.

    `cost_limit` is enforceable only where pydantic-ai can price the model: the
    boundary check cannot fire without a cost, and `UsageLimits.check_cost`
    emits `CostNotFoundWarning` to say so. `max_total_tokens` needs no pricing,
    so it is the ceiling that always holds.
    """
    cost = getattr(models, 'max_cost_usd', None)
    tokens = getattr(models, 'max_total_tokens', None)
    if cost is None and tokens is None and request_limit is None:
        return None
    return UsageLimits(
        request_limit=request_limit,
        cost_limit=Decimal(str(cost)) if cost is not None else None,
        total_tokens_limit=tokens,
    )


#: A review pass reads the workdir file by file, so its request cost tracks the
#: number of files the diff touches. A fixed budget is a cap that refuses before
#: the work: R94-B's own pre-push review stopped at the old fixed 8 on a
#: seventeen-file branch and produced no verdict at all [probe: `_review_impl`
#: returned "REVIEW FAILED ... request_limit of 8"]. The ceiling keeps a
#: tool-happy reviewer from spinning.
_REVIEW_REQUEST_FLOOR = 8
_REVIEW_REQUESTS_PER_FILE = 2
_REVIEW_REQUEST_CEILING = 40


def review_request_limit(changed_files: int) -> int:
    """Requests for one review pass: the floor plus two per changed file."""
    per_file = _REVIEW_REQUESTS_PER_FILE * max(0, int(changed_files))
    return min(_REVIEW_REQUEST_CEILING, _REVIEW_REQUEST_FLOOR + per_file)
