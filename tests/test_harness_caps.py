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

from types import SimpleNamespace

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
    services = _FakeServices(prompt_cache='1h')  # caching ON, so the list is real
    names = _names(one_shot_capabilities(services))
    assert 'Caching' in names          # the positive half of the claim
    assert 'ToolOutputLimits' not in names
    assert 'WarnOnCacheBusts' not in names


class _FakeServices:
    """Just enough of RunServices for one_shot_capabilities' cache profile."""

    def __init__(self, prompt_cache=False, prompt_cache_messages=False):
        self.config = SimpleNamespace(models=SimpleNamespace(
            prompt_cache=prompt_cache,
            prompt_cache_messages=prompt_cache_messages,
            prompt_cache_settings={},
        ))


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


def test_a_missing_harness_degrades_instead_of_killing_the_run(monkeypatch):
    """These capabilities sit on top of the ProcessHistory guard, so a venv
    without the harness (or a harness that moves these modules) must fall back
    to the previous behaviour — not raise inside every agent build."""
    import sys

    from codingdude.run_pipeline import _bounded_output_capabilities

    monkeypatch.setitem(sys.modules, 'pydantic_ai_harness.tool_output_limits', None)
    assert _bounded_output_capabilities() == []

    monkeypatch.undo()
    assert _names(_bounded_output_capabilities()) == [
        'ToolOutputLimits', 'WarnOnCacheBusts',
    ]


def test_the_harness_and_the_core_version_it_pins_are_installed():
    """pydantic-ai-harness 0.68 pins pydantic-ai-slim==2.68 exactly; adopting
    the harness means adopting that core version."""
    import importlib.metadata as metadata

    def parts(version: str) -> tuple[int, ...]:
        """Numeric version parts — `'0.100.0' >= '0.68.0'` is False as a string,
        which would fail this guard on the first legitimate 0.100 release."""
        out = []
        for chunk in version.split('.'):
            digits = ''.join(c for c in chunk if c.isdigit())
            out.append(int(digits) if digits else 0)
        return tuple(out)

    assert parts(metadata.version('pydantic-ai-harness'))[:2] >= (0, 68)
    core = metadata.version('pydantic-ai')
    assert parts(core)[:2] >= (2, 68)
    assert metadata.version('pydantic-ai-slim') == core
