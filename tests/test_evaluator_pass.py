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
"""R80-4 #296 (DE-2): the evaluator pass — boundary-based grading.

Seams: plan-step marker syntax ([milestone] / [function:<name>] leading tags,
pinned here; DE-7's function tags join the same syntax), evaluations_json
persistence + the attempt-level 3-pass cap on ExecutionStore, the read-only
WorkEvaluator (fresh session, submit_verdict tool), the auto-triggers on
release('done') and milestone step completion (non-blocking until the
long-run flag lands), and the honest no-evaluator skip.
"""

import json

from helpers import scripted
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from test_lane import _init_repo

from codingdude.db import Database
from codingdude.execution import EVALUATOR_CAP, ExecutionStore


def _store(home, workdir):
    return ExecutionStore(Database.connect(home), str(workdir))


def _ticket(home, workdir):
    from codingdude.roadmap import RoadmapStore

    return RoadmapStore(Database.connect(home)).create_ticket(
        str(workdir), 'eval ticket', 'body: fix the thing')


# --- marker syntax (defined HERE, pinned by test; #299 joins function tags)


def test_marker_syntax_milestone_and_function(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=[
        '[milestone] ship the parser',
        '[function:designer] sketch the shape',
        '[milestone] [function:coder] implement it',
        'plain step',
    ])
    steps = json.loads(attempt['steps_json'])
    assert steps[0]['milestone'] is True
    assert 'function' not in steps[0]
    assert steps[1].get('function') == 'designer'
    assert 'milestone' not in steps[1]
    assert steps[2]['milestone'] is True and steps[2]['function'] == 'coder'
    assert 'milestone' not in steps[3] and 'function' not in steps[3]
    # text preserved verbatim — the annotation stays visible
    assert steps[0]['text'] == '[milestone] ship the parser'


def test_marker_tags_only_recognized_at_start(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=[
        'mention [milestone] mid-text — not a tag',
    ])
    steps = json.loads(attempt['steps_json'])
    assert 'milestone' not in steps[0]


def test_marker_keys_survive_set_step(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['[milestone] step'])
    store.set_step(attempt['id'], 0, 'done', command='pytest -q',
                   exit_code=0, key_output_line='1 passed')
    steps = json.loads(store.resume_state(tid)['steps_json'])
    assert steps[0]['milestone'] is True
    assert steps[0]['status'] == 'done'


# --- evaluations_json persistence + cap


def test_evaluations_column_exists_on_fresh_schema(home):
    cols = {
        r['name'] for r in Database.connect(home)._conn.execute(
            'PRAGMA table_info(ticket_execution)')
    }
    assert 'evaluations_json' in cols


def test_evaluations_migration_adds_column(tmp_path):
    """A pre-#296 database (no evaluations_json) gains the column on
    connect, additive — existing rows untouched."""
    import sqlite3

    legacy = tmp_path / 'home'
    legacy.mkdir()
    conn = sqlite3.connect(legacy / 'codingdude.db')
    # the pre-#296 ticket_execution shape (waivers + takeover, no evaluations)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS ticket_execution ('
        ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
        ' ticket_id INTEGER NOT NULL, workdir TEXT NOT NULL,'
        ' session_id TEXT NOT NULL,'
        " status TEXT NOT NULL DEFAULT 'claimed',"
        " plan_json TEXT NOT NULL DEFAULT '[]',"
        " steps_json TEXT NOT NULL DEFAULT '[]',"
        " waivers_json TEXT NOT NULL DEFAULT '[]',"
        ' superseded_attempt_id INTEGER, heartbeat_at TEXT NOT NULL,'
        ' created_at TEXT NOT NULL)'
    )
    conn.execute(
        "INSERT INTO ticket_execution (ticket_id, workdir, session_id,"
        " status, heartbeat_at, created_at)"
        " VALUES (1, 'w', 's', 'claimed', 't', 't')")
    conn.commit()
    conn.close()
    store = ExecutionStore(Database.connect(legacy), 'w')
    state = store.resume_state(1)
    assert store.evaluations(state['id']) == []  # column present, empty


def test_record_and_read_evaluations(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])
    record = {'trigger': 'manual', 'verdict': 'PASS', 'findings': [],
              'summary': 'clean'}
    store.record_evaluation(attempt['id'], record)
    store.record_evaluation(attempt['id'], {
        'trigger': 'release', 'verdict': 'NEEDS_WORK',
        'findings': [{'file': 'a.py', 'symbol': 'f', 'note': 'n',
                      'severity': 'high'}],
        'summary': 'broken',
    })
    evals = store.evaluations(attempt['id'])
    assert len(evals) == 2
    assert evals[0]['verdict'] == 'PASS'
    assert evals[-1]['findings'][0]['file'] == 'a.py'
    assert evals[-1]['at']  # timestamped


def test_evaluator_cap_is_three(home):
    assert EVALUATOR_CAP == 3


def test_resume_state_renders_latest_needs_work_findings(home, workdir):
    """NEEDS_WORK findings reach the next work prompt: get_resume_state —
    the replacement session's orientation read — renders them."""
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])
    store.record_evaluation(attempt['id'], {
        'trigger': 'release', 'verdict': 'NEEDS_WORK',
        'findings': [{'file': 'src/app.py', 'symbol': 'greet',
                      'note': 'returns wrong value', 'severity': 'high'}],
        'summary': 'one defect',
    })
    rendered = store_tool_resume(store, tid)
    assert 'src/app.py' in rendered and 'greet' in rendered
    assert 'NEEDS_WORK' in rendered


def store_tool_resume(store, ticket_id: int) -> str:
    """The get_resume_state render — the store-level body the tool prints."""
    return store.render_resume(ticket_id)


# --- evaluation cap enforcement + triggers (toolset layer)


def _capturing_evaluator(calls, verdict='PASS'):
    class Cap:
        def __init__(self):
            self.calls = calls

        async def evaluate(self, ticket_id, attempt_id, trigger,
                           step_index=None):
            self.calls.append(
                {'ticket_id': ticket_id, 'attempt_id': attempt_id,
                 'trigger': trigger, 'step_index': step_index})
            return {'trigger': trigger, 'verdict': verdict,
                    'findings': [], 'summary': 'ok'}

    return Cap()


def _toolset_with(store, evaluator, session_id='s1'):
    from codingdude.execution import build_execution_toolset

    return build_execution_toolset(store, session_id, evaluator=evaluator)


async def _call(toolset, name, **args):
    tool = toolset.tools[name]
    return await tool.function(**args)


async def test_release_done_triggers_evaluation(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])
    store.set_step(attempt['id'], 0, 'done', command='pytest -q',
                   exit_code=0, key_output_line='1 passed')
    calls = []
    ts = _toolset_with(store, _capturing_evaluator(calls))
    # register the active claim the way the agent would
    await _call(ts, 'claim_ticket', ticket_id=tid, plan_steps=['step'])
    result = await _call(ts, 'release_ticket', status='done')
    assert calls and calls[0]['trigger'] == 'release'
    assert 'PASS' in result


async def test_milestone_step_completion_triggers_evaluation(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    store.claim(tid, 's1', plan_steps=['[milestone] step'])
    calls = []
    ts = _toolset_with(store, _capturing_evaluator(calls))
    await _call(ts, 'claim_ticket', ticket_id=tid,
                plan_steps=['[milestone] step'])
    await _call(ts, 'update_execution_step', index=0, status='done',
                command='pytest -q', exit_code=0, key_output_line='1 passed')
    assert calls and calls[0]['trigger'] == 'milestone'
    assert calls[0]['step_index'] == 0


async def test_plain_step_completion_does_not_trigger(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    store.claim(tid, 's1', plan_steps=['plain'])
    calls = []
    ts = _toolset_with(store, _capturing_evaluator(calls))
    await _call(ts, 'claim_ticket', ticket_id=tid, plan_steps=['plain'])
    await _call(ts, 'update_execution_step', index=0, status='done',
                command='pytest -q', exit_code=0, key_output_line='1 passed')
    assert calls == []


async def test_no_evaluator_configured_skips_honestly(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])
    store.set_step(attempt['id'], 0, 'done', command='c', exit_code=0,
                   key_output_line='ok')
    ts = _toolset_with(store, None)
    await _call(ts, 'claim_ticket', ticket_id=tid, plan_steps=['step'])
    result = await _call(ts, 'release_ticket', status='done')
    assert 'evaluation skipped' in result


async def test_cap_exhaustion_surfaces_needs_operator(home, workdir):
    """3 passes without PASS → the loop stops: NEEDS_OPERATOR message, the
    state persisted on the attempt, the evaluator not called again."""
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])
    store.set_step(attempt['id'], 0, 'done', command='c', exit_code=0,
                   key_output_line='ok')
    for i in range(EVALUATOR_CAP):
        store.record_evaluation(attempt['id'], {
            'trigger': 'manual', 'verdict': 'NEEDS_WORK',
            'findings': [{'file': 'a.py', 'symbol': None,
                          'note': f'fail {i}', 'severity': 'high'}],
            'summary': f'broken {i}',
        })
    calls = []
    ts = _toolset_with(store, _capturing_evaluator(calls, verdict='NEEDS_WORK'))
    await _call(ts, 'claim_ticket', ticket_id=tid, plan_steps=['step'])
    result = await _call(ts, 'evaluate_work', ticket_id=tid)
    assert calls == []  # cap reached: no further passes run
    assert 'NEEDS_OPERATOR' in result
    persisted = store.evaluations(attempt['id'])
    assert persisted[-1]['verdict'] == 'NEEDS_OPERATOR'


async def test_evaluate_work_tool_runs_manual_pass(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])

    class PersistingCap:
        """Mimics WorkEvaluator: evaluates AND persists the verdict."""

        def __init__(self, calls):
            self.calls = calls
            self.store = store

        async def evaluate(self, ticket_id, attempt_id, trigger,
                           step_index=None):
            self.calls.append(
                {'ticket_id': ticket_id, 'attempt_id': attempt_id,
                 'trigger': trigger, 'step_index': step_index})
            record = {'trigger': trigger, 'verdict': 'PASS',
                      'findings': [], 'summary': 'ok'}
            self.store.record_evaluation(attempt_id, record)
            return record

    calls = []
    ts = _toolset_with(store, PersistingCap(calls))
    await _call(ts, 'claim_ticket', ticket_id=tid, plan_steps=['step'])
    result = await _call(ts, 'evaluate_work', ticket_id=tid)
    assert calls and calls[0]['trigger'] == 'manual'
    assert 'PASS' in result
    assert len(store.evaluations(attempt['id'])) == 1  # verdict persisted


async def test_release_passes_verdict_through_result(home, workdir):
    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])
    store.set_step(attempt['id'], 0, 'done', command='c', exit_code=0,
                   key_output_line='ok')
    calls = []
    ts = _toolset_with(
        store, _capturing_evaluator(calls, verdict='NEEDS_WORK'))
    await _call(ts, 'claim_ticket', ticket_id=tid, plan_steps=['step'])
    result = await _call(ts, 'release_ticket', status='done')
    # non-blocking until the long-run flag lands — but the verdict is loud
    assert 'NEEDS_WORK' in result


# --- WorkEvaluator: read-only delegate with a structured verdict tool


def _verdict_model(verdict='NEEDS_WORK', file='src/app.py', symbol='greet'):
    """Scripted evaluator model: calls submit_verdict on its first turn."""

    def fn(messages, info):
        if not any(
            isinstance(p, ToolCallPart) for m in messages for p in m.parts
        ):
            return ModelResponse(parts=[ToolCallPart(
                tool_name='submit_verdict',
                args={'verdict': verdict,
                      'findings': [{'file': file, 'symbol': symbol,
                                    'note': 'wrong return', 'severity': 'high'}],
                      'summary': 'one defect found'},
            )])
        return ModelResponse(parts=[TextPart(content='verdict submitted')])

    return scripted(fn)


async def test_work_evaluator_persists_verdict(home, workdir, monkeypatch):
    from codingdude.evaluator import WorkEvaluator

    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])
    evaluator = WorkEvaluator(
        db=Database.connect(home), workdir=workdir,
        model=_verdict_model(), db_session='s1',
    )
    record = await evaluator.evaluate(tid, attempt['id'], trigger='release')
    assert record['verdict'] == 'NEEDS_WORK'
    assert record['findings'][0]['file'] == 'src/app.py'
    assert record['findings'][0]['symbol'] == 'greet'
    assert record['trigger'] == 'release'
    persisted = store.evaluations(attempt['id'])
    assert len(persisted) == 1 and persisted[0]['verdict'] == 'NEEDS_WORK'


async def test_work_evaluator_without_verdict_is_needs_work(
        home, workdir, monkeypatch):
    """Skeptical default: an evaluator session that never submits a verdict
    is recorded as NEEDS_WORK, never as a silent PASS."""
    from codingdude.evaluator import WorkEvaluator

    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])

    def silent(messages, info):
        return ModelResponse(parts=[TextPart(content='looks fine to me')])

    evaluator = WorkEvaluator(
        db=Database.connect(home), workdir=workdir,
        model=scripted(silent), db_session='s1',
    )
    record = await evaluator.evaluate(tid, attempt['id'], trigger='release')
    assert record['verdict'] == 'NEEDS_WORK'
    assert 'no verdict' in record['summary'].lower()


def _prompt_text(messages) -> str:
    """The user-prompt text of the evaluator session (UserPromptPart)."""
    from pydantic_ai.messages import UserPromptPart

    return ' '.join(
        str(p.content)
        for m in messages
        for p in m.parts
        if isinstance(p, UserPromptPart)
    )


async def test_work_evaluator_carries_contract_and_diff(
        home, workdir, monkeypatch):
    """The evaluator session sees the ticket contract, the step evidence,
    and the work diff — the anchors it grades against."""
    from codingdude.evaluator import WorkEvaluator

    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['step'])
    store.set_step(attempt['id'], 0, 'done', command='pytest -q',
                   exit_code=0, key_output_line='1 passed')
    _init_repo(workdir)
    (workdir / 'app.py').write_text('def greet():\n    return "bye"\n')

    seen = {}

    def fn(messages, info):
        if not any(
            isinstance(p, ToolCallPart) for m in messages for p in m.parts
        ):
            seen['prompt'] = _prompt_text(messages)
            return ModelResponse(parts=[ToolCallPart(
                tool_name='submit_verdict',
                args={'verdict': 'PASS', 'findings': [], 'summary': 'ok'},
            )])
        return ModelResponse(parts=[TextPart(content='done')])

    evaluator = WorkEvaluator(
        db=Database.connect(home), workdir=workdir,
        model=scripted(fn), db_session='s1',
    )
    await evaluator.evaluate(tid, attempt['id'], trigger='release')
    prompt = seen['prompt']
    assert 'eval ticket' in prompt          # the ticket contract
    assert 'pytest -q' in prompt            # the step evidence
    assert 'greet' in prompt                # the work diff


def test_evaluator_model_resolution_chain():
    """Chain (today): subagent → main; the registry profile re-points it
    in #299. None from both = no evaluator (honest skip upstream)."""
    from codingdude.evaluator import resolve_evaluator_model

    assert resolve_evaluator_model('sub', 'main-model') == 'sub'
    assert resolve_evaluator_model(None, 'main-model') == 'main-model'
    assert resolve_evaluator_model(None, None) is None


# --- replay-eval pipeline (seeded defect; live-model M2 calibration pending)


async def test_replay_eval_flags_seeded_defect(home, workdir):
    """Pipeline correctness: a seeded defective diff is graded NEEDS_WORK
    with the defective file named. (Live-model calibration of the ≥4/5 M2
    rate is a separate run against a real evaluator model.)"""
    from codingdude.evaluator import WorkEvaluator

    store = _store(home, workdir)
    tid = _ticket(home, workdir)
    attempt = store.claim(tid, 's1', plan_steps=['fix greet'])
    _init_repo(workdir)
    (workdir / 'app.py').write_text('def greet():\n    return "WRONG"\n')

    def grader(messages, info):
        if not any(
            isinstance(p, ToolCallPart) for m in messages for p in m.parts
        ):
            text = _prompt_text(messages)
            flagged = 'WRONG' in text and 'app.py' in text
            return ModelResponse(parts=[ToolCallPart(
                tool_name='submit_verdict',
                args={'verdict': 'NEEDS_WORK' if flagged else 'PASS',
                      'findings': (
                          [{'file': 'app.py', 'symbol': 'greet',
                            'note': 'seeded defect visible in diff',
                            'severity': 'high'}] if flagged else []),
                      'summary': 'seeded defect flagged' if flagged
                      else 'clean'},
            )])
        return ModelResponse(parts=[TextPart(content='done')])

    evaluator = WorkEvaluator(
        db=Database.connect(home), workdir=workdir,
        model=scripted(grader), db_session='s1',
    )
    record = await evaluator.evaluate(tid, attempt['id'], trigger='release')
    assert record['verdict'] == 'NEEDS_WORK'
    assert record['findings'][0]['file'] == 'app.py'
    assert record['findings'][0]['symbol'] == 'greet'
