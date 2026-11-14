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

