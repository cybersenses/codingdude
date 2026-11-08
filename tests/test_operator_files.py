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
"""R80-3 #295 (DE-5): operator kill-switch and steer files.

Seam: the OperatorFilesToolset wrapper — the tool-call dispatch boundary the
agent already crosses. AGENT_STOP present → no tool executes (OperatorHalt);
STEER.md present and non-empty → content injected once into the model-visible
result, then truncated to zero (consume-once). Poll-free by construction:
checks happen only at call_tool.
"""

import pytest
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from codingdude.operator_files import (
    OperatorFilesToolset,
    OperatorHalt,
    clear_steer,
    operator_files_toolset,
    peek_steer,
    stop_requested,
)


@pytest.fixture
def inner_calls():
    return []


@pytest.fixture
def inner(inner_calls):
    def echo(path: str) -> str:
        inner_calls.append(path)
        return f'echo:{path}'

    return FunctionToolset([echo])


def _ctx():
    """Minimal RunContext for tool enumeration (plain function schemas
    ignore it; get_tools needs max_retries/_tool_name_path defaults)."""
    from pydantic_ai._run_context import RunContext
    from pydantic_ai.usage import RunUsage

    return RunContext(
        deps=None, model=None, usage=RunUsage(), messages=[], tracer=None,
        retries={}, workspace=None,
    )


async def _call(wrapped, name: str, **args):
    """Drive one tool call through the wrapper with the real ToolsetTool
    (FunctionToolset asserts its own tool type) and a minimal context."""
    ctx = _ctx()
    tools = await wrapped.get_tools(ctx)
    tool = tools.get(name)
    assert tool is not None, f'tool {name!r} not found in toolset'
    return await wrapped.call_tool(name, args, ctx=ctx, tool=tool)



def test_stop_requested_false_when_absent(workdir):
    assert stop_requested(workdir) is False


def test_stop_requested_true_when_present(workdir):
    (workdir / 'AGENT_STOP').write_text('', encoding='utf-8')
    assert stop_requested(workdir) is True


def test_peek_steer_empty_when_absent(workdir):
    assert peek_steer(workdir) == ''


def test_peek_steer_reads_without_truncating(workdir):
    (workdir / 'STEER.md').write_text('prefer ruff', encoding='utf-8')
    assert peek_steer(workdir) == 'prefer ruff'
    # peek only: the file must survive for the consume step
    assert (workdir / 'STEER.md').read_text(encoding='utf-8') == 'prefer ruff'


def test_peek_steer_skips_empty_file(workdir):
    (workdir / 'STEER.md').write_text('   \n', encoding='utf-8')
    assert peek_steer(workdir) == ''


def test_clear_steer_truncates_to_zero(workdir):
    (workdir / 'STEER.md').write_text('prefer ruff', encoding='utf-8')
    clear_steer(workdir)
    assert (workdir / 'STEER.md').exists()
    assert (workdir / 'STEER.md').read_text(encoding='utf-8') == ''


def test_clear_steer_tolerates_missing_file(workdir):
    clear_steer(workdir)  # must not raise


async def test_wrapper_passes_result_through_without_files(workdir, inner):
    wrapped = operator_files_toolset(inner, workdir)
    result = await _call(wrapped, 'echo', path='a.txt')
    assert result == 'echo:a.txt'


async def test_wrapper_halts_before_executing_tool(workdir, inner, inner_calls):
    (workdir / 'AGENT_STOP').write_text('', encoding='utf-8')
    wrapped = operator_files_toolset(inner, workdir)
    with pytest.raises(OperatorHalt):
        await _call(wrapped, 'echo', path='a.txt')
    # no tool executes once the stop file is present
    assert inner_calls == []


async def test_wrapper_injects_steer_once_and_consumes(workdir, inner):
    (workdir / 'STEER.md').write_text('prefer ruff', encoding='utf-8')
    wrapped = operator_files_toolset(inner, workdir)
    first = await _call(wrapped, 'echo', path='a.txt')
    assert '[OPERATOR STEER]' in first
    assert 'prefer ruff' in first
    # consume-once: file truncated, second call carries no steer block
    assert (workdir / 'STEER.md').read_text(encoding='utf-8') == ''
    second = await _call(wrapped, 'echo', path='b.txt')
    assert '[OPERATOR STEER]' not in second


async def test_wrapper_survives_steer_file_when_tool_fails(workdir):
    """A steer written before a failing tool call is not lost: the file stays
    (not consumed) so the next successful boundary injects it."""
    calls = []

    def flaky(path: str) -> str:
        calls.append(path)
        if len(calls) == 1:
            raise ModelRetry('transient')
        return 'ok'

    wrapped = operator_files_toolset(FunctionToolset([flaky]), workdir)
    (workdir / 'STEER.md').write_text('prefer ruff', encoding='utf-8')
    with pytest.raises(ModelRetry):
        await _call(wrapped, 'flaky', path='a')
    # not consumed on failure
    assert (workdir / 'STEER.md').read_text(encoding='utf-8') == 'prefer ruff'
    injected = await _call(wrapped, 'flaky', path='a')
    assert '[OPERATOR STEER]' in injected


async def test_wrapper_race_inflight_call_completes(workdir):
    """Race semantics (pinned): AGENT_STOP appearing DURING a tool execution
    does not abort that call — it completes and returns its result; the halt
    fires at the next boundary. Documented in PRD REQ-5 / design DE-5."""
    calls = []

    def slow(path: str) -> str:
        calls.append(path)
        if len(calls) == 1:
            # operator drops the stop file while the tool is in flight
            (workdir / 'AGENT_STOP').write_text('', encoding='utf-8')
        return f'echo:{path}'

    wrapped = operator_files_toolset(FunctionToolset([slow]), workdir)
    result = await _call(wrapped, 'slow', path='a')
    assert result == 'echo:a'
    with pytest.raises(OperatorHalt):
        await _call(wrapped, 'slow', path='b')



def test_wrapper_accepts_toolset_list(workdir, inner):
    wrapped = operator_files_toolset([inner], workdir)
    assert isinstance(wrapped, OperatorFilesToolset)


def _tool_calling_model(tool_name: str, args: dict, final: str):
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

    def fn(messages, info):
        if not any(
            isinstance(p, ToolCallPart) for m in messages for p in m.parts
        ):
            return ModelResponse(
                parts=[ToolCallPart(tool_name=tool_name, args=args)]
            )
        return ModelResponse(parts=[TextPart(content=final)])

    return FunctionModel(fn)


def _steer_aware_model(tool_name: str, args: dict):
    """Call a tool, then answer with what the tool result carried — so the
    test asserts on what the MODEL saw, not on the raw return value."""
    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )

    def fn(messages, info):
        if not any(
            isinstance(p, ToolCallPart) for m in messages for p in m.parts
        ):
            return ModelResponse(
                parts=[ToolCallPart(tool_name=tool_name, args=args)]
            )
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        seen = any('[OPERATOR STEER]' in r for r in returns)
        steer_text = any('mention-ruff-please' in r for r in returns)
        verdict = (
            'saw-marker+text' if seen and steer_text
            else 'saw-marker' if seen
            else 'no-steer'
        )
        return ModelResponse(parts=[TextPart(content=verdict)])

    return FunctionModel(fn)


async def test_engine_halts_when_stop_file_present(home, workdir):
    """M4 seam: AGENT_STOP at the workdir root aborts the run within one
    tool call — the engine returns a 'halted' outcome, no tool executes."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    (workdir / 'AGENT_STOP').write_text('', encoding='utf-8')
    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(
        prompt='read the readme',
        workdir=workdir,
        model=_tool_calling_model('read_file', {'path': 'README.md'}, 'done'),
        approvals=ApprovalPolicy(yolo=True),
    )
    assert outcome.status == 'halted'


async def test_engine_completes_without_stop_file(home, workdir):
    """No operator file → today's behavior byte-for-byte (contract pin)."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(
        prompt='read the readme',
        workdir=workdir,
        model=_tool_calling_model('read_file', {'path': 'README.md'}, 'done'),
        approvals=ApprovalPolicy(yolo=True),
    )
    assert outcome.status == 'complete'


async def test_engine_steer_reaches_model_and_is_consumed(home, workdir):
    """STEER.md content is injected once into the model-visible tool result;
    the file is truncated after, so a follow-up run sees nothing."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    (workdir / 'STEER.md').write_text('mention-ruff-please', encoding='utf-8')
    engine = Engine(config=load_config(), db=Database.connect(home))
    policy = ApprovalPolicy(yolo=True)
    outcome = await engine.run(
        prompt='read the readme',
        workdir=workdir,
        model=_steer_aware_model('read_file', {'path': 'README.md'}),
        approvals=policy,
    )
    assert outcome.status == 'complete'
    assert outcome.output == 'saw-marker+text'
    # consume-once: truncated to zero, still present (not deleted)
    assert (workdir / 'STEER.md').read_text(encoding='utf-8') == ''
    # a second run on the same workdir sees no steer
    outcome2 = await engine.run(
        prompt='read the readme again',
        workdir=workdir,
        model=_steer_aware_model('read_file', {'path': 'README.md'}),
        approvals=policy,
    )
    assert outcome2.output == 'no-steer'

