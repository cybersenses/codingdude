"""SQLite persistence for Sessions, messages, approvals, Memory, and usage."""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
CREATE TABLE IF NOT EXISTS design_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
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


class Database:
    """CodingDude's single SQLite store. Created on first use."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a database was created (R3).

        CREATE TABLE IF NOT EXISTS won't alter existing databases, so new
        sessions-table columns are added here, guarded by a PRAGMA check.
        """
        existing = {
            r['name'] for r in self._conn.execute('PRAGMA table_info(sessions)')
        }
        for column, decl in (
            ('context_tokens', 'INTEGER'),
            ('context_limit', 'INTEGER'),
            ('keep_for_evals', 'INTEGER NOT NULL DEFAULT 0'),
        ):
            if column not in existing:
                self._conn.execute(f'ALTER TABLE sessions ADD COLUMN {column} {decl}')
        ticket_cols = {
            r['name'] for r in self._conn.execute('PRAGMA table_info(tickets)')
        }
        if ticket_cols and 'roadmap_id' not in ticket_cols:
            self._conn.execute('ALTER TABLE tickets ADD COLUMN roadmap_id TEXT')
        self._conn.commit()

    def update_session_context(
        self, session_id: str, total_tokens: int, model_limit: int
    ) -> None:
        """Persist the latest context-window snapshot for the UI meter."""
        self._conn.execute(
            'UPDATE sessions SET context_tokens = ?, context_limit = ?'
            ' WHERE session_id = ?',
            (total_tokens, model_limit, session_id),
        )
        self._conn.commit()

    @classmethod
    def connect(cls, home: Path) -> 'Database':
        home.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: runs may execute on a worker thread; access
        # is serialized (one run at a time).
        conn = sqlite3.connect(home / 'codingdude.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        # migration: embeddings gained workdir scoping in 0.3.1 — the cache is
        # disposable, so recreate the legacy shape in place
        cols = [r[1] for r in conn.execute('PRAGMA table_info(embeddings)')]
        if cols and 'workdir' not in cols:
            conn.execute('DROP TABLE embeddings')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.executescript(_SCHEMA)
        conn.commit()
        return cls(conn)

    def create_project(self, name: str, workdir: Path) -> int:
        cur = self._conn.execute(
            'INSERT INTO projects (name, workdir, created_at) VALUES (?, ?, ?)',
            (name, str(workdir), utc_now_iso()),
        )
        self._conn.commit()
        assert cur.lastrowid is not None
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
        self._conn.commit()
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
        self._conn.commit()
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
        row = self._conn.execute(
            'SELECT COALESCE(MAX(seq), -1) + 1 AS next FROM messages WHERE session_id = ?',
            (session_id,),
        ).fetchone()
        self._conn.execute(
            'INSERT INTO messages (session_id, seq, payload) VALUES (?, ?, ?)',
            (session_id, row['next'], payload),
        )
        self._conn.execute(
            'UPDATE sessions SET updated_at = ? WHERE session_id = ?', (utc_now_iso(), session_id)
        )
        self._conn.commit()

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
        self._conn.commit()

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
            cols = {r[1] for r in self._conn.execute(f'PRAGMA table_info({name})')}
            if 'session_id' in cols:
                scoped.append(name)
        return scoped

    def delete_session(self, session_id: str) -> None:
        for table in self._session_scoped_tables():
            self._conn.execute(
                f'DELETE FROM {table} WHERE session_id = ?', (session_id,)
            )
        self._conn.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        self._conn.commit()

    def record_pattern_approval(self, session_id: str, pattern: str) -> None:
        self._conn.execute(
            'INSERT INTO approvals (session_id, tool_name, args, pattern, status, created_at)'
            " VALUES (?, 'shell', '', ?, 'approved', ?)",
            (session_id, pattern, utc_now_iso()),
        )
        self._conn.commit()

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
        self._conn.commit()

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
        self._conn.commit()
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
        self._conn.commit()

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
        self._conn.commit()
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
        self._conn.commit()

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

    # --- Runs (R31): durable run lifecycle so end-state survives bounces ---

    def record_run_start(self, run_id: str, session_id: str, *, pid: int | None = None) -> None:
        self._conn.execute(
            'INSERT OR REPLACE INTO runs'
            ' (run_id, session_id, worker_pid, status, started_at)'
            " VALUES (?, ?, ?, 'running', ?)",
            (run_id, session_id, pid, utc_now_iso()),
        )
        self._conn.commit()

    def record_run_end(
        self, run_id: str, status: str, *, exit_code: int | None = None
    ) -> None:
        self._conn.execute(
            'UPDATE runs SET status = ?, exit_code = ?, ended_at = ? WHERE run_id = ?',
            (status, exit_code, utc_now_iso(), run_id),
        )
        self._conn.commit()

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
        self._conn.commit()
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
        self._conn.commit()

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
