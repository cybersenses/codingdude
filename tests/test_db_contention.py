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
"""R57 / #223 — lock-contention regression harness.

Three properties the store must hold when server, worker, CLI and eval
processes write the same database at the same time. Each test asserts the
user-visible symptom ("database is locked" / a wedged store), never an
implementation detail, and each is deterministic and sub-second.

Diagnosis (`.scratch/db_contention.py`, `.scratch/db_minimise.py`): a write that
raises never rolls back, so the connection keeps the SQLite write lock and
every other writer waits out `busy_timeout` (15 s) and then fails with
`sqlite3.OperationalError: database is locked`.
"""

import sqlite3
import threading

import pytest

from codingdude.db import Database

THREADS = 4
ITERS = 20


def _race(db: Database, fn) -> list[str]:
    """Run `fn(i)` on THREADS threads released together; return failures."""
    errors: list[str] = []
    guard = threading.Lock()
    gate = threading.Barrier(THREADS)

    def worker(i: int) -> None:
        gate.wait()
        for _ in range(ITERS):
            try:
                fn(i)
            except Exception as exc:  # noqa: BLE001 - the failure *is* the signal
                with guard:
                    errors.append(f'{type(exc).__name__}: {exc}')
                return

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sorted(set(errors))


def test_failed_write_does_not_wedge_the_database(home, tmp_path):
    """A rejected write must not leave the write lock held by this connection.

    Observed before the fix: the failed INSERT stays in an open transaction,
    so every other process waits out busy_timeout and reports 'database is
    locked' — the reported lockup.
    """
    writer = Database.connect(home)
    other = Database.connect(home)
    workdir = tmp_path / 'project'
    writer.create_project('project', workdir)

    with pytest.raises(sqlite3.IntegrityError):
        writer.create_project('duplicate', workdir)   # UNIQUE (projects.workdir)

    assert writer._conn.in_transaction is False, (
        'a failed write left an open transaction holding the write lock'
    )

    # Do not pay the production 15 s busy_timeout: the question is whether the
    # lock is held at all, not how long this connection agrees to wait for it.
    other._conn.execute('PRAGMA busy_timeout=200')
    assert other.create_project('other', tmp_path / 'other') > 0


def test_concurrent_message_appends_do_not_collide(home):
    """MAX(seq)+1 must allocate uniquely under concurrent writers.

    Server (user turn) and worker (assistant turn) append to the same session
    from different processes; a read-then-insert hands both the same seq.
    """
    seed = Database.connect(home)
    sid = seed.create_session(home, 'race')
    writers = [Database.connect(home) for _ in range(THREADS)]

    errors = _race(None, lambda i: writers[i].append_messages(sid, '{"m":1}'))
    assert errors == [], f'concurrent appends failed: {errors}'

    rows = seed._conn.execute(
        'SELECT COUNT(*) FROM messages WHERE session_id = ?', (sid,)
    ).fetchone()[0]
    assert rows == THREADS * ITERS


def test_one_database_shared_by_threads_stays_consistent(home):
    """The server serves requests from threadpool threads on one connection.

    A single sqlite3 connection is not a thread-safe transaction boundary:
    interleaved statements raise 'cannot start a transaction within a
    transaction' and commit each other's half-written work.
    """
    db = Database.connect(home)
    sid = db.create_session(home, 'threads')

    errors = _race(db, lambda i: db.record_usage(sid, model=f'm{i}', requests=1))
    assert errors == [], f'shared connection failed under threads: {errors}'

    total = db._conn.execute(
        'SELECT COUNT(*) FROM usage WHERE session_id = ?', (sid,)
    ).fetchone()[0]
    assert total == THREADS * ITERS
