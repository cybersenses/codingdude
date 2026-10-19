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
    await engine.drain_post_run()
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
    await engine.drain_post_run()
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
    await engine.drain_post_run()
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
    await engine.drain_post_run()  # extraction (incl. FORGET) runs in the tail

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


async def test_solution_kind_and_solutions_accessor(db, workdir):
    """kind defaults to 'fact'; solutions() returns only kind='solution' rows
    scoped global+workdir, newest first."""
    store = MemoryStore(db)
    store.add('an ordinary fact', scope='workdir', workdir=str(workdir))
    store.add(
        'Problem: edit races on tmp file\nSolution: unique tmp names + retry',
        scope='workdir', workdir=str(workdir), kind='solution',
    )
    store.add('global solution fact', scope='global', kind='solution')

    sols = store.solutions(str(workdir))
    contents = [s['content'] for s in sols]
    assert 'Problem: edit races on tmp file\nSolution: unique tmp names + retry' in contents
    assert 'global solution fact' in contents
    assert 'an ordinary fact' not in contents
    assert all(s['kind'] == 'solution' for s in sols)


async def test_record_solution_tool_updates_paraphrase_duplicate(engine, db, workdir):
    """Re-recording the same problem updates the existing entry instead of
    duplicating it (annotate-on-solve discipline)."""
    outcome = await engine.run(
        prompt='log the fix',
        workdir=workdir,
        model=call_then_answer(
            'record_solution',
            {'problem': 'atomic write tmp collision', 'solution': 'unique uuid tmp names'},
            lambda r: 'ok' if 'recorded solution' in r else 'no',
        ),
    )
    assert outcome.output == 'ok'
    store = MemoryStore(db)
    assert len(store.solutions(str(workdir))) == 1

    outcome = await engine.run(
        prompt='log the better fix',
        workdir=workdir,
        model=call_then_answer(
            'record_solution',
            {'problem': 'atomic-write tmp name collision',
             'solution': 'unique uuid tmp names + bounded os.replace retry'},
            lambda r: 'ok' if 'updated solution' in r else 'no',
        ),
    )
    assert outcome.output == 'ok'
    sols = store.solutions(str(workdir))
    assert len(sols) == 1
    assert 'os.replace retry' in sols[0]['content']


async def test_lookup_solutions_tool(engine, db, workdir):
    await engine.run(
        prompt='log the fix',
        workdir=workdir,
        model=call_then_answer(
            'record_solution',
            {'problem': 'cp1252 decode crash on git diff', 'solution': 'utf-8 + errors=replace'},
            lambda r: 'ok',
        ),
    )
    outcome = await engine.run(
        prompt='have I fixed this before?',
        workdir=workdir,
        model=call_then_answer(
            'lookup_solutions', {'query': 'git diff decode crash'},
            lambda r: 'found' if 'cp1252' in r and 'utf-8' in r else 'no',
        ),
    )
    assert outcome.output == 'found'

    outcome = await engine.run(
        prompt='anything about kubernetes?',
        workdir=workdir,
        model=call_then_answer(
            'lookup_solutions', {'query': 'kubernetes ingress'},
            lambda r: 'empty' if 'no matching solutions' in r else 'no',
        ),
    )
    assert outcome.output == 'empty'


async def test_solutions_forced_into_instructions_once(engine, db, workdir):
    """Forced recall: solutions are injected every session (not RAG-gated),
    and appear exactly once (no double-inject via the Memory block)."""
    MemoryStore(db).add(
        'Problem: z drive hangs the shell\nSolution: probe with PowerShell Test-Path',
        scope='workdir', workdir=str(workdir), kind='solution',
    )

    def echo_context(messages, info):
        text = ''.join(
            str(p.content) for m in messages for p in m.parts if hasattr(p, 'content')
        )
        text += getattr(info, 'instructions', '') or ''
        return ModelResponse(parts=[TextPart(content=text[-6000:])])

    outcome = await engine.run(
        prompt='hello', workdir=workdir, model=scripted(echo_context)
    )
    assert 'Referential solutions' in outcome.output
    assert outcome.output.count('z drive hangs the shell') == 1


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
    await engine.drain_post_run()
    types = [e['type'] for e in events]
    assert 'MEMORY_EXTRACTING' in types
    assert types.index('MEMORY_EXTRACTING') > types.index('RUN_USAGE')
    assert 'MEMORY_EXTRACTED' in types
