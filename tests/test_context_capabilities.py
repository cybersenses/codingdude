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
"""R91 #337: per-request context guard + prompt caching capabilities.

The run-start-only compaction (HistoryManager.maybe_compact) could not stop
mid-run growth: a long tool loop reached a 1.2M-token request and providers
400'd it (deepseek-flash incident). The guard here runs before EVERY model
request via pydantic-ai's ProcessHistory capability.
"""
from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import Caching, ProcessHistory
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from codingdude.context import CLEARED_STUB, ContextManager
from codingdude.run_pipeline import PromptAssembler, context_capabilities


class FakePart:
    def __init__(self, content: str, part_kind: str = "text"):
        self.content = content
        self.part_kind = part_kind


class FakeMsg:
    def __init__(self, *parts):
        self.parts = list(parts)


def _over_limit_history(cm: ContextManager) -> list:
    old = [FakeMsg(FakePart("r" * 4000, "tool-return")) for _ in range(5)]
    recent = [FakeMsg(FakePart(f"turn {i}")) for i in range(10)]
    return old + recent


def _events(traced):
    return [e for e in traced if isinstance(e, dict) and e.get("type") == "CONTEXT_COMPACTED"]


def _collector(traced):
    """Engine passes `traced` (a callable); tests collect into a list."""
    def collect(event):
        traced.append(event)
    return collect


def test_capabilities_compact_over_limit_and_emit_event():
    cm = ContextManager(model_limit=6_000)
    traced: list = []
    caps = context_capabilities(cm, _collector(traced))
    assert caps, "guard disabled"
    processor = caps[0].processor
    history = _over_limit_history(cm)
    compacted = processor(list(history))
    assert "[earlier tool result cleared" in compacted[0].parts[0].content
    assert compacted[5:] == history[5:]
    events = _events(traced)
    assert len(events) == 1
    assert events[0]["cleared"] == 3  # budget walk, see test_context.py
    assert events[0]["before_tokens"] > events[0]["after_tokens"]


def test_capabilities_under_limit_is_identity():
    cm = ContextManager(model_limit=100_000)
    traced: list = []
    caps = context_capabilities(cm, traced)
    processor = caps[0].processor
    history = [FakeMsg(FakePart("small"))]
    assert processor(list(history)) == history
    assert _events(traced) == []


def test_capabilities_fail_open_when_accounting_raises():
    class BrokenCM:
        def usage(self, messages):
            raise RuntimeError("estimator exploded")

    traced: list = []
    caps = context_capabilities(BrokenCM(), traced)
    processor = caps[0].processor
    history = [FakeMsg(FakePart("keep me"))]
    assert processor(list(history)) == history  # degradation, never a crash


def test_capabilities_gated_by_flags():
    cm = ContextManager(model_limit=6_000)
    traced: list = []
    assert context_capabilities(cm, traced, per_request=False,
                                prompt_cache=False) == []
    caps = context_capabilities(cm, traced, per_request=True, prompt_cache=False)
    assert len(caps) == 1 and isinstance(caps[0], ProcessHistory)
    caps = context_capabilities(cm, traced, per_request=False, prompt_cache=True)
    assert len(caps) == 1 and isinstance(caps[0], Caching)


def test_caching_capability_emits_unified_cache_setting():
    assert Caching().get_model_settings() == {"cache": True}


def test_prompt_assembler_forwards_capabilities_to_agent():
    assembler = PromptAssembler()
    caps = [Caching()]
    agent = assembler.agent(TestModel(), "instructions", [], capabilities=caps)
    assert agent._cap_model_settings == {"cache": True}


@pytest.mark.asyncio
async def test_agent_run_compacts_history_before_first_request():
    """End-to-end at the model seam: a persisted history over the limit is
    mechanically compacted before the FIRST model request goes out."""
    cm = ContextManager(model_limit=6_000)
    traced: list = []
    seen: list[list[ModelMessage]] = []

    def fn(messages, info):
        seen.append(list(messages))
        return ModelResponse(parts=[TextPart(content="done")])

    agent = Agent(
        model=FunctionModel(fn),
        capabilities=context_capabilities(cm, _collector(traced)),
    )
    history = [_pyai_user("start the task")]
    for i in range(5):
        history.extend(_pyai_tool_return("r" * 4000, f"call_{i}"))
    history.extend(_pyai_user(f"turn {i}") for i in range(10))
    await agent.run("finish up", message_history=history)
    assert seen, "model never called"
    first_request = seen[0]
    stubbed = [
        p.content for m in first_request for p in m.parts
        if isinstance(p, ToolReturnPart) and CLEARED_STUB in str(p.content)
    ]
    # Budget walk (keep 50% of 6000 = 3000 tokens): the newest returns fill
    # the budget, the oldest 3 are stubbed before the request goes out.
    assert len(stubbed) == 3, "old tool returns reached the wire unstubbed"
    assert len(_events(traced)) >= 1


def _pyai_tool_return(content: str, tool_call_id: str):
    """Real-shape history pair: the call lives in a ModelResponse (the
    assistant asked), the return in the following ModelRequest."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )

    call = ToolCallPart(tool_name="read_file", args={"path": "x"},
                        tool_call_id=tool_call_id)
    ret = ToolReturnPart(tool_name="read_file", content=content,
                         tool_call_id=tool_call_id)
    return [ModelResponse(parts=[call]), ModelRequest(parts=[ret])]


def _pyai_user(text: str):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    return ModelRequest(parts=[UserPromptPart(content=text)])
