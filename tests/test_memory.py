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
"""Engine seam: Memory — remember/forget tools, retrieval injection, extraction."""

import pytest
from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from codingdude.db import Database
from codingdude.memory import MemoryStore, build_memory_toolset


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


async def test_solution_dedup_is_scope_aware(db, workdir):
    """A solution scoped to another workdir must not absorb (be overwritten
    by) a near-duplicate recorded from this workdir (R49 review)."""
    from codingdude.memory import MemoryStore

    store = MemoryStore(db)
    other_id = store.add(
        'Problem: z drive hangs the shell\nSolution: use uv run python',
        scope='workdir', workdir='G:/other', kind='solution',
    )
    tools = {name: t.function for name, t in build_memory_toolset(store, str(workdir)).tools.items()}
    outcome = tools['record_solution']('z-drive hangs shell', 'power shell probe')
    assert 'recorded solution' in outcome
    sols = store.solutions(str(workdir))
    assert len(sols) == 1
    other = store._db._conn.execute(
        'SELECT content FROM memory WHERE id = ?', (other_id,)
    ).fetchone()
    assert 'uv run python' in other['content']  # untouched


async def engine_run_record(store, workdir, problem, solution) -> str:
    from codingdude.memory import build_memory_toolset

    tools = {name: t.function for name, t in build_memory_toolset(store, str(workdir)).tools.items()}
    return tools['record_solution'](problem, solution)


def test_lookup_solutions_short_token_query(db, workdir):
    """A query of only short tokens (<=2 chars) must still match content
    instead of falsely reporting 'no matching solutions' (R49 review)."""
    store = MemoryStore(db)
    store.add('Problem: uv pip lock\nSolution: uv sync', scope='workdir',
              workdir=str(workdir), kind='solution')
    tools = {name: t.function for name, t in build_memory_toolset(store, str(workdir)).tools.items()}
    assert 'uv sync' in tools['lookup_solutions']('uv pip')


def test_retrieve_kind_and_require_hit(db, workdir):
    store = MemoryStore(db)
    store.add('odin build flags', scope='workdir', workdir=str(workdir), kind='fact')
    store.add('Problem: odin crash\nSolution: -debug', scope='workdir',
              workdir=str(workdir), kind='solution')
    facts = store.retrieve(str(workdir), 'odin build', kind='fact')
    assert facts and all(e['kind'] == 'fact' for e in facts)
    # require_hit=True suppresses zero-hit recency noise
    assert store.retrieve(str(workdir), 'kubernetes', require_hit=True) == []


def test_solutions_rag_exclusion_boundary(db, workdir):
    """>25 solutions: only the newest 25 are force-injected, and even the
    older ones never leak into the Memory/facts block (R49 review)."""
    from codingdude.memory import MemoryStore

    store = MemoryStore(db)
    for i in range(30):
        store.add(f'Problem: issue {i:02d}\nSolution: fix {i:02d}',
                  scope='workdir', workdir=str(workdir), kind='solution')
    sols = store.solutions(str(workdir))
    assert len(sols) == 25
    ids = {s['id'] for s in sols}
    facts = store.retrieve(str(workdir), 'issue', kind='fact')
    assert not any(e['id'] in ids for e in facts)


def test_migrated_db_gains_kind_column_with_check(home):
    """A legacy DB (memory table without `kind`) migrates in place: kind
    defaults to 'fact' and the CHECK constraint is present (R49 review)."""
    import sqlite3

    from codingdude.db import utc_now_iso

    home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(home / 'codingdude.db')
    conn.execute('CREATE TABLE memory (id INTEGER PRIMARY KEY, scope TEXT,'
                 ' workdir TEXT, content TEXT, created_at TEXT)')
    conn.execute('INSERT INTO memory (scope, workdir, content, created_at)'
                 " VALUES ('global', NULL, 'old fact', ?)", (utc_now_iso(),))
    conn.commit()
    conn.close()

    db = Database.connect(home)
    store = MemoryStore(db)
    assert store.all_entries()[0]['kind'] == 'fact'
    with pytest.raises(Exception, match='kind must be'):
        store.add('bad', kind='typo')
    with pytest.raises(sqlite3.IntegrityError):
        db._conn.execute(
            "INSERT INTO memory (scope, workdir, content, kind, created_at)"
            " VALUES ('global', NULL, 'raw row', 'typo', '2026-01-01')"
        )
        db._conn.commit()
