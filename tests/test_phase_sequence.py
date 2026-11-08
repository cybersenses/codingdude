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
"""DE-7b (#299): phase sequencing — function-tagged sessions with handoff.

A phase boundary is a session boundary: when the active attempt's next
non-done step carries a function tag different from the session's current
phase, the next run starts fresh under that function's profile, seeded
with the handoff artifact. Untagged work stays byte-compatible.
(Sibling file: tests/test_execution.py is uniform CRLF and the edit tool
normalizes line endings — R66 lesson.)
"""

from dataclasses import replace

from helpers import scripted
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.config import Config, FunctionModelConfig
from codingdude.db import Database
from codingdude.execution import ExecutionStore, build_execution_toolset
from codingdude.roadmap import RoadmapStore


def _store(home, workdir):
    return ExecutionStore(Database.connect(home), str(workdir))


def _ticket(home, workdir):
    return RoadmapStore(Database.connect(home)).create_ticket(
        str(workdir), 'phase ticket', 'body: fix the parser')


def _profiled_config():
    models = replace(
        Config.defaults().models,
        functions={'coder': FunctionModelConfig(
            model='stub:coder-model', thinking='low')},
    )
    return replace(Config.defaults(), models=models)


def _plain_engine(db):
    from codingdude.engine import Engine

    return Engine(config=Config.defaults(), db=db)


def _capture(tag: str, seen: list):
    def fn(messages, info):
        seen.extend(
            str(getattr(p, 'content', ''))
            for m in messages for p in m.parts
        )
        return ModelResponse(parts=[TextPart(content=tag)])

    return scripted(fn)


def _profiled_engine(db, monkeypatch):
    """An engine whose `_model_from_name` resolves to scripted stubs; the
    coder profile's stub records what the phase session's model saw."""
    from codingdude.engine import Engine

    coder_seen: list[str] = []
    coder_model = _capture('phase-ok', coder_seen)

    def fake_model_from_name(name, base_url=None, providers=None):
        if name == 'stub:coder-model':
            return coder_model
        return _capture(f'model:{name}', [])

    monkeypatch.setattr(
        'codingdude.engine._model_from_name', fake_model_from_name)
    return Engine(config=_profiled_config(), db=db), coder_seen


# ---- store seam: next_phase + handoff artifact ----


def test_next_phase_returns_tagged_next_step(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=[
        'plain step',
        '[function:coder] implement it',
    ])
    store.set_step(attempt['id'], 0, 'done', command='x', exit_code=0,
                   key_output_line='ok')
    nxt = store.next_phase('s1')
    assert nxt is not None
    assert nxt['function'] == 'coder'
    assert nxt['step_index'] == 1
    assert nxt['ticket_id'] == tid
    assert nxt['attempt_id'] == attempt['id']


def test_next_phase_none_when_untagged_or_nothing_left(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['a', 'b'])
    # nothing done yet, but no tagged steps either
    assert store.next_phase('s1') is None
    store.set_step(attempt['id'], 0, 'done', command='x', exit_code=0,
                   key_output_line='ok')
    store.set_step(attempt['id'], 1, 'done', command='x', exit_code=0,
                   key_output_line='ok')
    # all steps done (still claimed): heading back to main
    assert store.next_phase('s1') is None


def test_next_phase_scans_only_this_sessions_claims(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    other = Database.connect(home).create_session(workdir)
    store.claim(tid, other, plan_steps=['[function:designer] sketch'])
    assert store.next_phase('s1') is None
    assert store.next_phase(other)['function'] == 'designer'


def test_phase_handoff_names_contract_and_progress(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=[
        'reproduce', '[function:coder] fix it',
    ])
    store.set_step(attempt['id'], 0, 'done', command='pytest -q',
                   exit_code=0, key_output_line='3 passed')
    text = store.phase_handoff(store.next_phase('s1'))
    assert 'Phase handoff: coder' in text
    assert 'phase ticket' in text
    assert '[done] reproduce' in text
    assert 'pytest -q' in text
    assert '[todo] [function:coder] fix it' in text


# ---- claim approval visibility: the operator sees the staffing ----


async def test_claim_result_names_staffed_functions(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    toolset = build_execution_toolset(store, 's1')
    [claim_ticket] = [
        t for t in toolset.tools.values() if t.name == 'claim_ticket']
    out = await claim_ticket.function(
        ticket_id=tid,
        plan_steps=[
            '[function:designer] sketch',
            '[milestone] [function:coder] build',
            '[function:coder] polish',
            '[function:evaluator] grade',
        ],
    )
    assert 'staffing: designer -> coder -> evaluator' in out


async def test_claim_result_untagged_has_no_staffing_line(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    toolset = build_execution_toolset(store, 's1')
    [claim_ticket] = [
        t for t in toolset.tools.values() if t.name == 'claim_ticket']
    out = await claim_ticket.function(ticket_id=tid, plan_steps=['a', 'b'])
    assert 'staffing:' not in out


# ---- engine: the phase transition ----


async def test_phase_transition_fresh_session_under_profile(
        home, db, workdir, monkeypatch):
    engine, coder_seen = _profiled_engine(db, monkeypatch)
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    sid = db.create_session(workdir)
    store.claim(tid, sid, plan_steps=['[function:coder] fix it'])
    # prior turns exist — a phase boundary wipes the model's message store
    db.append_messages(sid, 'old turn content')

    events: list[dict] = []
    outcome = await engine.run(
        prompt='continue the work', workdir=workdir, session_id=sid,
        model=scripted(lambda m, i: ModelResponse(
            parts=[TextPart(content='main-model-should-not-run')])),
        emit=events.append,
    )
    assert outcome.output == 'phase-ok'
    assert any(e.get('type') == 'PHASE_START' and e.get('function') == 'coder'
               for e in events)
    assert db.session_phase(sid) == 'coder'
    # the handoff reached the phase session's model (with the user's words)
    assert any('Phase handoff: coder' in s for s in coder_seen)
    assert any('continue the work' in s for s in coder_seen)
    # wipe: the old turn is gone from the message store
    stored = db.load_messages(sid)
    assert all('old turn content' not in (m or '') for m in stored)


async def test_untagged_run_is_byte_compatible(home, db, workdir):
    """No tagged steps anywhere: no PHASE_START, history keeps flowing."""
    engine = _plain_engine(db)
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    sid = db.create_session(workdir)
    store.claim(tid, sid, plan_steps=['untagged step'])

    events: list[dict] = []
    seen_one: list[str] = []
    await engine.run(
        prompt='turn one', workdir=workdir, session_id=sid,
        model=_capture('first', seen_one), emit=events.append,
    )
    assert not any(e.get('type') == 'PHASE_START' for e in events)
    assert db.session_phase(sid) is None

    seen_two: list[str] = []
    await engine.run(
        prompt='turn two', workdir=workdir, session_id=sid,
        model=_capture('second', seen_two), emit=events.append,
    )
    assert not any(e.get('type') == 'PHASE_START' for e in events)
    # history kept flowing: turn one's content is in the second run's input
    assert any('turn one' in s for s in seen_two)


async def test_phase_returns_to_main_on_untagged_boundary(
        home, db, workdir, monkeypatch):
    engine, coder_seen = _profiled_engine(db, monkeypatch)
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    sid = db.create_session(workdir)
    attempt = store.claim(tid, sid, plan_steps=[
        '[function:coder] fix it', 'plain cleanup',
    ])
    store.set_step(attempt['id'], 0, 'done', command='x', exit_code=0,
                   key_output_line='ok')
    db.set_session_phase(sid, 'coder')

    events: list[dict] = []
    outcome = await engine.run(
        prompt='wrap up', workdir=workdir, session_id=sid,
        model=scripted(lambda m, i: ModelResponse(
            parts=[TextPart(content='main-profile-answer')])),
        emit=events.append,
    )
    assert outcome.output == 'main-profile-answer'
    assert any(e.get('type') == 'PHASE_START' and e.get('function') is None
               for e in events)
    assert db.session_phase(sid) is None


async def test_no_transition_when_phase_is_unchanged(home, db, workdir):
    """Same phase as recorded: no boundary, no reset — the run continues."""
    engine = _plain_engine(db)
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    sid = db.create_session(workdir)
    store.claim(tid, sid, plan_steps=['[function:coder] fix it'])
    db.set_session_phase(sid, 'coder')

    events: list[dict] = []
    await engine.run(
        prompt='keep going', workdir=workdir, session_id=sid,
        model=scripted(lambda m, i: ModelResponse(
            parts=[TextPart(content='same-phase')])),
        emit=events.append,
    )
    assert not any(e.get('type') == 'PHASE_START' for e in events)
    assert db.session_phase(sid) == 'coder'


async def test_transition_suppresses_kickoff(home, db, workdir, monkeypatch):
    engine, coder_seen = _profiled_engine(db, monkeypatch)
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    sid = db.create_session(workdir)
    store.claim(tid, sid, plan_steps=['[function:coder] fix it'])
    events: list[dict] = []
    await engine.run(
        prompt='continue', workdir=workdir, session_id=sid,
        model=scripted(lambda m, i: ModelResponse(
            parts=[TextPart(content='ok')])),
        emit=events.append,
    )
    assert any(e.get('type') == 'PHASE_START' for e in events)
    assert not any(e.get('type') == 'KICKOFF' for e in events)


# ---- legacy DB: sessions.phase migrates additively ----


def test_sessions_phase_column_on_legacy_db(tmp_path):
    import sqlite3

    legacy = tmp_path / 'legacy-home'
    legacy.mkdir()
    conn = sqlite3.connect(legacy / 'codingdude.db')
    conn.executescript(
        'CREATE TABLE sessions (session_id TEXT PRIMARY KEY,'
        ' workdir TEXT NOT NULL, created_at TEXT NOT NULL,'
        ' updated_at TEXT NOT NULL, title TEXT,'
        ' context_tokens INTEGER, context_limit INTEGER,'
        ' keep_for_evals INTEGER NOT NULL DEFAULT 0);')
    conn.commit()
    conn.close()
    db = Database.connect(legacy)
    sid = db.create_session(tmp_path)
    assert db.session_phase(sid) is None
    db.set_session_phase(sid, 'coder')
    assert db.session_phase(sid) == 'coder'
