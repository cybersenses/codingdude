"""Database: schema created on first use, sessions and messages roundtrip."""

from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.db import Database
from codingdude.messages import decode_messages, encode_messages


def test_schema_created_on_first_use(home):
    assert not (home / 'codingdude.db').exists()
    db = Database.connect(home)
    assert (home / 'codingdude.db').exists()
    assert db.list_sessions(Path('/nowhere')) == []


def test_session_create_list_and_message_roundtrip(home, workdir):
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    assert session_id in [s.session_id for s in db.list_sessions(workdir)]

    messages = encode_messages(
        [ModelResponse(parts=[TextPart(content='hello bank')])]
    )
    db.append_messages(session_id, messages)
    loaded = decode_messages(db.load_messages(session_id))
    assert [p.content for m in loaded for p in m.parts] == ['hello bank']


def test_usage_accumulates_per_session(home, workdir):
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    db.record_usage(session_id, model='m1', input_tokens=10, output_tokens=5, cost_usd=0.01)
    db.record_usage(session_id, model='m1', input_tokens=1, output_tokens=2, cost_usd=0.02)
    totals = db.session_usage(session_id)
    assert totals['input_tokens'] == 11
    assert totals['output_tokens'] == 7
    assert abs(totals['cost_usd'] - 0.03) < 1e-9


def test_session_usage_includes_per_model_breakdown(home, workdir):
    """R10 thickener: the Cost tab needs a per-model split, not just totals."""
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    db.record_usage(session_id, model='m1', requests=1, input_tokens=10, output_tokens=5, cost_usd=0.01)
    db.record_usage(session_id, model='m2', requests=1, input_tokens=1, output_tokens=2, cost_usd=0.02)
    db.record_usage(session_id, model='m1', requests=1, input_tokens=1, output_tokens=2, cost_usd=None)
    by_model = {row['model']: row for row in db.session_usage(session_id)['by_model']}
    assert set(by_model) == {'m1', 'm2'}
    assert by_model['m1']['requests'] == 2
    assert by_model['m1']['input_tokens'] == 11
    assert by_model['m1']['cost_usd'] == pytest.approx(0.01)
    assert by_model['m2']['requests'] == 1
    assert by_model['m2']['output_tokens'] == 2


def test_session_usage_includes_per_request_breakdown(home, workdir):
    """R10 thickener: per-request rows (one per run/aux call) in chronological
    order, so the Cost tab can show where in the session spend happened."""
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    db.record_usage(session_id, model='m1', requests=3, input_tokens=10, output_tokens=5, cost_usd=0.01)
    db.record_usage(session_id, model='m2', requests=1, input_tokens=1, output_tokens=2, cost_usd=0.02)
    by_request = db.session_usage(session_id)['by_request']
    assert [r['model'] for r in by_request] == ['m1', 'm2']
    assert by_request[0]['requests'] == 3
    assert by_request[1]['cost_usd'] == pytest.approx(0.02)
    assert all('created_at' in r for r in by_request)


def test_context_snapshot_roundtrip_and_migration(home, workdir):
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    db.update_session_context(session_id, total_tokens=96_000, model_limit=128_000)
    sessions = db.list_sessions(workdir)
    info = next(s for s in sessions if s.session_id == session_id)
    assert info.context_tokens == 96_000
    assert info.context_limit == 128_000


def test_context_columns_added_to_legacy_database(home, workdir):
    """A sessions table created before R3 gains the context columns in place."""
    db = Database.connect(home)
    # Simulate a legacy DB by dropping the columns via table rebuild.
    db._conn.executescript(
        """
        CREATE TABLE sessions_legacy (session_id TEXT PRIMARY KEY,
            workdir TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, title TEXT);
        DROP TABLE sessions;
        ALTER TABLE sessions_legacy RENAME TO sessions;
        """
    )
    db._conn.commit()
    db2 = Database.connect(home)
    session_id = db2.create_session(workdir)
    db2.update_session_context(session_id, 1000, 2000)
    info = db2.list_sessions(workdir)[0]
    assert (info.context_tokens, info.context_limit) == (1000, 2000)
