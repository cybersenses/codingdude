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
#: returned "REVIEW FAILED ... request_limit of 8"].
#:
#: The ceiling is a SPIN guard, not a cost guard — `spend_limits` carries the
#: cost and token ceilings — so it only has to stop a tool-happy reviewer
#: looping inside the 300s timeout. It must therefore sit above any real branch
#: rather than at the first round number: at 40 the budget stopped growing at
#: sixteen files while the file count did not, so a wide branch's unavoidable
#: per-file reads exhausted it and the reviewer failed with no verdict again —
#: the same outage as the fixed 8, further out [probe: `review_request_limit(33)
#: == 40` before this change, while that 33-file branch needed at least 41 (one
#: read per file plus the floor) — the old ceiling was already short by the
#: weakest possible reading, before counting any verdict requests]. 120 is the
#: floor plus two per file up to 56 files, past the widest branch this repo has
#: produced (33 files, R93).
_REVIEW_REQUEST_FLOOR = 8
_REVIEW_REQUESTS_PER_FILE = 2
_REVIEW_REQUEST_CEILING = 120

#: A plan/step review's work is its steps, not the diff (#353). `_run_review`
#: reads the repository to check each plan step's claimed evidence, and it does
#: that on a clean tree too — where the diff is empty and the file count is
#: zero. So the branch caller's unit (a file) is joined by a plan caller's unit
#: (a step), priced the same: one read plus one narrowing look.
#:
#: The failure this replaces: a six-step plan on a clean tree was read as "a
#: branch that touched nothing", given the empty-diff floor of 8, and the pass
#: died mid-verification without a verdict [probe: the step reviewer returned
#: "REVIEW FAILED — the reviewer did not run (UsageLimitExceeded: ... The next
#: request would exceed the request_limit of 8 ...)"].
_REVIEW_REQUESTS_PER_PLAN_STEP = 2


def review_request_limit(changed_files: int, plan_steps: int = 0) -> int:
    """Requests for one review pass: the floor plus two per work item.

    The two callers of `planning._review_impl` do not have the same work, so
    neither can be priced from the diff alone:

    * a BRANCH review (`review_diff_findings`, `plan_steps=0`) reads the files
      the diff touches — its work items are those files;
    * a PLAN review (`_run_review`, the step-evidence check) reads the
      repository to verify each plan step, and does so however small the diff
      is. `plan_steps` is how many steps it must verify.

    Both are counted: a plan review on a wide branch has both kinds of work.

    Load-bearing and pinned by test: up to the ceiling's crossover the budget is
    at least one request per work item plus the floor, so the reads a review
    *must* make can never exhaust it; and it is monotone in both arguments.

    Past the crossover a very wide diff or a very long plan may leave the
    reviewer under-provisioned. That residual is accepted because it is visible:
    the pass fails loudly (`REVIEW FAILED — …`) rather than returning '', and
    `''` is the only CLEAN signal the push gate can read from a review. (The
    gate itself never parses that string — `review_gate.require_review` demands
    a `diff_key`-matched record — so the loud failure protects the *reader*, not
    the gate.)

    Zero work items yields the floor, and that is correct only for the branch
    review: an empty diff has no file the reviewer could read. It was NOT
    correct for a plan review — that was the #353 outage, which is why the plan
    caller now states how much work it has instead of being read as a branch
    that touched nothing. One degraded path remains indistinguishable at this
    seam: an unanswerable `git` makes `review_gate.collect_review_diff` return
    '' (it returns '' on failure), which also counts 0. That is not a hole in
    the gate — `require_review` keys off `resolve_base`, never this count — and
    a reviewer handed an empty diff answers CLEAN in about one request.
    """
    per_file = _REVIEW_REQUESTS_PER_FILE * max(0, int(changed_files))
    per_step = _REVIEW_REQUESTS_PER_PLAN_STEP * max(0, int(plan_steps))
    return min(_REVIEW_REQUEST_CEILING, _REVIEW_REQUEST_FLOOR + per_file + per_step)

