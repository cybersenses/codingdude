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
"""R93-A: a delegation is bounded by the run that caused it.

Two holes this pins shut:

- the delegated run was handed no `usage`, so its requests and tokens never
  reached the parent run's accounting or its limits;
- the operator kill-switch was observed only at the *main* agent's tool
  boundaries, so `AGENT_STOP` went unseen for the whole of a delegated run.
"""

from types import SimpleNamespace

import pytest
from helpers import scripted
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.usage import RunUsage, UsageLimits

from codingdude.config import DelegationConfig
from codingdude.delegation import child_usage_limits
from codingdude.operator_files import AGENT_STOP_NAME, OperatorHalt
from codingdude.tools import build_delegation_toolset


def _ctx(requests: int = 0, limits: UsageLimits | None = None) -> SimpleNamespace:
    """The real thing is supplied by pydantic-ai; a direct call supplies this.

    Limits default to the engine's configured `[models] request_limit` (500,
    see RunServices.usage_limits) — not `UsageLimits()`'s library default of
    50, which a long session has already passed.
    """
    return SimpleNamespace(
        usage=RunUsage(requests=requests),
        usage_limits=UsageLimits(request_limit=500) if limits is None else limits,
    )


def _tool(toolset):
    [tool] = list(toolset.tools.values())
    return tool


def _answer(text: str = 'ok'):
    return scripted(lambda messages, info: ModelResponse(parts=[TextPart(content=text)]))


def _chatty():
    """A subagent that never finishes: keeps calling a read tool."""
    return scripted(lambda messages, info: ModelResponse(
        parts=[ToolCallPart(tool_name='list_dir', args={'path': '.'})]
    ))


# ---- the model-visible surface is unchanged ----


def test_run_context_is_not_part_of_the_model_visible_schema(workdir):
    """`ctx` is pydantic-ai plumbing, not a parameter the model can fill."""
    tool = _tool(build_delegation_toolset(workdir, _answer(), session_id='s1'))
    schema = tool.function_schema.json_schema
    assert tool.takes_ctx is True
    assert 'ctx' not in schema['properties']
    assert schema['required'] == ['task']


# ---- delegated spend reaches the parent run ----


async def test_delegated_usage_lands_on_the_parent_run(workdir):
    ctx = _ctx()
    tool = _tool(build_delegation_toolset(workdir, _answer(), session_id='s1'))
    assert await tool.function(ctx, task='x') == 'ok'
    # the same accumulator the parent run holds is mutated in place
    assert ctx.usage.requests == 1
    assert ctx.usage.input_tokens > 0
    assert ctx.usage.output_tokens > 0


# ---- the budget is a slice of the session total, not a reset ----


def test_child_limits_allow_the_delegation_slice_after_prior_spend():
    limits = child_usage_limits(100, UsageLimits(request_limit=500), 3)
    assert limits.request_limit == 103


def test_child_limits_never_outrun_a_tighter_parent_limit():
    limits = child_usage_limits(100, UsageLimits(request_limit=101), 40)
    assert limits.request_limit == 101


def test_child_limits_carry_the_parents_cost_and_token_limits():
    parent = UsageLimits(request_limit=500, cost_limit=1.5, total_tokens_limit=9000)
    limits = child_usage_limits(0, parent, 40)
    assert limits.cost_limit == 1.5
    assert limits.total_tokens_limit == 9000
    assert limits.request_limit == 40


def test_child_limits_without_a_parent_still_bound_the_delegation():
    assert child_usage_limits(7, None, 40).request_limit == 47


def test_child_limits_floor_the_budget_at_one_request():
    assert child_usage_limits(0, None, 0).request_limit == 1


async def test_delegation_spends_its_slice_not_a_fresh_budget(workdir):
    """100 requests already spent + max_requests=3 means three more, not three
    total: a bare `UsageLimits(request_limit=3)` against the shared counter
    would have aborted before the delegated run made its first request."""
    ctx = _ctx(requests=100)
    toolset = build_delegation_toolset(
        workdir, _chatty(), session_id='s1',
        delegation_config=DelegationConfig(max_requests=3),
    )
    out = await _tool(toolset).function(ctx, task='loop forever')
    assert 'delegation aborted' in out
    assert ctx.usage.requests == 103


# ---- the operator kill-switch is observed inside a delegation ----


async def test_operator_stop_aborts_a_delegation(workdir):
    (workdir / AGENT_STOP_NAME).write_text('', encoding='utf-8')
    tool = _tool(build_delegation_toolset(workdir, _chatty(), session_id='s1'))
    with pytest.raises(OperatorHalt):
        await tool.function(_ctx(), task='do work')


# ---- a delegation bills its own share, not the session's total ----


def test_usage_delta_reports_only_what_the_delegation_spent():
    """Sharing the accumulator makes result.usage the session total; billing
    that would charge the whole session to every delegation (and the parent
    bills the same spend again on its own result)."""
    from codingdude.tools import _usage_delta, _UsageTotals

    before = _UsageTotals(requests=100, input_tokens=5_000, output_tokens=200)
    after = SimpleNamespace(requests=104, input_tokens=6_200, output_tokens=520)
    spent = _usage_delta(before, after)
    assert (spent.requests, spent.input_tokens, spent.output_tokens) == (4, 1_200, 320)
    assert spent.cost is None


async def test_delegation_bills_the_delta_not_the_session_total(workdir, tmp_path):
    from codingdude.db import Database

    db = Database.connect(tmp_path / 'home')
    session_id = db.create_session(workdir)
    toolset = build_delegation_toolset(workdir, _answer(), session_id=session_id, db=db)
    # a session that has already made 100 requests
    await _tool(toolset).function(_ctx(requests=100), task='x')
    rows = db.session_usage(session_id)
    assert rows.get('requests') == 1  # this delegation's one request, not 101


# ---- the two usage rows partition the spend (no double count) ----


def test_the_ledger_net_is_the_run_minus_its_delegations():
    """The parent's row must be charged the remainder of a shared accumulator,
    or `session_usage` (which the Budget Cap reads) counts delegated spend
    twice and halts the session at roughly half the real spend."""
    from codingdude.delegation import DelegatedSpend

    ledger = DelegatedSpend()
    ledger.add(SimpleNamespace(
        requests=4, input_tokens=1_200, output_tokens=320, cost=0.25))
    net = ledger.net(SimpleNamespace(
        requests=10, input_tokens=3_000, output_tokens=800, cost=0.70))
    assert (net.requests, net.input_tokens, net.output_tokens) == (6, 1_800, 480)
    assert net.cost == pytest.approx(0.45)


def test_the_ledger_never_makes_a_run_row_negative():
    from codingdude.delegation import DelegatedSpend

    ledger = DelegatedSpend()
    ledger.add(SimpleNamespace(
        requests=9, input_tokens=100, output_tokens=100, cost=2.0))
    net = ledger.net(SimpleNamespace(
        requests=2, input_tokens=10, output_tokens=10, cost=1.0))
    assert (net.requests, net.input_tokens, net.output_tokens, net.cost) == (0, 0, 0, 0.0)


def test_the_ledger_keeps_an_unknown_cost_unknown():
    from codingdude.delegation import DelegatedSpend

    ledger = DelegatedSpend()
    net = ledger.net(SimpleNamespace(
        requests=1, input_tokens=1, output_tokens=1, cost=None))
    assert net.cost is None


async def test_delegated_spend_is_recorded_once_across_both_rows(workdir, tmp_path):
    """End-to-end at the accounting seam: the delegation writes its own row and
    the ledger gives the run's row the remainder, so the session total equals
    the true spend instead of double-counting the delegated slice."""
    from codingdude.db import Database
    from codingdude.delegation import DelegatedSpend

    db = Database.connect(tmp_path / 'home')
    session_id = db.create_session(workdir)
    ledger = DelegatedSpend()
    toolset = build_delegation_toolset(
        workdir, _answer(), session_id=session_id, db=db, spend_ledger=ledger,
    )
    ctx = _ctx()
    await _tool(toolset).function(ctx, task='x')

    # the run bills the remainder of the same accumulator the delegation used
    net = ledger.net(ctx.usage)
    db.record_usage(
        session_id, model='main', requests=net.requests,
        input_tokens=net.input_tokens, output_tokens=net.output_tokens,
        cost_usd=net.cost,
    )
    totals = db.session_usage(session_id)
    assert totals['requests'] == ctx.usage.requests  # 1, not 2
    assert totals['input_tokens'] == ctx.usage.input_tokens
    assert totals['output_tokens'] == ctx.usage.output_tokens


async def test_an_aborted_delegation_is_still_billed_and_traced(workdir, tmp_path):
    """A delegation that burns its whole slice is the one case where spend is
    guaranteed — it used to return before billing and before its terminal
    trace event, so the cost vanished and DELEGATION_STARTED had no peer."""
    from codingdude.db import Database

    db = Database.connect(tmp_path / 'home')
    session_id = db.create_session(workdir)
    events: list[dict] = []
    toolset = build_delegation_toolset(
        workdir, _chatty(), session_id=session_id, db=db,
        emitter=events.append,
        delegation_config=DelegationConfig(max_requests=3),
    )
    out = await _tool(toolset).function(_ctx(requests=100), task='loop')
    assert 'delegation aborted' in out
    assert db.session_usage(session_id)['requests'] == 3  # the slice it spent
    completed = [e for e in events if e['type'] == 'DELEGATION_COMPLETED']
    assert len(completed) == 1
    assert completed[0]['aborted'] is True
    assert completed[0]['requests'] == 3


async def test_the_abort_message_names_the_limit_that_actually_fired(workdir):
    """`child_usage_limits` takes the min of the delegation slice and the
    session cap; blaming the delegation's 40 when the session's own limit bound
    it sends the operator to the wrong setting."""
    ctx = _ctx(requests=100, limits=UsageLimits(request_limit=101))
    toolset = build_delegation_toolset(
        workdir, _chatty(), session_id='s1',
        delegation_config=DelegationConfig(max_requests=40),
    )
    out = await _tool(toolset).function(ctx, task='loop')
    assert 'session request limit of 101' in out
    assert 'budget of 40' not in out


async def test_the_abort_message_names_the_delegation_budget_when_it_binds(workdir):
    toolset = build_delegation_toolset(
        workdir, _chatty(), session_id='s1',
        delegation_config=DelegationConfig(max_requests=3),
    )
    out = await _tool(toolset).function(_ctx(requests=0), task='loop')
    assert 'delegation budget of 3' in out
    assert 'session request limit' not in out

