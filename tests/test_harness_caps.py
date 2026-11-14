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
"""R93-B: upstream harness capabilities that bound tool output at the source."""

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from codingdude.context import ContextManager
from codingdude.run_pipeline import (
    _TOOL_OUTPUT_CHARS,
    _TOOL_OUTPUT_KEEP_CHARS,
    context_capabilities,
    one_shot_capabilities,
)


def _caps():
    """The RUN-seam capabilities, without the per-request guard under test here."""
    return context_capabilities(ContextManager(model_limit=128_000), None,
                                per_request=False, models=None)


def _names(caps) -> list[str]:
    return [type(c).__name__ for c in caps]


def _tool_return_sizes(result) -> list[int]:
    return [
        len(str(p.content))
        for m in result.all_messages()
        for p in m.parts
        if type(p).__name__ == 'ToolReturnPart'
    ]


async def _run_with_caps(payload: str, caps):
    def big() -> str:
        """Return a payload."""
        return payload

    def fn(messages, info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name='big', args={})])
        return ModelResponse(parts=[TextPart(content='done')])

    agent = Agent(model=FunctionModel(fn), toolsets=[FunctionToolset([big])],
                  capabilities=caps)
    return await agent.run('go')


# --- wiring ----------------------------------------------------------------


def test_run_capabilities_carry_the_harness_guards():
    names = _names(_caps())
    assert 'ToolOutputLimits' in names
    assert 'WarnOnCacheBusts' in names


def test_one_shot_agents_keep_prefix_caching_only():
    """One-shot agents send a fresh conversation; output bounding there is not
    part of this ticket's scope and would change their cost profile."""
    services = _FakeServices()
    assert 'ToolOutputLimits' not in _names(one_shot_capabilities(services))


class _FakeServices:
    """Just enough of RunServices for one_shot_capabilities' cache profile."""

    class config:  # noqa: N801 - mirrors the attribute shape it stands in for
        class models:  # noqa: N801
            prompt_cache = False
            prompt_cache_messages = False
            prompt_cache_settings: dict = {}


# --- behaviour -------------------------------------------------------------


async def test_an_oversized_tool_return_is_bounded_before_it_reaches_history():
    oversized = 'x' * 200_000
    assert len(oversized) > _TOOL_OUTPUT_CHARS
    result = await _run_with_caps(oversized, _caps())
    [size] = _tool_return_sizes(result)
    assert size <= _TOOL_OUTPUT_KEEP_CHARS


async def test_an_ordinary_tool_return_is_untouched():
    ordinary = 'line of output\n' * 100  # ~1.5k chars
    result = await _run_with_caps(ordinary, _caps())
    [size] = _tool_return_sizes(result)
    assert size == len(ordinary)


async def test_the_cap_sits_below_a_single_full_read():
    """read_file caps at 256KB; one such return is ~64k tokens, so the
    source-level cap has to sit below it to be worth anything."""
    from codingdude.tools import MAX_READ_BYTES

    assert _TOOL_OUTPUT_CHARS < MAX_READ_BYTES
    assert _TOOL_OUTPUT_KEEP_CHARS < _TOOL_OUTPUT_CHARS


# --- dependency guard ------------------------------------------------------


def test_the_harness_and_the_core_version_it_pins_are_installed():
    """pydantic-ai-harness 0.68 pins pydantic-ai-slim==2.68 exactly; adopting
    the harness means adopting that core version."""
    import importlib.metadata as metadata

    assert metadata.version('pydantic-ai-harness') >= '0.68.0'
    core = metadata.version('pydantic-ai')
    assert tuple(int(p) for p in core.split('.')[:2]) >= (2, 68)
    assert metadata.version('pydantic-ai-slim') == core
