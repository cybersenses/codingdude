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
    title TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    seq INTEGER NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (session_id, seq)
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
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    workdir: str
    created_at: str
    updated_at: str
    title: str | None


class Database:
    """CodingDude's single SQLite store. Created on first use."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

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
            (name, str(workdir), _now()),
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
        now = _now()
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
        return [SessionInfo(**dict(r)) for r in rows]

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
            'UPDATE sessions SET updated_at = ? WHERE session_id = ?', (_now(), session_id)
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
            'UPDATE sessions SET updated_at = ? WHERE session_id = ?', (_now(), session_id)
        )
        self._conn.commit()

    def delete_session(self, session_id: str) -> None:
        for table in ('messages', 'approvals', 'usage'):
            self._conn.execute(
                f'DELETE FROM {table} WHERE session_id = ?', (session_id,)
            )
        self._conn.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        self._conn.commit()

    def record_pattern_approval(self, session_id: str, pattern: str) -> None:
        self._conn.execute(
            'INSERT INTO approvals (session_id, tool_name, args, pattern, status, created_at)'
            " VALUES (?, 'shell', '', ?, 'approved', ?)",
            (session_id, pattern, _now()),
        )
        self._conn.commit()

    def session_patterns(self, session_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT pattern FROM approvals"
            " WHERE session_id = ? AND status = 'approved' AND pattern != ''",
            (session_id,),
        ).fetchall()
        return [r['pattern'] for r in rows]

    def session_workdir(self, session_id: str) -> str | None:
        row = self._conn.execute(
            'SELECT workdir FROM sessions WHERE session_id = ?', (session_id,)
        ).fetchone()
        return row['workdir'] if row else None

    def load_messages(self, session_id: str) -> list[str]:
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
            (session_id, model, requests, input_tokens, output_tokens, cost_usd, _now()),
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
        return dict(row)
