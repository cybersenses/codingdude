"""Database: schema created on first use, sessions and messages roundtrip."""

from pathlib import Path

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
