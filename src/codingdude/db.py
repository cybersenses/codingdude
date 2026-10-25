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
"""SQLite persistence for Sessions, messages, approvals, Memory, and usage."""

import logging
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    workdir TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT,
    context_tokens INTEGER,
    context_limit INTEGER,
    keep_for_evals INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    seq INTEGER NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE TABLE IF NOT EXISTS session_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    run_id TEXT,
    offset_s REAL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    tool_name TEXT NOT NULL,
    args TEXT NOT NULL,
    pattern TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL CHECK (scope IN ('global', 'workdir')),
    workdir TEXT,
    content TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'fact' CHECK (kind IN ('fact', 'solution')),
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    model TEXT NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    path TEXT NOT NULL,
    workdir TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    vector TEXT NOT NULL,
    PRIMARY KEY (path, workdir)
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    goal TEXT NOT NULL,
    steps TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    workdir TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roadmap_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done')),
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done')),
    body TEXT NOT NULL DEFAULT '',
    blocked_by TEXT,
    roadmap_id TEXT,
    commit_sha TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_execution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    workdir TEXT NOT NULL,
    session_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'claimed'
        CHECK (status IN ('claimed', 'released', 'done', 'stale')),
    plan_json TEXT NOT NULL DEFAULT '[]',
    steps_json TEXT NOT NULL DEFAULT '[]',
    heartbeat_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    path TEXT NOT NULL,
    heading TEXT NOT NULL,
    content TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ref_sections ON reference_sections (workdir, path);
CREATE TABLE IF NOT EXISTS reference_meta (
    workdir TEXT NOT NULL,
    path TEXT NOT NULL,
    version TEXT,
    mtime TEXT NOT NULL,
    size INTEGER NOT NULL,
    PRIMARY KEY (workdir, path)
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    response_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts ON artifacts (session_id, created_at);
CREATE TABLE IF NOT EXISTS renders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    path TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    pid INTEGER NOT NULL,
    command TEXT NOT NULL,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    exit_code INTEGER,
    background INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_processes ON processes (session_id, id);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    worker_pid INTEGER,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'gate_aborted', 'interrupted')),
    exit_code INTEGER,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs ON runs (session_id, started_at);
CREATE TABLE IF NOT EXISTS gh_mirror (
    workdir TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ticket', 'roadmap')),
    local_id TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workdir, kind, local_id)
);
CREATE TABLE IF NOT EXISTS design_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'sunset')),
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tech_designs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'superseded')),
    body TEXT NOT NULL DEFAULT '',
    prd_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string; the canonical timestamp
    format for every persisted row."""
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class SessionInfo:
    """Immutable view of one session row (id, workdir, timestamps, title)."""
    session_id: str
    workdir: str
    created_at: str
    updated_at: str
    title: str | None
    context_tokens: int | None = None
    context_limit: int | None = None
    keep_for_evals: bool = False


# SQLITE_BUSY retry budget: server and worker processes share the DB file, so a
# transient lock (busy_timeout exceeded) is retried instead of surfacing as
# 'database is locked' to the run. After the last attempt it fails loudly.
_BUSY_RETRIES = 3
_BACKOFF_BASE = 0.05


class _Connection(sqlite3.Connection):
    """A connection that never leaves a failed write holding the write lock.

    Python's sqlite3 opens a transaction before DML but does not roll it back
    when a statement raises, so the doomed transaction keeps SQLite's write
    lock and every other writer waits out `busy_timeout` and then fails with
    'database is locked' (R57). Rolling back one level below every caller
    keeps the invariant in one place instead of at each of the 45 statements
    in `db.py` and the 58 in the eight store modules that use `db._conn`
    directly (`artifacts`, `execution`, `memory`, `planning`, `projectnotes`,
    `references`, `roadmap`, `semantic`) — 58 by the `db._conn` attribute
    path alone; six more in `references.py` reach the same connection
    through a local alias and are counted with the commit sites below.

    `commit` is guarded for the same reason, and it is the path that actually
    produced the reported symptom: a COMMIT that returns SQLITE_BUSY also
    leaves the transaction open, and 31 call sites in the store modules
    commit through `db._conn` rather than through `Database._commit` — 29
    literal, plus the two in `references.py` that bind
    `conn = self._db._conn` first.
    Putting the retry here — rather than in `Database._commit` — is what makes
    it reach them; a rollback at this level and a retry one level up would
    instead commit an empty transaction and lose the write.
    """

    def _rollback_quietly(self) -> None:
        # The in_transaction check sits inside the try too: on a broken or
        # closed connection it can itself raise, and that must not mask the
        # original error the caller is about to receive.
        try:
            if self.in_transaction:
                self.rollback()
        except sqlite3.Error:
            # The caller is about to receive the original failure, which is
            # the actionable one; say that this connection is now dirty.
            _logger.warning(
                'rollback failed; connection left in a transaction', exc_info=True
            )

    def _commit_once(self) -> None:
        """One COMMIT attempt. The seam the retry tests intercept."""
        sqlite3.Connection.commit(self)

    def commit(self) -> None:
        """Commit, retrying while the database stays write-locked.

        When the retries run out — or anything else interrupts the attempt,
        including the backoff sleep itself — the transaction is rolled back
        before the error propagates: a connection left mid-transaction holds
        SQLite's write lock for the rest of the process's life (R57).
        """
        try:
            for attempt in range(_BUSY_RETRIES + 1):
                try:
                    self._commit_once()
                    return
                except sqlite3.OperationalError as exc:
                    if 'database is locked' not in str(exc) or attempt == _BUSY_RETRIES:
                        raise
                    time.sleep(_BACKOFF_BASE * 2**attempt)
        except BaseException:
            # Same invariant as the statement shims below, and the reason the
            # rollback wraps the whole loop rather than each attempt: a COMMIT
            # can block for the full busy_timeout, so a Ctrl-C arrives either
            # inside it or inside the sleep after it. Both must leave nothing
            # behind.
            self._rollback_quietly()
            raise

    # BaseException is deliberate in all four (commit and the three
    # statement shims): a Ctrl-C or a SystemExit mid-write must not leave the
    # transaction (and its write lock) behind either. The error is always
    # re-raised, so nothing is swallowed.
    # `Any` on the parameters: sqlite3's own stub type for it is a long
    # union of protocols, and this shim only forwards the value unchanged.
    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        try:
            return super().execute(sql, parameters)
        except BaseException:
            self._rollback_quietly()
            raise

    def executemany(self, sql: str, parameters: Any, /) -> sqlite3.Cursor:
        try:
            return super().executemany(sql, parameters)
        except BaseException:
            self._rollback_quietly()
            raise

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        try:
            return super().executescript(sql_script)
        except BaseException:
            self._rollback_quietly()
            raise


class Database:
    """CodingDude's single SQLite store. Created on first use.

    One connection per thread (R57): a sqlite3 connection is a transaction
    boundary, so sharing one across the server's threadpool lets two threads
    commit each other's half-written work — and CPython raises
    `InterfaceError: bad parameter or other API misuse` when it happens.
    """

    def __init__(self, home: Path):
        self._home = Path(home)
        self._local = threading.local()
        self._schema_ready = False
        self._migrated = False
        # open the first connection and migrate eagerly, on the calling thread
        _ = self._conn

    @property
    def _conn(self) -> sqlite3.Connection:
        """This thread's connection, opened on first use."""
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            return conn
        self._home.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self._home / 'codingdude.db',
            check_same_thread=False,
            factory=_Connection,
        )
        conn.row_factory = sqlite3.Row
        # busy_timeout first: the WAL switch and the legacy-table drop below
        # can themselves hit another writer's lock, and would otherwise run
        # with SQLite's default 5 s handler instead of the configured 15 s.
        conn.execute('PRAGMA busy_timeout=15000')
        conn.execute('PRAGMA journal_mode=WAL')
        # #238: passive autocheckpoint every 256 pages (~1 MB), not SQLite's
        # 1000-page (~4 MB) default — smaller WAL frames mean cheaper reads
        # and a shorter window in which a pinned reader can starve checkpoints.
        conn.execute('PRAGMA wal_autocheckpoint=256')
        # migration: embeddings gained workdir scoping in 0.3.1 — the cache is
        # disposable, so recreate the legacy shape in place
        cols = [r[1] for r in conn.execute('PRAGMA table_info(embeddings)')]
        if cols and 'workdir' not in cols:
            conn.execute('DROP TABLE embeddings')
        self._local.conn = conn
        if not self._schema_ready:
            conn.executescript(_SCHEMA)
            conn.commit()
            self._schema_ready = True
        # set before migrating: _migrate() re-enters this property, so the flag
        # is a re-entrancy guard, not a completion marker
        if not self._migrated:
            self._migrated = True
            self._migrate()
        return conn

    @_conn.setter
    def _conn(self, conn: sqlite3.Connection) -> None:
        """Replace this thread's connection (test seam)."""
        self._local.conn = conn

    def _migrate(self) -> None:
        """Add columns introduced after a database was created (R3).

        CREATE TABLE IF NOT EXISTS won't alter existing databases, so new
        sessions-table columns are added here, guarded by a PRAGMA check.
        """
        existing = {
            r['name'] for r in self._conn.execute('PRAGMA table_info(sessions)')
        }
        # Fully literal statements: no interpolated SQL at all.
        for column, stmt in (
            ('context_tokens',
             'ALTER TABLE sessions ADD COLUMN context_tokens INTEGER'),
            ('context_limit',
             'ALTER TABLE sessions ADD COLUMN context_limit INTEGER'),
            ('keep_for_evals',
             'ALTER TABLE sessions ADD COLUMN keep_for_evals'
             ' INTEGER NOT NULL DEFAULT 0'),
        ):
            if column not in existing:
                self._conn.execute(stmt)
        ticket_cols = {
            r['name'] for r in self._conn.execute('PRAGMA table_info(tickets)')
        }
        if ticket_cols and 'roadmap_id' not in ticket_cols:
            self._conn.execute('ALTER TABLE tickets ADD COLUMN roadmap_id TEXT')
        memory_cols = {
            r['name'] for r in self._conn.execute('PRAGMA table_info(memory)')
        }
        if memory_cols and 'kind' not in memory_cols:
            # R49: solutions memory — existing rows are plain facts.
            self._conn.execute(
                "ALTER TABLE memory ADD COLUMN kind TEXT NOT NULL DEFAULT 'fact'"
            " CHECK (kind IN ('fact', 'solution'))"
            )
        self._commit()

    def _commit(self) -> None:
        """Commit this thread's connection.

        The retry-and-rollback lives in `_Connection.commit`, one level down,
        so the 31 call sites in the store modules that commit through
        `db._conn` directly get it too, not just the ones in this module.
        """
        self._conn.commit()

    # #238: soft threshold at which the idle janitor attempts a TRUNCATE
    # checkpoint; above WAL_CEILING_BYTES it also warns — that is the
    # documented worst case, reached only when readers pin the log faster
    # than sweeps can truncate it.
    WAL_CHECKPOINT_THRESHOLD_BYTES = 4 * 1024 * 1024
    WAL_CEILING_BYTES = 64 * 1024 * 1024

    def checkpoint_idle(
        self, threshold_bytes: int | None = None
    ) -> dict:
        """Bound the WAL (#238): TRUNCATE-checkpoint when it has grown past
        `threshold_bytes` (default 4 MB).

        Passive autocheckpoint can be starved indefinitely by a reader
        holding an old snapshot, which is how the WAL reached 25 MB in the
        wild. The janitor calls this each sweep; busy readers surface as
        `busy=1` in the result (never an exception). The attempt runs on a
        dedicated connection with a 1 s busy_timeout so a held write lock
        cannot stall a sweep — the worker connections keep their 15 s.
        A WAL past WAL_CEILING_BYTES (64 MB, documented ceiling) additionally
        logs a warning — growth beyond it means readers never release.
        """
        threshold = (
            self.WAL_CHECKPOINT_THRESHOLD_BYTES
            if threshold_bytes is None
            else threshold_bytes
        )
        wal = self._home / 'codingdude.db-wal'
        size = wal.stat().st_size if wal.exists() else 0
        if size < threshold:
            return {'ran': False, 'wal_bytes': size}
        ck = sqlite3.connect(self._home / 'codingdude.db')
        try:
            ck.execute('PRAGMA busy_timeout=1000')
            busy, _log, _ckpt = ck.execute(
                'PRAGMA wal_checkpoint(TRUNCATE)'
            ).fetchone()
        finally:
            ck.close()
        size = wal.stat().st_size if wal.exists() else 0
        if busy:
            _logger.info('idle WAL checkpoint skipped (busy readers); %d bytes', size)
        if size >= self.WAL_CEILING_BYTES:
            _logger.warning(
                'WAL is %d bytes (past the %d ceiling) — readers are pinning '
                'the log faster than checkpoints can truncate it',
                size, self.WAL_CEILING_BYTES,
            )
        return {'ran': True, 'busy': busy, 'wal_bytes': size}

    def update_session_context(
        self, session_id: str, total_tokens: int, model_limit: int
    ) -> None:
        """Persist the latest context-window snapshot for the UI meter."""
        self._conn.execute(
            'UPDATE sessions SET context_tokens = ?, context_limit = ?'
            ' WHERE session_id = ?',
            (total_tokens, model_limit, session_id),
        )
        self._commit()

    @classmethod
    def connect(cls, home: Path) -> 'Database':
        """Open the store, creating the home directory if needed.

        Schema creation and migration run once, on the calling thread, before
        any other thread can reach `_conn`.
        """
        home = Path(home)
        home.mkdir(parents=True, exist_ok=True)
        return cls(home)

    def create_project(self, name: str, workdir: Path) -> int:
        cur = self._conn.execute(
            'INSERT INTO projects (name, workdir, created_at) VALUES (?, ?, ?)',
            (name, str(workdir), utc_now_iso()),
        )
        self._commit()
        if cur.lastrowid is None:  # pragma: no cover - INSERT always sets it
            raise RuntimeError('INSERT did not yield a rowid')
        return cur.lastrowid

    def list_projects(self) -> list[dict]:
        """Projects, most recently active first.

        Recency = the newest session's updated_at in that workdir; projects
        with no sessions fall back to their own creation time, so startup
        resumes the project actually used last, not the alphabetically first.
        """
        rows = self._conn.execute(
            'SELECT p.id, p.name, p.workdir, p.created_at,'
            ' MAX(s.updated_at) AS last_activity FROM projects p'
            ' LEFT JOIN sessions s ON s.workdir = p.workdir'
            ' GROUP BY p.id ORDER BY COALESCE(MAX(s.updated_at), p.created_at) DESC'
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_project(self, project_id: int) -> bool:
        cur = self._conn.execute('DELETE FROM projects WHERE id = ?', (project_id,))
        self._commit()
        return cur.rowcount > 0

    def project_by_workdir(self, workdir: Path) -> dict | None:
        row = self._conn.execute(
            'SELECT id, name, workdir FROM projects WHERE workdir = ?',
            (str(workdir),),
        ).fetchone()
        return dict(row) if row else None

    def create_session(self, workdir: Path, title: str | None = None) -> str:
        session_id = uuid.uuid4().hex
        now = utc_now_iso()
        self._conn.execute(
            'INSERT INTO sessions (session_id, workdir, created_at, updated_at, title)'
            ' VALUES (?, ?, ?, ?, ?)',
            (session_id, str(workdir), now, now, title),
        )
        self._commit()
        return session_id

    def list_sessions(self, workdir: Path) -> list[SessionInfo]:
        rows = self._conn.execute(
            'SELECT * FROM sessions WHERE workdir = ? ORDER BY updated_at DESC',
            (str(workdir),),
        ).fetchall()
        infos = []
        for r in rows:
            d = dict(r)
            d['keep_for_evals'] = bool(d.get('keep_for_evals', 0))
            infos.append(SessionInfo(**d))
        return infos

    def append_messages(self, session_id: str, payload: str) -> None:
        """Append one message, allocating its sequence atomically.

        A read-then-insert hands two concurrent appenders the same seq and
        trips UNIQUE (session_id, seq): the server writes the user turn while
        the worker writes assistant turns for the same session (R57).
        """
        self._conn.execute(
            'INSERT INTO messages (session_id, seq, payload)'
            ' SELECT ?, COALESCE(MAX(seq), -1) + 1, ? FROM messages'
            ' WHERE session_id = ?',
            (session_id, payload, session_id),
        )
        self._conn.execute(
            'UPDATE sessions SET updated_at = ? WHERE session_id = ?', (utc_now_iso(), session_id)
        )
        self._commit()

    def replace_messages(self, session_id: str, payloads: list[str]) -> None:
        """Overwrite the session's message list (used by compaction)."""
        self._conn.execute(
            'DELETE FROM messages WHERE session_id = ?', (session_id,)
        )
        for seq, payload in enumerate(payloads):
            self._conn.execute(
                'INSERT INTO messages (session_id, seq, payload) VALUES (?, ?, ?)',
                (session_id, seq, payload),
            )
        self._conn.execute(
            'UPDATE sessions SET updated_at = ? WHERE session_id = ?', (utc_now_iso(), session_id)
        )
        self._commit()

    def _session_scoped_tables(self) -> list[str]:
        """Every table keyed by session_id (M6: derived from the schema, so
        delete_session can never lag new tables)."""
        names = [
            r[0] for r in self._conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='table' AND name != 'sessions'"
            )
        ]
        scoped = []
        for name in sorted(names):
            # name comes from sqlite_master, never user input; validated to
            # a plain identifier so the formatted query stays literal
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
                continue
            # pragma_table_info(?) is parameterizable (unlike PRAGMA);
            # the SELECT projects exactly one column: the name
            cols = {r[0] for r in self._conn.execute(
                'SELECT name FROM pragma_table_info(?)', (name,))}
            if 'session_id' in cols:
                scoped.append(name)
        return scoped

    def delete_session(self, session_id: str) -> None:
        for table in self._session_scoped_tables():
            # table is validated to [A-Za-z_][A-Za-z0-9_]* at the source
            # (_session_scoped_tables); identifiers cannot be parameterized.
            sql = f'DELETE FROM {table} WHERE session_id = ?'  # nosec B608 - table identifier regex-validated in _session_scoped_tables
            self._conn.execute(sql, (session_id,))
        self._conn.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        self._commit()

    def record_pattern_approval(self, session_id: str, pattern: str) -> None:
        self._conn.execute(
            'INSERT INTO approvals (session_id, tool_name, args, pattern, status, created_at)'
            " VALUES (?, 'shell', '', ?, 'approved', ?)",
            (session_id, pattern, utc_now_iso()),
        )
        self._commit()

    def session_patterns(self, session_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT pattern FROM approvals"
            " WHERE session_id = ? AND status = 'approved' AND pattern != ''",
            (session_id,),
        ).fetchall()
        return [r['pattern'] for r in rows]

    def set_keep_for_evals(self, session_id: str, keep: bool) -> None:
        """Mark (or unmark) a session as worth keeping for eval curation."""
        self._conn.execute(
            'UPDATE sessions SET keep_for_evals = ? WHERE session_id = ?',
            (int(keep), session_id),
        )
        self._commit()

    def add_session_note(
        self, session_id: str, content: str,
        run_id: str | None = None, offset_s: float | None = None,
    ) -> int:
        """Timestamped user annotation pinned to a point in the session."""
        cur = self._conn.execute(
            'INSERT INTO session_notes'
            ' (session_id, run_id, offset_s, content, created_at)'
            ' VALUES (?, ?, ?, ?, ?)',
            (session_id, run_id, offset_s, content, utc_now_iso()),
        )
        self._commit()
        return cur.lastrowid or 0

    def record_render(
        self, session_id: str, path: str, bytes_: int, mtime: int,
    ) -> None:
        """Persist a captured render (R1): per-session provenance for images
        the run produced, so the Renders tab survives workdir moves."""
        self._conn.execute(
            'INSERT INTO renders (session_id, path, bytes, mtime, captured_at)'
            ' VALUES (?, ?, ?, ?, ?)',
            (session_id, path, bytes_, mtime, utc_now_iso()),
        )
        self._commit()

    def list_renders(self, session_id: str) -> list[dict]:
        """Captured renders for a session, newest capture first."""
        rows = self._conn.execute(
            'SELECT path, bytes, mtime, captured_at FROM renders'
            ' WHERE session_id = ? ORDER BY id DESC',
            (session_id,),
        ).fetchall()
        return [
            {'path': r[0], 'bytes': r[1], 'mtime': r[2], 'captured_at': r[3]}
            for r in rows
        ]

    def record_process(
        self, session_id: str, *, pid: int, command: str, started_at: str,
        status: str, exit_code: int | None = None, background: bool = False,
    ) -> int | None:
        """Persist a shell-process lifecycle record (R28 Phase 1).

        Best-effort by callers — never fails a run. Returns the row id so
        the finish transition can UPDATE instead of duplicating the row.
        """
        cur = self._conn.execute(
            'INSERT INTO processes (session_id, pid, command, started_at,'
            ' status, exit_code, background) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (session_id, pid, command, started_at, status, exit_code,
             int(background)),
        )
        self._commit()
        return cur.lastrowid

    def update_process(
        self, row_id: int, *, status: str,
        exit_code: int | None = None, background: bool = False,
    ) -> None:
        self._conn.execute(
            'UPDATE processes SET status = ?, exit_code = ?, background = ?'
            ' WHERE id = ?',
            (status, exit_code, int(background), row_id),
        )
        self._commit()

    def list_processes(self, session_id: str) -> list[dict]:
        """Recorded shell processes for a session, newest first.

        Rows still marked 'running' are reconciled against actual pid
        liveness: a worker that died before mark_exited otherwise leaves a
        phantom live process in the HITL panel forever. Dead pids are
        corrected in the DB, not just in the response.
        """
        from .processes import _pid_alive

        rows = self._conn.execute(
            'SELECT id, pid, command, started_at, status, exit_code, background'
            ' FROM processes WHERE session_id = ? ORDER BY id DESC',
            (session_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop('id', None)
            d['background'] = bool(d['background'])
            if d['status'] == 'running' and not _pid_alive(d['pid']):
                d['status'] = 'exited (no capture)'
                self.update_process(
                    r['id'], status=d['status'], exit_code=None,
                    background=d['background'],
                )
            out.append(d)
        return out

    def reconcile_dead_processes(self) -> int:
        """Startup sweep: durably end 'running' process rows whose pid is gone.

        Same reconciliation list_processes does lazily, but across ALL
        sessions at boot, so phantom live processes never reach the HITL
        panel after a crash. Returns the number of rows marked.
        """
        from .processes import _pid_alive

        rows = self._conn.execute(
            "SELECT id, pid, background FROM processes WHERE status = 'running'",
        ).fetchall()
        marked = 0
        for r in rows:
            if not _pid_alive(r['pid']):
                self.update_process(
                    r['id'], status='exited (no capture)',
                    background=bool(r['background']))
                marked += 1
        return marked

    # --- Runs (R31): durable run lifecycle so end-state survives bounces ---

    def record_run_start(self, run_id: str, session_id: str, *, pid: int | None = None) -> None:
        self._conn.execute(
            'INSERT OR REPLACE INTO runs'
            ' (run_id, session_id, worker_pid, status, started_at)'
            " VALUES (?, ?, ?, 'running', ?)",
            (run_id, session_id, pid, utc_now_iso()),
        )
        self._commit()

    def record_run_end(
        self, run_id: str, status: str, *, exit_code: int | None = None
    ) -> None:
        self._conn.execute(
            'UPDATE runs SET status = ?, exit_code = ?, ended_at = ? WHERE run_id = ?',
            (status, exit_code, utc_now_iso(), run_id),
        )
        self._commit()

    def get_run(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            'SELECT run_id, session_id, worker_pid, status, exit_code,'
            ' started_at, ended_at FROM runs WHERE run_id = ?',
            (run_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_runs(self, session_id: str, limit: int = 20) -> list[dict]:
        """Runs for a session, newest first (#77 run-output view)."""
        rows = self._conn.execute(
            'SELECT run_id, session_id, worker_pid, status, exit_code,'
            ' started_at, ended_at FROM runs WHERE session_id = ?'
            ' ORDER BY started_at DESC, rowid DESC LIMIT ?',
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def reconcile_interrupted_runs(self) -> int:
        """Mark runs still 'running' as 'interrupted' (server-boot reconcile).

        A run that was live when the server died can never deliver a terminal
        event; its end state is 'interrupted' by definition. Idempotent.
        """
        cur = self._conn.execute(
            "UPDATE runs SET status = 'interrupted', ended_at = ?"
            " WHERE status = 'running'",
            (utc_now_iso(),),
        )
        self._commit()
        return cur.rowcount

    def list_session_notes(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            'SELECT id, session_id, run_id, offset_s, content, created_at'
            ' FROM session_notes WHERE session_id = ? ORDER BY id',
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def session_workdir(self, session_id: str) -> str | None:
        row = self._conn.execute(
            'SELECT workdir FROM sessions WHERE session_id = ?', (session_id,)
        ).fetchone()
        return row['workdir'] if row else None

    def load_messages(self, session_id: str, limit: int | None = None) -> list[str]:
        if limit is not None:
            rows = self._conn.execute(
                'SELECT payload FROM messages WHERE session_id = ? '
                'ORDER BY seq DESC LIMIT ?',
                (session_id, limit),
            ).fetchall()
            return [r['payload'] for r in reversed(rows)]
        rows = self._conn.execute(
            'SELECT payload FROM messages WHERE session_id = ? ORDER BY seq',
            (session_id,),
        ).fetchall()
        return [r['payload'] for r in rows]

    def record_usage(
        self,
        session_id: str,
        *,
        model: str,
        requests: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float | None = None,
    ) -> None:
        self._conn.execute(
            'INSERT INTO usage (session_id, model, requests, input_tokens, output_tokens,'
            ' cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (session_id, model, requests, input_tokens, output_tokens, cost_usd, utc_now_iso()),
        )
        self._commit()

    def session_usage(self, session_id: str) -> dict[str, float | None]:
        row = self._conn.execute(
            'SELECT COALESCE(SUM(requests), 0) AS requests,'
            ' COALESCE(SUM(input_tokens), 0) AS input_tokens,'
            ' COALESCE(SUM(output_tokens), 0) AS output_tokens,'
            ' SUM(cost_usd) AS cost_usd FROM usage WHERE session_id = ?',
            (session_id,),
        ).fetchone()
        usage = dict(row)
        usage['by_model'] = [
            dict(r)
            for r in self._conn.execute(
                'SELECT model, COALESCE(SUM(requests), 0) AS requests,'
                ' COALESCE(SUM(input_tokens), 0) AS input_tokens,'
                ' COALESCE(SUM(output_tokens), 0) AS output_tokens,'
                ' SUM(cost_usd) AS cost_usd'
                ' FROM usage WHERE session_id = ? GROUP BY model ORDER BY model',
                (session_id,),
            ).fetchall()
        ]
        # one row per recorded request batch (a run or an auxiliary call),
        # chronological — the Cost tab's per-step view
        usage['by_request'] = [
            dict(r)
            for r in self._conn.execute(
                'SELECT model, requests, input_tokens, output_tokens, cost_usd, created_at'
                ' FROM usage WHERE session_id = ? ORDER BY id',
                (session_id,),
            ).fetchall()
        ]
        return usage
