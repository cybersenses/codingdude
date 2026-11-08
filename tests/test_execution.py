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
"""R9 tracer: crash-safe ticket execution claims (tests/test_execution.py)."""

import json
import time

import pytest

from codingdude.db import Database
from codingdude.execution import EvidenceError, ExecutionStore, build_execution_toolset


@pytest.fixture()
def db(tmp_path):
    return Database.connect(tmp_path)


@pytest.fixture()
def workdir(tmp_path):
    d = tmp_path / 'proj'
    d.mkdir()
    return str(d)


@pytest.fixture()
def store(db, workdir):
    return ExecutionStore(db, workdir)


@pytest.fixture()
def ticket(db, workdir):
    from codingdude.roadmap import RoadmapStore

    tid = RoadmapStore(db).create_ticket(workdir, 'do the thing')
    assert tid is not None
    return tid


def test_claim_creates_attempt_and_reuses_for_same_session(store, ticket):
    a1 = store.claim(ticket, 's1', plan_steps=['step a', 'step b'])
    assert a1['status'] == 'claimed'
    assert a1['ticket_id'] == ticket
    assert a1['session_id'] == 's1'
    assert json.loads(a1['plan_json']) == ['step a', 'step b']
    # Idempotent: same session reclaims its own attempt, no duplicate row.
    a2 = store.claim(ticket, 's1')
    assert a2['id'] == a1['id']


def test_conflicting_fresh_claim_names_the_holder(store, ticket):
    store.claim(ticket, 's1')
    with pytest.raises(ValueError, match='s1'):
        store.claim(ticket, 's2')


def test_stale_claim_is_marked_stale_and_reclaimable(db, workdir, ticket):
    short = ExecutionStore(db, workdir, stale_after_s=0)
    old = short.claim(ticket, 's1')
    time.sleep(0.01)
    fresh = short.claim(ticket, 's2')
    assert short.attempts(ticket)[0]['status'] == 'stale'
    assert fresh['id'] != old['id']
    assert fresh['session_id'] == 's2'
    assert short.resume_state(ticket)['id'] == fresh['id']


def test_set_step_updates_step_evidence_and_ticket_status(store, db, workdir, ticket):
    a = store.claim(ticket, 's1', plan_steps=['write test', 'make it pass'])
    store.set_step(
        a['id'], 0, 'done',
        command='uv run pytest -q', exit_code=0, key_output_line='3 passed',
    )
    state = store.resume_state(ticket)
    steps = json.loads(state['steps_json'])
    assert steps[0] == {
        'text': 'write test', 'status': 'done',
        'evidence': {
            'command': 'uv run pytest -q', 'exit_code': 0,
            'key_output_line': '3 passed',
        },
    }
    assert steps[1]['status'] == 'todo'
    tickets = db._conn.execute(
        'SELECT status FROM tickets WHERE id = ?', (ticket,)
    ).fetchone()
    assert tickets['status'] == 'in_progress'
    with pytest.raises(ValueError, match='out of range'):
        store.set_step(a['id'], 5, 'done')


def test_release_done_closes_attempt_and_ticket(store, db, ticket):
    a = store.claim(ticket, 's1')
    store.release(a['id'], 'done')
    assert store.resume_state(ticket)['status'] == 'done'
    row = db._conn.execute(
        'SELECT status FROM tickets WHERE id = ?', (ticket,)
    ).fetchone()
    assert row['status'] == 'done'


def test_drift_flags_done_without_evidence_and_out_of_order(store, ticket):
    """R9 thickener + DE-1: plan diffing — a step claimed 'done' without
    structured evidence, legacy free-text evidence (demoted to unverified),
    and steps completed out of order are surfaced as drift."""
    attempt = store.claim(ticket, 's1', plan_steps=['step a', 'step b', 'step c'])
    assert store.drift(ticket) == {
        'attempt_id': attempt['id'],
        'done_without_evidence': [],
        'unverified_evidence': [],
        'out_of_order': [],
    }
    ev = dict(command='uv run pytest -q', exit_code=0, key_output_line='3 passed')
    store.set_step(attempt['id'], 0, 'done', **ev)
    # The write-time gate rejects unevidenced 'done' steps, so the
    # done-without-evidence state is seeded directly (legacy row shape).
    steps = json.loads(store.resume_state(ticket)['steps_json'])
    steps[1] = {'text': 'step b', 'status': 'done', 'evidence': None}
    store.db._conn.execute(
        'UPDATE ticket_execution SET steps_json = ? WHERE id = ?',
        (json.dumps(steps), attempt['id']),
    )
    store.db._conn.commit()
    store.set_step(attempt['id'], 2, 'done', **ev)  # sequential, evidenced
    drift = store.drift(ticket)
    assert drift['done_without_evidence'] == [1]
    assert drift['unverified_evidence'] == []
    assert drift['out_of_order'] == []

    attempt2 = store.claim(ticket, 's1')
    steps = json.loads(attempt2['steps_json'])
    steps[0] = {'text': 'step a', 'status': 'todo', 'evidence': None}
    steps[2] = {'text': 'step c', 'status': 'done', 'evidence': 'ok'}
    store.db._conn.execute(
        'UPDATE ticket_execution SET steps_json = ? WHERE id = ?',
        (json.dumps(steps), attempt2['id']),
    )
    store.db._conn.commit()
    drift = store.drift(ticket)
    assert drift['out_of_order'] == [1, 2]
    assert drift['done_without_evidence'] == [1]
    assert drift['unverified_evidence'] == [2]  # legacy free text, demoted


def test_done_step_requires_structured_evidence(store, ticket):
    """DE-1 (decision #95, structured-required): a 'done' step without the
    three evidence fields is rejected — narrative assertion is the
    unverifiable class this gate closes."""
    a = store.claim(ticket, 's1', plan_steps=['step a'])
    with pytest.raises(EvidenceError, match=r'step 0.*command'):
        store.set_step(a['id'], 0, 'done')


@pytest.mark.parametrize(
    'command, exit_code, key_output_line',
    [
        (None, None, None),
        ('uv run pytest -q', None, None),
        ('uv run pytest -q', 0, None),
        (None, 0, '3 passed'),
        ('   ', 0, '3 passed'),
        ('uv run pytest -q', 0, '  '),
        ('uv run pytest -q', True, '3 passed'),  # bool is not an exit code
    ],
)
def test_done_step_rejects_partial_evidence(
    store, ticket, command, exit_code, key_output_line,
):
    a = store.claim(ticket, 's1', plan_steps=['step a'])
    with pytest.raises(EvidenceError, match='step 0'):
        store.set_step(
            a['id'], 0, 'done', command=command, exit_code=exit_code,
            key_output_line=key_output_line,
        )
    steps = json.loads(store.resume_state(ticket)['steps_json'])
    assert steps[0]['status'] == 'todo'  # nothing recorded on a rejected step


def test_done_step_accepts_complete_structured_evidence(store, ticket):
    a = store.claim(ticket, 's1', plan_steps=['step a'])
    store.set_step(
        a['id'], 0, 'done',
        command='uv run pytest -q', exit_code=0, key_output_line='3 passed',
    )
    steps = json.loads(store.resume_state(ticket)['steps_json'])
    assert steps[0]['evidence'] == {
        'command': 'uv run pytest -q', 'exit_code': 0,
        'key_output_line': '3 passed',
    }


def test_non_done_step_needs_no_evidence(store, ticket):
    a = store.claim(ticket, 's1', plan_steps=['step a'])
    store.set_step(a['id'], 0, 'todo')
    steps = json.loads(store.resume_state(ticket)['steps_json'])
    assert steps[0]['evidence'] is None


def test_release_done_blocks_on_out_of_order_steps(store, ticket):
    a = store.claim(ticket, 's1', plan_steps=['step a', 'step b', 'step c'])
    ev = dict(command='uv run pytest -q', exit_code=0, key_output_line='3 passed')
    store.set_step(a['id'], 2, 'done', **ev)
    store.set_step(a['id'], 0, 'done', **ev)
    with pytest.raises(EvidenceError, match=r'\[2\]'):
        store.release(a['id'], 'done')
    assert store.resume_state(ticket)['status'] == 'claimed'  # not closed
    # 'released' (steps aside) is never blocked by the gate
    store.release(a['id'], 'released')
    assert store.resume_state(ticket)['status'] == 'released'


def test_release_done_allows_ordered_evidenced_steps(store, ticket):
    a = store.claim(ticket, 's1', plan_steps=['step a', 'step b'])
    ev = dict(command='uv run pytest -q', exit_code=0, key_output_line='3 passed')
    store.set_step(a['id'], 0, 'done', **ev)
    store.set_step(a['id'], 1, 'done', **ev)
    store.release(a['id'], 'done')
    assert store.resume_state(ticket)['status'] == 'done'


def test_waive_drift_unblocks_release_and_is_auditable(store, ticket):
    a = store.claim(ticket, 's1', plan_steps=['step a', 'step b', 'step c'])
    ev = dict(command='uv run pytest -q', exit_code=0, key_output_line='3 passed')
    store.set_step(a['id'], 2, 'done', **ev)  # out-of-order done
    with pytest.raises(EvidenceError):
        store.release(a['id'], 'done')
    waivers = store.waive_drift(
        a['id'], [2], 'reordered during review; diff verified manually',
    )
    assert waivers[0]['indices'] == [2]
    assert waivers[0]['reason'] == 'reordered during review; diff verified manually'
    assert waivers[0]['at']
    store.release(a['id'], 'done')
    row = store.resume_state(ticket)
    assert row['status'] == 'done'
    assert json.loads(row['waivers_json'])[0]['indices'] == [2]


def test_waive_drift_validation(store, ticket):
    a = store.claim(ticket, 's1', plan_steps=['step a'])
    with pytest.raises(ValueError, match='reason'):
        store.waive_drift(a['id'], [0], '   ')
    with pytest.raises(ValueError, match='at least one'):
        store.waive_drift(a['id'], [], 'why')
    with pytest.raises(ValueError, match='not drift-flagged'):
        store.waive_drift(a['id'], [0], 'step 0 is not done')
    with pytest.raises(KeyError):
        store.waive_drift(424242, [0], 'no such attempt')


def test_waive_drift_rejects_repeat_waiver(store, ticket):
    a = store.claim(ticket, 's1', plan_steps=['step a', 'step b'])
    ev = dict(command='uv run pytest -q', exit_code=0, key_output_line='3 passed')
    store.set_step(a['id'], 1, 'done', **ev)  # out-of-order done, stays flagged
    store.waive_drift(a['id'], [1], 'first waiver')
    with pytest.raises(ValueError, match='already waived'):
        store.waive_drift(a['id'], [1], 'second waiver')


def test_legacy_free_text_evidence_is_demoted_to_unverified(store, ticket):
    """Pre-REQ-1 attempts carry free-text evidence strings; the gate demotes
    them to 'unverified' honestly without retroactively failing releases."""
    a = store.claim(ticket, 's1', plan_steps=['step a'])
    steps = json.loads(store.resume_state(ticket)['steps_json'])
    steps[0] = {'text': 'step a', 'status': 'done', 'evidence': 'tests: 3 passed'}
    store.db._conn.execute(
        'UPDATE ticket_execution SET steps_json = ? WHERE id = ?',
        (json.dumps(steps), a['id']),
    )
    store.db._conn.commit()
    drift = store.drift(ticket)
    assert drift['done_without_evidence'] == []
    assert drift['unverified_evidence'] == [0]
    store.release(a['id'], 'done')  # legacy attempts still release


def test_resume_state_none_for_unknown_ticket(store):    assert store.resume_state(999) is None


def test_heartbeat_refreshes(store, ticket):
    a = store.claim(ticket, 's1')
    before = a['heartbeat_at']
    time.sleep(0.01)
    store.heartbeat(a['id'])
    assert store.resume_state(ticket)['heartbeat_at'] > before
    with pytest.raises(KeyError):
        store.heartbeat(424242)


async def test_toolset_round_trip(store, ticket):
    tools = build_execution_toolset(store, 's1').tools
    claim = tools['claim_ticket'].function
    assert 'attempt' in (await claim(ticket, ['a', 'b'])).lower()
    step = tools['update_execution_step'].function
    assert 'done' in (await step(
        0, 'done', command='uv run pytest -q', exit_code=0,
        key_output_line='3 passed',
    )).lower()
    assert 'ok' in (await tools['heartbeat_claim'].function()).lower()
    resume = tools['get_resume_state'].function
    state = await resume(ticket)
    assert 's1' in state and 'uv run pytest -q' in state
    release = tools['release_ticket'].function
    assert 'done' in (await release('done')).lower()


async def test_update_execution_step_reports_evidence_gaps(store, ticket):
    """Tool boundary: an EvidenceError becomes an actionable message, and
    the rejected step is not recorded."""
    tools = build_execution_toolset(store, 's1').tools
    await tools['claim_ticket'].function(ticket, ['step a'])
    out = await tools['update_execution_step'].function(0, 'done')
    assert 'command' in out and 'exit_code' in out and 'key_output_line' in out
    steps = json.loads(store.resume_state(ticket)['steps_json'])
    assert steps[0]['status'] == 'todo'


async def test_release_ticket_reports_blocked_steps(store, ticket):
    """Tool boundary: a gate-blocked 'done' release names the steps and the
    waive path instead of raising into the model loop."""
    tools = build_execution_toolset(store, 's1').tools
    await tools['claim_ticket'].function(ticket, ['step a', 'step b'])
    await tools['update_execution_step'].function(
        1, 'done', command='uv run pytest -q', exit_code=0,
        key_output_line='3 passed',
    )
    out = await tools['release_ticket'].function('done')
    assert '[1]' in out and 'waive_drift' in out


async def test_waive_drift_tool_round_trip(store, ticket):
    tools = build_execution_toolset(store, 's1').tools
    await tools['claim_ticket'].function(ticket, ['step a', 'step b'])
    await tools['update_execution_step'].function(
        1, 'done', command='uv run pytest -q', exit_code=0,
        key_output_line='3 passed',
    )
    out = await tools['waive_drift'].function([1], 'verified in review')
    assert 'waived' in out and '[1]' in out
    assert 'done' in (await tools['release_ticket'].function('done')).lower()


async def test_resume_state_renders_waivers(store, ticket):
    tools = build_execution_toolset(store, 's1').tools
    await tools['claim_ticket'].function(ticket, ['step a', 'step b'])
    await tools['update_execution_step'].function(
        1, 'done', command='uv run pytest -q', exit_code=0,
        key_output_line='3 passed',
    )
    await tools['waive_drift'].function([1], 'verified in review')
    state = await tools['get_resume_state'].function(ticket)
    assert 'waived: steps [1] — verified in review' in state


async def test_wired_into_build_all(tmp_path, monkeypatch):
    """Upstream check: the execution tools reach a real engine toolset."""
    from codingdude.config import Config
    from codingdude.plugins import PluginContext, build_all

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr('codingdude.mcp_config.ensure_default_mcp', lambda *_: None)
    monkeypatch.setattr(
        'codingdude.plugins.merged_mcp_server_names', lambda *_: []
    )
    db = Database.connect(home)
    ctx = PluginContext(
        workdir=tmp_path, config=Config.defaults(), db=db,
        session_id='s9', home=home,
    )
    toolsets = await build_all(ctx)
    names = {t.name for ts in toolsets for t in getattr(ts, 'tools', {}).values()}
    assert {'claim_ticket', 'update_execution_step', 'release_ticket',
            'get_resume_state', 'heartbeat_claim', 'waive_drift'} <= names


# --- DE-4 (#294): death-verified takeover + step inheritance ---

_EVIDENCE = dict(command='uv run pytest -q', exit_code=0, key_output_line='3 passed')


def _seed_run(db, session_id: str, status: str) -> None:
    db.record_run_start(f'run-{session_id}', session_id)
    if status != 'running':
        db.record_run_end(f'run-{session_id}', status)


@pytest.mark.parametrize('terminal', ['completed', 'failed', 'gate_aborted', 'interrupted'])
def test_takeover_when_holder_run_verifiably_dead(
    store, db, ticket, terminal,
):
    """A blocking attempt whose session's newest run is terminal (worker
    finish, reaper, boot reconcile) is taken over immediately — no 900s
    staleness wait — and the new attempt inherits the whole record."""
    old = store.claim(ticket, 'dead1', plan_steps=['step a', 'step b'])
    store.set_step(old['id'], 0, 'done', **_EVIDENCE)
    _seed_run(db, 'dead1', terminal)

    fresh = store.claim(ticket, 's2', plan_steps=['step a', 'step b'])

    assert fresh['id'] != old['id']
    assert fresh['session_id'] == 's2'
    assert fresh['superseded_attempt_id'] == old['id']
    assert store.attempts(ticket)[0]['status'] == 'stale'
    assert json.loads(fresh['plan_json']) == ['step a', 'step b']
    steps = json.loads(fresh['steps_json'])
    assert steps[0] == {
        'text': 'step a', 'status': 'done', 'evidence': dict(_EVIDENCE),
    }
    assert steps[1]['status'] == 'todo'
    # the inherited record is visible to the gate seams, not just stored
    drift = store.drift(ticket)
    assert drift['attempt_id'] == fresh['id']
    assert drift['done_without_evidence'] == []


def test_takeover_carries_waivers(store, db, ticket):
    """#293 heads-up: inheritance must carry waivers_json — a waived step on
    the superseded attempt must not re-block release on the new one."""
    old = store.claim(ticket, 'dead1', plan_steps=['step a', 'step b'])
    store.set_step(old['id'], 1, 'done', **_EVIDENCE)  # out of order
    store.waive_drift(old['id'], [1], 'verified in review')
    _seed_run(db, 'dead1', 'interrupted')

    fresh = store.claim(ticket, 's2', plan_steps=['step a', 'step b'])

    assert store.waivers(ticket) == [
        {'indices': [1], 'reason': 'verified in review',
         'at': store.waivers(ticket)[0]['at']},
    ]
    store.set_step(fresh['id'], 0, 'done', **_EVIDENCE)
    store.release(fresh['id'], 'done')  # inherited waiver keeps the gate open


def test_no_takeover_while_holder_run_is_live(db, workdir, ticket):
    """The misidentified-dead race: heartbeat staleness alone never fires
    the takeover — a session whose newest run row is still 'running' keeps
    its claim (heartbeat lag under load is not death)."""
    short = ExecutionStore(db, workdir, stale_after_s=0)
    old = short.claim(ticket, 's1', plan_steps=['step a'])
    _seed_run(db, 's1', 'running')
    time.sleep(0.01)
    with pytest.raises(ValueError, match='s1'):
        short.claim(ticket, 's2')
    assert short.resume_state(ticket)['id'] == old['id']
    assert short.resume_state(ticket)['status'] == 'claimed'


def test_stale_path_unchanged_no_run_row_no_inheritance(db, workdir, ticket):
    """The legacy 900s staleness path stays as shipped: fresh attempt, empty
    steps, no supersession link — takeover is the death-verified path only."""
    short = ExecutionStore(db, workdir, stale_after_s=0)
    old = short.claim(ticket, 's1', plan_steps=['step a'])
    store_set = ExecutionStore(db, workdir, stale_after_s=0)
    store_set.set_step(old['id'], 0, 'done', **_EVIDENCE)
    time.sleep(0.01)
    fresh = short.claim(ticket, 's2', plan_steps=['step a'])
    assert fresh['superseded_attempt_id'] is None
    assert json.loads(fresh['steps_json'])[0]['status'] == 'todo'
    assert short.attempts(ticket)[0]['status'] == 'stale'


def test_interrupted_discovers_dead_session_claims(store, db, workdir, ticket):
    """Discovery seam (DE-4): claimed attempts in this workdir whose
    session's newest run is terminal, with the resume anchors the bootstrap
    renders into the first turn."""
    from codingdude.roadmap import RoadmapStore

    dead = store.claim(ticket, 'dead1', plan_steps=['step a', 'step b'])
    store.set_step(dead['id'], 0, 'done', **_EVIDENCE)
    _seed_run(db, 'dead1', 'interrupted')

    other = RoadmapStore(db).create_ticket(workdir, 'live work')
    store.claim(other, 'live1', plan_steps=['x'])
    _seed_run(db, 'live1', 'running')  # live session: not interrupted

    found = store.interrupted()
    assert [a['ticket_id'] for a in found] == [ticket]
    row = found[0]
    assert row['attempt_id'] == dead['id']
    assert row['session_id'] == 'dead1'
    assert row['run_status'] == 'interrupted'
    assert row['done_count'] == 1
    assert row['next_step_index'] == 1
