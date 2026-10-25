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
"""Database: schema created on first use, sessions and messages roundtrip."""

import sqlite3
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.db import Database, _Connection
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


def test_load_messages_limit_returns_most_recent_in_order(home, workdir):
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    for i in range(5):
        db.append_messages(
            session_id, encode_messages([ModelResponse(parts=[TextPart(content=f'msg {i}')])])
        )
    loaded = decode_messages(db.load_messages(session_id, limit=2))
    assert [p.content for m in loaded for p in m.parts] == ['msg 3', 'msg 4']


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


def test_keep_for_evals_mark_roundtrip(home, workdir):
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    sessions = db.list_sessions(workdir)
    assert next(s for s in sessions if s.session_id == session_id).keep_for_evals is False
    db.set_keep_for_evals(session_id, True)
    assert db.list_sessions(workdir)[0].keep_for_evals is True
    db.set_keep_for_evals(session_id, False)
    assert db.list_sessions(workdir)[0].keep_for_evals is False


def test_session_notes_add_and_chronological_list(home, workdir):
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    db.add_session_note(session_id, 'went off the rails here', run_id='r1', offset_s=12.5)
    db.add_session_note(session_id, 'clever fix')
    notes = db.list_session_notes(session_id)
    assert [n['content'] for n in notes] == ['went off the rails here', 'clever fix']
    assert notes[0]['run_id'] == 'r1'
    assert notes[0]['offset_s'] == 12.5
    assert notes[1]['run_id'] is None
    assert notes[1]['offset_s'] is None
    assert notes[0]['created_at']
    assert db.list_session_notes('no-such-session') == []


def test_render_records_roundtrip_and_chronological_list(home, workdir):
    """Renders persist per session (R1 gap): recorded on capture, listed
    newest-first with provenance (captured_at), session-scoped."""
    db = Database.connect(home)
    session_id = db.create_session(workdir)
    db.record_render(session_id, 'shots/first.png', bytes_=100, mtime=1000)
    db.record_render(session_id, 'shots/second.png', bytes_=200, mtime=2000)
    renders = db.list_renders(session_id)
    assert [r['path'] for r in renders] == ['shots/second.png', 'shots/first.png']
    assert renders[0]['bytes'] == 200
    assert renders[0]['mtime'] == 2000
    assert renders[0]['captured_at']
    assert db.list_renders('no-such-session') == []


def test_delete_session_cascades_all_session_scoped_tables(home, workdir):
    """M6 regression: delete_session must clean every table keyed by
    session_id — the list is derived from the schema, so new tables can't
    be orphaned again."""
    db = Database.connect(home)
    sid = db.create_session(workdir, title='t')
    db.append_messages(sid, '{}')
    db.add_session_note(sid, 'note')
    db.record_render(sid, 'shot.png', 10, 1)
    db.record_pattern_approval(sid, 'git status')
    db.record_usage(sid, model='m', input_tokens=1)
    db._conn.execute(
        "INSERT INTO artifacts (session_id, kind, title, payload_json, status, created_at)"
        " VALUES (?, 'choice', 't', '{}', 'pending', 'x')",
        (sid,),
    )
    db._conn.execute(
        "INSERT INTO ticket_execution"
        " (ticket_id, workdir, session_id, status, plan_json, steps_json,"
        "  heartbeat_at, created_at)"
        " VALUES (1, 'w', ?, 'claimed', '{}', '[]', 'x', 'x')",
        (sid,),
    )
    db._conn.commit()

    db.delete_session(sid)

    orphaned = []
    counters = {
        'messages': 'SELECT COUNT(*) FROM messages WHERE session_id = ?',
        'approvals': 'SELECT COUNT(*) FROM approvals WHERE session_id = ?',
        'usage': 'SELECT COUNT(*) FROM usage WHERE session_id = ?',
        'plans': 'SELECT COUNT(*) FROM plans WHERE session_id = ?',
        'session_notes': 'SELECT COUNT(*) FROM session_notes WHERE session_id = ?',
        'renders': 'SELECT COUNT(*) FROM renders WHERE session_id = ?',
        'artifacts': 'SELECT COUNT(*) FROM artifacts WHERE session_id = ?',
        'ticket_execution': 'SELECT COUNT(*) FROM ticket_execution WHERE session_id = ?',
    }
    for table, query in counters.items():
        n = db._conn.execute(query, (sid,)).fetchone()[0]
        if n:
            orphaned.append(f'{table}={n}')
    assert not orphaned, f'orphaned rows after delete_session: {orphaned}'
    assert db.list_sessions(workdir) == []


def test_busy_timeout_is_15s(home):
    """SQLITE_BUSY contention between server/worker processes gets a 15s
    grace window before raising (intermittent 'database is locked')."""
    db = Database.connect(home)
    timeout = db._conn.execute('PRAGMA busy_timeout').fetchone()[0]
    assert timeout == 15_000


def _flaky_conn(home, fail_times, calls):
    """A real connection whose COMMIT fails `fail_times` times (test seam).

    `_commit_once` is the single attempt, so the retry loop above it stays
    under test; overriding `commit` itself would bypass the code being tested.
    """

    class Flaky(_Connection):
        def _commit_once(self) -> None:
            calls['n'] += 1
            if calls['n'] <= fail_times:
                raise sqlite3.OperationalError('database is locked')
            super()._commit_once()

    conn = sqlite3.connect(home / 'codingdude.db', factory=Flaky)
    conn.row_factory = sqlite3.Row
    return conn


def test_commit_retries_on_database_locked(home, workdir, monkeypatch):
    """A transient SQLITE_BUSY during commit is retried with backoff
    instead of surfacing as 'database is locked' to the run."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    calls = {'n': 0}
    sleeps: list[float] = []

    db._conn = _flaky_conn(home, fail_times=2, calls=calls)
    monkeypatch.setattr('codingdude.db._BACKOFF_BASE', 0.001)
    monkeypatch.setattr('codingdude.db.time.sleep', sleeps.append)

    db.add_session_note(sid, 'written despite lock contention')

    assert calls['n'] == 3  # two failures then success
    assert sleeps == [0.001, 0.002]


def test_commit_gives_up_after_max_retries(home, workdir, monkeypatch):
    """A lock held beyond the retry budget still raises — fails loudly,
    never silently drops the write."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    calls = {'n': 0}

    db._conn = _flaky_conn(home, fail_times=999, calls=calls)
    monkeypatch.setattr('codingdude.db._BACKOFF_BASE', 0.001)
    monkeypatch.setattr('codingdude.db.time.sleep', lambda _s: None)

    with pytest.raises(sqlite3.OperationalError, match='database is locked'):
        db.add_session_note(sid, 'lost write')
    assert calls['n'] == 4  # initial attempt + 3 retries


def test_direct_connection_commit_retries_too(home, workdir, monkeypatch):
    """`db._conn.commit()` — the path 31 store call sites use — also retries.

    Guarding only `Database._commit` left every module that commits through
    the raw connection unprotected, which is where the reported lockup came
    from (R57 review).
    """
    db = Database.connect(home)
    sid = db.create_session(workdir)
    calls = {'n': 0}

    db._conn = _flaky_conn(home, fail_times=2, calls=calls)
    monkeypatch.setattr('codingdude.db._BACKOFF_BASE', 0.001)
    monkeypatch.setattr('codingdude.db.time.sleep', lambda _s: None)

    db._conn.execute(
        "INSERT INTO session_notes (session_id, content, created_at)"
        " VALUES (?, 'direct', 'x')",
        (sid,),
    )
    db._conn.commit()

    assert calls['n'] == 3
    assert db._conn.execute(
        'SELECT COUNT(*) FROM session_notes WHERE session_id = ?', (sid,)
    ).fetchone()[0] == 1


def test_giving_up_on_commit_rolls_the_transaction_back(home, workdir, monkeypatch):
    """A COMMIT that never succeeds must not leave the write lock held.

    A COMMIT returning SQLITE_BUSY leaves the transaction open; without a
    rollback the connection keeps SQLite's write lock for the life of the
    process, which is the reported lockup.
    """
    db = Database.connect(home)
    sid = db.create_session(workdir)
    calls = {'n': 0}

    db._conn = _flaky_conn(home, fail_times=999, calls=calls)
    monkeypatch.setattr('codingdude.db._BACKOFF_BASE', 0.001)
    monkeypatch.setattr('codingdude.db.time.sleep', lambda _s: None)

    db._conn.execute(
        "INSERT INTO session_notes (session_id, content, created_at)"
        " VALUES (?, 'doomed', 'x')",
        (sid,),
    )
    assert db._conn.in_transaction is True  # the rollback has something to undo
    with pytest.raises(sqlite3.OperationalError, match='database is locked'):
        db._conn.commit()

    assert db._conn.in_transaction is False, (
        'a failed COMMIT left an open transaction holding the write lock'
    )


def test_commit_does_not_retry_other_operational_errors(home, workdir, monkeypatch):
    """Only SQLITE_BUSY is retried — a non-lock OperationalError raises on the
    first attempt instead of burning the retry budget on e.g. 'no such table',
    whose outcome cannot change; each lock-blocked attempt can additionally
    wait out the 15 s busy_timeout, so a full budget is a ~60 s hang."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    calls = {'n': 0}

    class Broken(_Connection):
        def _commit_once(self) -> None:
            calls['n'] += 1
            raise sqlite3.OperationalError('no such table: nope')

    db._conn = sqlite3.connect(home / 'codingdude.db', factory=Broken)
    db._conn.row_factory = sqlite3.Row
    db._conn.execute(
        "INSERT INTO session_notes (session_id, content, created_at)"
        " VALUES (?, 'x', 'x')",
        (sid,),
    )
    monkeypatch.setattr('codingdude.db._BACKOFF_BASE', 0.001)

    with pytest.raises(sqlite3.OperationalError, match='no such table'):
        db._conn.commit()
    assert calls['n'] == 1  # no retries for non-lock errors


def _interrupting_conn(home) -> _Connection:
    """A real connection whose COMMIT is interrupted rather than locked."""

    class Interrupted(_Connection):
        def _commit_once(self) -> None:
            raise KeyboardInterrupt

    conn = sqlite3.connect(home / 'codingdude.db', factory=Interrupted)
    conn.row_factory = sqlite3.Row
    return conn


def test_interrupted_commit_rolls_the_transaction_back(home, workdir):
    """A Ctrl-C mid-COMMIT must not leave the write lock behind either.

    COMMIT can block for the full busy_timeout, which is exactly when an
    interrupt arrives, so `commit` needs the same BaseException invariant
    the statement shims already enforce (R57 review).
    """
    db = Database.connect(home)
    sid = db.create_session(workdir)

    db._conn = _interrupting_conn(home)
    db._conn.execute(
        "INSERT INTO session_notes (session_id, content, created_at)"
        " VALUES (?, 'abandoned', 'x')",
        (sid,),
    )
    assert db._conn.in_transaction is True  # the rollback has something to undo
    with pytest.raises(KeyboardInterrupt):
        db._conn.commit()

    assert db._conn.in_transaction is False, (
        'an interrupted COMMIT left an open transaction holding the write lock'
    )


def test_interrupt_during_backoff_sleep_rolls_back(home, workdir, monkeypatch):
    """The interrupt can also land in the sleep between retries.

    That is why the rollback wraps the whole retry loop instead of each
    attempt: an exception raised inside the handler would otherwise escape
    with the write still locked.
    """
    db = Database.connect(home)
    sid = db.create_session(workdir)
    calls = {'n': 0}

    db._conn = _flaky_conn(home, fail_times=999, calls=calls)
    db._conn.execute(
        "INSERT INTO session_notes (session_id, content, created_at)"
        " VALUES (?, 'abandoned', 'x')",
        (sid,),
    )
    assert db._conn.in_transaction is True  # the rollback has something to undo

    def interrupted_sleep(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr('codingdude.db.time.sleep', interrupted_sleep)

    with pytest.raises(KeyboardInterrupt):
        db._conn.commit()

    assert calls['n'] == 1  # gave up on the sleep, not on the budget
    assert db._conn.in_transaction is False


def test_wal_autocheckpoint_is_bounded(home):
    """#238: passive autocheckpoint runs every 256 pages (~1 MB) instead of
    SQLite's 1000-page (~4 MB) default, so the WAL stays cheap to rewind."""
    db = Database.connect(home)
    pages = db._conn.execute('PRAGMA wal_autocheckpoint').fetchone()[0]
    assert pages == 256


def test_checkpoint_idle_truncates_when_wal_exceeds_threshold(home, workdir):
    """#238: an explicit TRUNCATE checkpoint on idle bounds the WAL even when
    passive autocheckpoint was starved by long-lived readers."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    for _ in range(20):
        db._conn.execute(
            "INSERT INTO session_notes (session_id, content, created_at)"
            " VALUES (?, ?, 'x')",
            (sid, 'x' * 400),
        )
        db._conn.commit()
    wal = home / 'codingdude.db-wal'
    assert wal.exists() and wal.stat().st_size > 0

    result = db.checkpoint_idle(threshold_bytes=1)

    assert result['ran'] is True
    assert result['busy'] == 0
    assert wal.stat().st_size == 0, 'WAL was not truncated'


def test_checkpoint_idle_skips_below_threshold(home, workdir):
    """#238: the idle checkpoint is a no-op while the WAL is under the soft
    threshold — every sweep must not pay a checkpoint."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    db.add_session_note(sid, 'tiny')

    result = db.checkpoint_idle(threshold_bytes=64 * 1024 * 1024)

    assert result['ran'] is False
    assert result['busy'] == 0  # the key exists even on the skip branch
    assert 'wal_bytes' in result


def test_checkpoint_idle_survives_busy_readers(home, workdir):
    """#238: a reader pinning the WAL makes TRUNCATE return busy — that must
    surface in the result, not raise into the janitor loop. The attempt also
    runs under a short busy_timeout so a held write lock cannot stall a sweep."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    db._conn.execute(
        "INSERT INTO session_notes (session_id, content, created_at)"
        " VALUES (?, ?, 'x')",
        (sid, 'x' * 400),
    )
    db._conn.commit()
    reader = sqlite3.connect(home / 'codingdude.db')
    reader.execute('BEGIN')
    reader.execute('SELECT COUNT(*) FROM session_notes').fetchone()

    result = db.checkpoint_idle(threshold_bytes=1)  # must not raise

    assert result['ran'] is True
    assert result['busy'] == 1
    reader.close()


def test_run_lifecycle_start_then_end(home, workdir):
    """R31: runs are persisted so run end-state survives a server bounce."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    db.record_run_start('runA', sid, pid=4242)
    row = db.get_run('runA')
    assert row['status'] == 'running'
    assert row['session_id'] == sid
    assert row['worker_pid'] == 4242
    db.record_run_end('runA', 'completed')
    assert db.get_run('runA')['status'] == 'completed'


def test_run_end_status_variants(home, workdir):
    db = Database.connect(home)
    sid = db.create_session(workdir)
    db.record_run_start('runB', sid, pid=1)
    db.record_run_end('runB', 'failed', exit_code=1)
    assert db.get_run('runB')['status'] == 'failed'
    assert db.get_run('runB')['exit_code'] == 1


def test_reconcile_marks_orphaned_running_runs_interrupted(home, workdir):
    """A run still 'running' after a server restart can never finish — it is
    interrupted by definition. Reconcile makes that end-state durable."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    db.record_run_start('runLive', sid, pid=1)
    db.record_run_start('runDone', sid, pid=2)
    db.record_run_end('runDone', 'completed')
    assert db.reconcile_interrupted_runs() == 1
    assert db.get_run('runLive')['status'] == 'interrupted'
    assert db.get_run('runDone')['status'] == 'completed'
    assert db.reconcile_interrupted_runs() == 0  # idempotent


def test_reconcile_dead_processes_marks_orphaned_running_rows(home, workdir, monkeypatch):
    """#148 follow-up: process rows stuck at 'running' whose pid no longer
    exists get a durable 'exited (no capture)' end state at server boot —
    not just lazily when list_processes happens to be called."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    db.record_process(sid, pid=4242, command='gone', started_at='t', status='running')
    db.record_process(sid, pid=4243, command='gone-bg', started_at='t',
                      status='running', background=True)
    db.record_process(sid, pid=1, command='alive', started_at='t', status='running')
    monkeypatch.setattr(
        'codingdude.processes._pid_alive', lambda pid: pid not in (4242, 4243))

    assert db.reconcile_dead_processes() == 2
    rows = {r['pid']: r for r in db.list_processes(sid)}
    assert rows[4242]['status'] == 'exited (no capture)'
    assert rows[4243]['status'] == 'exited (no capture)'
    assert rows[4243]['background'] is True  # sweep must not drop the flag
    assert rows[1]['status'] == 'running'
    assert db.reconcile_dead_processes() == 0  # idempotent


def test_list_runs_newest_first_scoped_to_session(home, workdir):
    """#77: the UI run-output view lists a session's recent runs."""
    db = Database.connect(home)
    sid = db.create_session(workdir)
    other = db.create_session(workdir / 'other')
    db.record_run_start('run1', sid, pid=1)
    db.record_run_end('run1', 'completed', exit_code=0)
    db.record_run_start('run2', sid, pid=2)
    db.record_run_start('run3', other, pid=3)
    runs = db.list_runs(sid)
    assert [r['run_id'] for r in runs] == ['run2', 'run1']
    assert runs[1]['status'] == 'completed'
    assert runs[1]['exit_code'] == 0
    assert runs[0]['status'] == 'running'
