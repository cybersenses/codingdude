"""R25: tool runtime errors feed back to the agent (3 strikes).

An unexpected exception inside a tool (OSError, NameError, ...) used to
crash the run outright. It must instead become a ModelRetry the model can
act on; only after the retry budget (3) is exhausted does the run stop.
Control-flow exceptions (gates, approvals) pass through untouched.
"""
from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset

from codingdude.errors import GateRequired
from codingdude.tool_errors import error_feedback_toolset


def _agent(toolset, retries: int = 3) -> Agent:
    return Agent(
        model=TestModel(call_tools='all'),
        toolsets=[toolset],
        retries=retries,
    )


@pytest.mark.asyncio
async def test_unexpected_error_becomes_retry_and_run_survives():
    """A tool that fails once then succeeds: the error is fed back and the
    agent deals with it — the run completes."""
    calls = {'n': 0}

    def flaky() -> str:
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('boom: file locked')
        return 'ok'

    agent = _agent(error_feedback_toolset(FunctionToolset([flaky])))
    result = await agent.run('go')
    assert calls['n'] == 2
    assert 'ok' in result.output


@pytest.mark.asyncio
async def test_error_fed_back_names_tool_and_cause():
    """The retry prompt the model sees names the tool and the cause."""

    def always_fails() -> str:
        raise OSError('WinError 32: file in use')

    agent = _agent(error_feedback_toolset(FunctionToolset([always_fails])))
    with pytest.raises(UnexpectedModelBehavior, match=r"Tool 'always_fails' exceeded max retries count of 3"):
        await agent.run('go')


@pytest.mark.asyncio
async def test_gate_required_passes_through_unchanged():
    """Approval/gate control flow is not converted to a retry."""

    async def gated() -> str:
        raise GateRequired('git push')

    agent = _agent(error_feedback_toolset(FunctionToolset([gated])))
    with pytest.raises(GateRequired):
        await agent.run('go')


@pytest.mark.asyncio
async def test_model_retry_counts_against_budget():
    """Explicit ModelRetry still consumes the retry budget (unchanged)."""

    def stubborn() -> str:
        from pydantic_ai import ModelRetry

        raise ModelRetry('wrong args, fix them')

    agent = _agent(error_feedback_toolset(FunctionToolset([stubborn])))
    with pytest.raises(UnexpectedModelBehavior, match='exceeded max retries count of 3'):
        await agent.run('go')


def test_agent_default_retries_is_five():
    """The engine's agent gives tools 5 tries before the run stops.

    Raised 3 -> 5 with the gate diff-scope fix: deterministic edit failures
    (pre-existing gate findings, staleness races) exhausted the old budget.
    """
    from codingdude.run_pipeline import PromptAssembler

    assembler = PromptAssembler()
    agent = assembler.agent(TestModel(), 'instructions', [])
    assert agent._max_tool_retries == 5
