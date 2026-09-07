"""Engine seam: surgical edits — search/replace primary, whole-file fallback for new files."""

from dataclasses import dataclass

from helpers import scripted

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
)


@dataclass
class Collector:
    events: list

    def __call__(self, event):
        self.events.append(event)


def tool_then_answer(tool_name: str, tool_args: dict, answer_check):
    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name=tool_name, args=tool_args)]
            )
        retries = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, RetryPromptPart)
        ]
        return ModelResponse(parts=[TextPart(content=answer_check(retries))])

    return scripted(fn)


async def test_edit_file_replaces_unique_match(engine, workdir):
    (workdir / 'src' / 'app.py').write_text('def greet():\n    return "hi"\n')
    collector = Collector([])
    outcome = await engine.run(
        prompt='fix the greeting',
        workdir=workdir,
        model=tool_then_answer(
            'edit_file',
            {
                'path': 'src/app.py',
                'old_text': 'return "hi"',
                'new_text': 'return "hello"',
            },
            lambda retries: 'done',
        ),
        on_event=collector,
    )
    assert outcome.output == 'done'
    assert (workdir / 'src' / 'app.py').read_text() == 'def greet():\n    return "hello"\n'
    edits = [e for e in collector.events if e.kind == 'edit']
    assert len(edits) == 1
    assert edits[0].path == 'src/app.py'
    assert edits[0].before == 'def greet():\n    return "hi"\n'
    assert edits[0].after == 'def greet():\n    return "hello"\n'


async def test_edit_file_no_match_retries_and_file_untouched(engine, workdir):
    before = (workdir / 'src' / 'app.py').read_text()
    outcome = await engine.run(
        prompt='edit something',
        workdir=workdir,
        model=tool_then_answer(
            'edit_file',
            {'path': 'src/app.py', 'old_text': 'NOT PRESENT', 'new_text': 'x'},
            lambda retries: (
                'told-model' if any('not found' in r.lower() for r in retries) else 'no-hint'
            ),
        ),
    )
    assert outcome.output == 'told-model'
    assert (workdir / 'src' / 'app.py').read_text() == before


async def test_edit_file_multiple_matches_retries(engine, workdir):
    (workdir / 'src' / 'app.py').write_text('x = 1\nx = 1\n')
    outcome = await engine.run(
        prompt='edit ambiguous',
        workdir=workdir,
        model=tool_then_answer(
            'edit_file',
            {'path': 'src/app.py', 'old_text': 'x = 1', 'new_text': 'y = 2'},
            lambda retries: (
                'told-ambiguous' if any('more than once' in r.lower() for r in retries) else 'no-hint'
            ),
        ),
    )
    assert outcome.output == 'told-ambiguous'
    assert (workdir / 'src' / 'app.py').read_text() == 'x = 1\nx = 1\n'


async def test_write_file_creates_new_file_with_dirs(engine, workdir):
    collector = Collector([])
    await engine.run(
        prompt='add a module',
        workdir=workdir,
        model=tool_then_answer(
            'write_file',
            {'path': 'src/newpkg/mod.py', 'content': 'VALUE = 1\n'},
            lambda retries: 'done',
        ),
        on_event=collector,
    )
    assert (workdir / 'src' / 'newpkg' / 'mod.py').read_text() == 'VALUE = 1\n'
    edits = [e for e in collector.events if e.kind == 'edit']
    assert len(edits) == 1 and edits[0].path == 'src/newpkg/mod.py'


async def test_write_file_refuses_to_clobber_nonempty_file(engine, workdir):
    before = (workdir / 'src' / 'app.py').read_text()
    outcome = await engine.run(
        prompt='clobber it',
        workdir=workdir,
        model=tool_then_answer(
            'write_file',
            {'path': 'src/app.py', 'content': 'CLOBBERED'},
            lambda retries: (
                'refused' if any('edit_file' in r for r in retries) else 'wrote-anyway'
            ),
        ),
    )
    assert outcome.output == 'refused'
    assert (workdir / 'src' / 'app.py').read_text() == before
