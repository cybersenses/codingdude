"""Engine seam: Memory — remember/forget tools, retrieval injection, extraction."""

from helpers import scripted

from codingdude.memory import MemoryStore
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def call_then_answer(tool_name: str, args: dict, check):
    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=args)])
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, (ToolReturnPart, TextPart))
        ]
        return ModelResponse(parts=[TextPart(content=check('\n'.join(returns)))])

    return scripted(fn)


async def test_remember_and_forget_tools(engine, db, workdir):
    outcome = await engine.run(
        prompt='bank this',
        workdir=workdir,
        model=call_then_answer(
            'remember',
            {'content': 'User prefers uv over pip'},
            lambda r: 'banked' if 'remembered' in r else 'no',
        ),
    )
    assert outcome.output == 'banked'
    entries = MemoryStore(db).all_entries()
    assert any('uv over pip' in e['content'] for e in entries)

    outcome = await engine.run(
        prompt='drop it',
        workdir=workdir,
        model=call_then_answer(
            'forget', {'content_substring': 'uv over pip'}, lambda r: 'dropped' if 'forgot' in r else 'no'
        ),
    )
    assert outcome.output == 'dropped'
    entries = MemoryStore(db).all_entries()
    assert not any('uv over pip' in e['content'] for e in entries)


async def test_retrieval_injects_relevant_memory_at_session_start(engine, db, workdir):
    MemoryStore(db).add('always use uv, never pip in this project', scope='workdir', workdir=str(workdir))

    def echo_context(messages, info):
        text = ''.join(
            str(p.content) for m in messages for p in m.parts if hasattr(p, 'content')
        )
        text += getattr(info, 'instructions', '') or ''
        return ModelResponse(parts=[TextPart(content=text[-4000:])])

    outcome = await engine.run(
        prompt='hello', workdir=workdir, model=scripted(echo_context)
    )
    assert 'never pip' in outcome.output


async def test_memory_scoped_by_workdir(engine, db, workdir):
    MemoryStore(db).add('project-specific fact', scope='workdir', workdir=str(workdir))
    MemoryStore(db).add('global preference fact', scope='global')
    other = workdir / 'other'
    other.mkdir()

    entries_here = MemoryStore(db).retrieve(str(workdir), query='fact')
    contents = [e['content'] for e in entries_here]
    assert 'project-specific fact' in contents
    assert 'global preference fact' in contents

    entries_other = [e['content'] for e in MemoryStore(db).retrieve(str(other), query='fact')]
    assert 'project-specific fact' not in entries_other
    assert 'global preference fact' in entries_other


async def test_post_session_extraction_banks_missed_facts(home, db, workdir):
    from codingdude.config import load_config
    from codingdude.engine import Engine

    def extractor(messages, info):
        return ModelResponse(
            parts=[
                TextPart(
                    content='the user always names variables in snake_case'
                )
            ]
        )

    engine = Engine(
        config=load_config(), db=db,
        extraction_model=scripted(extractor),
    )
    await engine.run(
        prompt='note something',
        workdir=workdir,
        model=call_then_answer(
            'remember', {'content': 'explicit fact'}, lambda r: 'ok'
        ),
    )
    entries = [e['content'] for e in MemoryStore(db).all_entries()]
    assert 'explicit fact' in entries
    assert any('snake_case' in c for c in entries)
