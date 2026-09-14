"""Engine seam: Memory — remember/forget tools, retrieval injection, extraction."""

from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from codingdude.memory import MemoryStore


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


async def test_extraction_skips_paraphrase_duplicates(home, db, workdir):
    from codingdude.config import load_config
    from codingdude.engine import Engine

    MemoryStore(db).add(
        'the self-review was incomplete and cdissues.md still needs to be written',
        scope='workdir', workdir=str(workdir),
    )

    def extractor(messages, info):
        return ModelResponse(parts=[TextPart(content=(
            'the self-review task was incomplete and cdissues.md still needed '
            'to be written'
        ))])

    engine = Engine(config=load_config(), db=db, extraction_model=scripted(extractor))
    await engine.run(prompt='x', workdir=workdir, model=scripted(echo))

    entries = [e['content'] for e in MemoryStore(db).all_entries()]
    assert len(entries) == 1


async def test_extraction_forgets_obsolete_entries(home, db, workdir):
    from codingdude.config import load_config
    from codingdude.engine import Engine

    MemoryStore(db).add(
        'cdissues.md still needs to be written', scope='workdir', workdir=str(workdir),
    )

    def extractor(messages, info):
        return ModelResponse(parts=[TextPart(content=(
            'FORGET: cdissues.md still needs\n'
            'cdissues.md was written and the review closed'
        ))])

    engine = Engine(config=load_config(), db=db, extraction_model=scripted(extractor))
    await engine.run(prompt='x', workdir=workdir, model=scripted(echo))

    entries = [e['content'] for e in MemoryStore(db).all_entries()]
    assert entries == ['cdissues.md was written and the review closed']


def echo(messages, info):
    return ModelResponse(parts=[TextPart(content='done')])


async def test_retrieval_drops_zero_hit_noise(db, workdir):
    store = MemoryStore(db)
    store.add('unrelated fact about baking bread', scope='workdir', workdir=str(workdir))
    store.add('the project uses uv and ruff', scope='workdir', workdir=str(workdir))

    hits = [e['content'] for e in store.retrieve(str(workdir), query='ruff tooling')]
    assert hits == ['the project uses uv and ruff']


async def test_post_run_phase_events_are_emitted(home, db, workdir):
    """Regression: the post-run tail (memory extraction / claim check) must
    emit trace events so the UI never shows a silent multi-minute RUN_USAGE
    stall."""
    from codingdude.config import load_config
    from codingdude.engine import Engine

    def extractor(messages, info):
        return ModelResponse(parts=[TextPart(content='a fact')])

    events: list[dict] = []
    engine = Engine(
        config=load_config(), db=db, extraction_model=scripted(extractor)
    )
    await engine.run(
        prompt='note something',
        workdir=workdir,
        model=call_then_answer(
            'remember', {'content': 'explicit fact'}, lambda r: 'ok'
        ),
        emit=events.append,
    )
    types = [e['type'] for e in events]
    assert 'MEMORY_EXTRACTING' in types
    assert types.index('MEMORY_EXTRACTING') > types.index('RUN_USAGE')
    assert 'MEMORY_EXTRACTED' in types
