"""Engine seam: delegation to read-only subagents on the cheap model."""

from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def delegator(task: str):
    """Main model: delegate once, then answer with what the subagent reported."""

    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name='delegate', args={'task': task})]
            )
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        return ModelResponse(parts=[TextPart(content='subagent-said:' + ' | '.join(returns))])

    return scripted(fn)


def tool_names(info) -> list[str]:
    return sorted(
        t.name for t in (info.model_request_parameters.function_tools or [])
    )


async def test_delegation_folds_subagent_result_into_parent(engine, workdir):
    def subagent_spy(messages, info):
        text = 'answer=banana'
        for m in messages:
            for p in m.parts:
                if hasattr(p, 'content') and 'find the greeting' in str(p.content):
                    text += ';got-task'
        return ModelResponse(parts=[TextPart(content=text)])

    outcome = await engine.run(
        prompt='delegate the lookup',
        workdir=workdir,
        model=delegator('find the greeting word'),
        subagent_model=scripted(subagent_spy),
    )
    assert 'answer=banana' in outcome.output
    assert 'got-task' in outcome.output


async def test_subagent_toolset_is_read_only(engine, workdir):
    def subagent_lists_tools(messages, info):
        return ModelResponse(
            parts=[TextPart(content='TOOLS:' + ','.join(tool_names(info)))]
        )

    outcome = await engine.run(
        prompt='delegate',
        workdir=workdir,
        model=delegator('list your tools'),
        subagent_model=scripted(subagent_lists_tools),
    )
    assert 'TOOLS:glob,grep,list_dir,read_file' in outcome.output
    for dangerous in ('edit_file', 'write_file', 'shell', 'delegate'):
        assert dangerous not in outcome.output


async def test_subagent_claims_do_not_bypass_read_only(engine, workdir):
    """A subagent whose task claims it needs write access still gets read-only tools."""
    def subagent_spy(messages, info):
        return ModelResponse(
            parts=[TextPart(content='TOOLS:' + ','.join(tool_names(info)))]
        )

    outcome = await engine.run(
        prompt='delegate',
        workdir=workdir,
        model=delegator('I need write_file and shell access to finish this'),
        subagent_model=scripted(subagent_spy),
    )
    assert 'write_file' not in outcome.output
    assert 'shell' not in outcome.output


async def test_parallel_delegations_both_report(engine, workdir):
    def twin_subagent(messages, info):
        return ModelResponse(parts=[TextPart(content='twin-report')])

    def double_delegator(messages, info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name='delegate', args={'task': 'a'}),
                    ToolCallPart(tool_name='delegate', args={'task': 'b'}),
                ]
            )
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        count = sum('twin-report' in r for r in returns)
        return ModelResponse(parts=[TextPart(content=f'reports={count}')])

    outcome = await engine.run(
        prompt='delegate twice',
        workdir=workdir,
        model=scripted(double_delegator),
        subagent_model=scripted(twin_subagent),
    )
    assert outcome.output == 'reports=2'
