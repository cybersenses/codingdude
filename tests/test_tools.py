"""Engine seam: the scripted model drives real read-only tools on a temp Workdir."""

from helpers import scripted

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def tool_then_answer(tool_name: str, tool_args: dict, answer_check):
    """Scripted model: call a tool on turn 1, answer from the tool result on turn 2."""

    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name=tool_name, args=tool_args)]
            )
        returns = [
            p.content
            for m in messages
            for p in m.parts
            if isinstance(p, (ToolReturnPart, RetryPromptPart))
        ]
        return ModelResponse(parts=[TextPart(content=answer_check(returns))])

    return scripted(fn)


async def test_read_file_tool(engine, workdir):
    outcome = await engine.run(
        prompt='read the app',
        workdir=workdir,
        model=tool_then_answer(
            'read_file',
            {'path': 'src/app.py'},
            lambda returns: (
                'found greet' if any('greet' in str(r) for r in returns) else 'missing'
            ),
        ),
    )
    assert outcome.output == 'found greet'


async def test_grep_tool_finds_content(engine, workdir):
    outcome = await engine.run(
        prompt='where is greet?',
        workdir=workdir,
        model=tool_then_answer(
            'grep',
            {'pattern': 'greet'},
            lambda returns: (
                'in app.py' if any('app.py' in str(r) for r in returns) else 'missing'
            ),
        ),
    )
    assert outcome.output == 'in app.py'


async def test_list_dir_and_glob_tools(engine, workdir):
    for tool_name, args, marker in [
        ('list_dir', {'path': '.'}, 'README.md'),
        ('glob', {'pattern': 'src/*.py'}, 'app.py'),
    ]:
        outcome = await engine.run(
            prompt=f'list via {tool_name}',
            workdir=workdir,
            model=tool_then_answer(
                tool_name,
                args,
                lambda returns, marker=marker: (
                    'saw files' if any(marker in str(r) for r in returns) else 'missing'
                ),
            ),
        )
        assert outcome.output == 'saw files', tool_name


async def test_outside_workdir_is_refused_not_crashing(engine, workdir):
    def answer(returns):
        if any('outside' in str(r).lower() for r in returns):
            return 'refused it'
        return 'no refusal seen'

    outcome = await engine.run(
        prompt='read the secret',
        workdir=workdir,
        model=tool_then_answer(
            'read_file', {'path': '../secret.txt'}, answer
        ),
    )
    assert outcome.output == 'refused it'
