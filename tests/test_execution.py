"""R9 tracer: crash-safe ticket execution claims (tests/test_execution.py)."""

import json
import time

import pytest

from codingdude.db import Database
from codingdude.execution import ExecutionStore, build_execution_toolset


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
    store.set_step(a['id'], 0, 'done', evidence='3 passed, ruff clean')
    state = store.resume_state(ticket)
    steps = json.loads(state['steps_json'])
    assert steps[0] == {
        'text': 'write test', 'status': 'done', 'evidence': '3 passed, ruff clean',
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


def test_resume_state_none_for_unknown_ticket(store):
    assert store.resume_state(999) is None


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
    assert 'done' in (await step(0, 'done', evidence='tests green'))
    assert 'ok' in (await tools['heartbeat_claim'].function()).lower()
    resume = tools['get_resume_state'].function
    state = await resume(ticket)
    assert 's1' in state and 'tests green' in state
    release = tools['release_ticket'].function
    assert 'done' in (await release('done')).lower()


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
            'get_resume_state', 'heartbeat_claim'} <= names
