"""First-class planning data (R4): roadmap items, tickets, design decisions.

Planning state lives in SQLite scoped by project workdir — not in markdown
files the agent must remember to update. Exposes a store for the server's
CRUD endpoints and an agent toolset so the agent reads/updates planning data
as part of doing work. Marking a ticket 'done' automatically records the
current HEAD sha, so every closed ticket links to the commit that closed it.
"""

import logging
import subprocess
from datetime import UTC, datetime

from pydantic_ai.toolsets import FunctionToolset

from .db import Database

logger = logging.getLogger(__name__)

ROADMAP_STATUSES = ('open', 'in_progress', 'done')
TICKET_STATUSES = ('todo', 'in_progress', 'done')


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _head_sha(workdir: str) -> str | None:
    """Short HEAD sha of the project, or None outside a git repo."""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=workdir, capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


class RoadmapStore:
    """CRUD for roadmap_items, tickets, and design_decisions, scoped by workdir."""

    def __init__(self, db: Database):
        self.db = db

    # ---- roadmap items ----

    def list_roadmap(self, workdir: str) -> list[dict]:
        rows = self.db._conn.execute(
            'SELECT * FROM roadmap_items WHERE workdir = ?'
            " ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1"
            " ELSE 2 END, id",
            (workdir,),
        ).fetchall()
        return [dict(r) for r in rows]

    def create_roadmap_item(self, workdir: str, title: str, body: str = '') -> int:
        now = _now()
        cur = self.db._conn.execute(
            'INSERT INTO roadmap_items (workdir, title, status, body, created_at, updated_at)'
            " VALUES (?, ?, 'open', ?, ?, ?)",
            (workdir, title, body, now, now),
        )
        self.db._conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def update_roadmap_item(self, workdir: str, item_id: int, **fields: str) -> bool:
        return self._update('roadmap_items', workdir, item_id, fields)

    def delete_roadmap_item(self, workdir: str, item_id: int) -> bool:
        return self._delete('roadmap_items', workdir, item_id)

    # ---- tickets ----

    def list_tickets(self, workdir: str, status: str | None = None) -> list[dict]:
        if status is not None:
            rows = self.db._conn.execute(
                'SELECT * FROM tickets WHERE workdir = ? AND status = ? ORDER BY id',
                (workdir, status),
            ).fetchall()
        else:
            rows = self.db._conn.execute(
                'SELECT * FROM tickets WHERE workdir = ?'
                " ORDER BY CASE status WHEN 'todo' THEN 0 WHEN 'in_progress' THEN 1"
                " ELSE 2 END, id",
                (workdir,),
            ).fetchall()
        return [dict(r) for r in rows]

    def create_ticket(
        self, workdir: str, title: str, body: str = '', blocked_by: str | None = None
    ) -> int:
        now = _now()
        cur = self.db._conn.execute(
            'INSERT INTO tickets (workdir, title, status, body, blocked_by, created_at, updated_at)'
            " VALUES (?, ?, 'todo', ?, ?, ?, ?)",
            (workdir, title, body, blocked_by, now, now),
        )
        self.db._conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def update_ticket(self, workdir: str, ticket_id: int, **fields: str) -> bool:
        closing = fields.get('status') == 'done'
        changed = self._update('tickets', workdir, ticket_id, fields)
        # Traceability: closing a ticket stamps the commit that closed it.
        if changed and closing:
            sha = _head_sha(workdir)
            if sha:
                self.db._conn.execute(
                    'UPDATE tickets SET commit_sha = ? WHERE id = ?', (sha, ticket_id)
                )
                self.db._conn.commit()
        return changed

    def delete_ticket(self, workdir: str, ticket_id: int) -> bool:
        return self._delete('tickets', workdir, ticket_id)

    # ---- design decisions ----

    def list_decisions(self, workdir: str) -> list[dict]:
        rows = self.db._conn.execute(
            'SELECT * FROM design_decisions WHERE workdir = ? ORDER BY id DESC',
            (workdir,),
        ).fetchall()
        return [dict(r) for r in rows]

    def create_decision(self, workdir: str, title: str, body: str = '') -> int:
        now = _now()
        cur = self.db._conn.execute(
            'INSERT INTO design_decisions (workdir, title, body, created_at, updated_at)'
            ' VALUES (?, ?, ?, ?, ?)',
            (workdir, title, body, now, now),
        )
        self.db._conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def update_decision(self, workdir: str, decision_id: int, **fields: str) -> bool:
        return self._update('design_decisions', workdir, decision_id, fields)

    def delete_decision(self, workdir: str, decision_id: int) -> bool:
        return self._delete('design_decisions', workdir, decision_id)

    # ---- shared helpers ----

    def _update(self, table: str, workdir: str, row_id: int, fields: dict) -> bool:
        if not fields:
            return False
        names = list(fields)
        assignments = ', '.join(f'{name} = ?' for name in names)
        params = [fields[name] for name in names] + [_now(), row_id, workdir]
        cur = self.db._conn.execute(
            f'UPDATE {table} SET {assignments}, updated_at = ? WHERE id = ? AND workdir = ?',
            params,
        )
        self.db._conn.commit()
        return cur.rowcount > 0

    def _delete(self, table: str, workdir: str, row_id: int) -> bool:
        cur = self.db._conn.execute(
            f'DELETE FROM {table} WHERE id = ? AND workdir = ?', (row_id, workdir)
        )
        self.db._conn.commit()
        return cur.rowcount > 0


def build_roadmap_toolset(store: RoadmapStore, workdir: str) -> FunctionToolset:
    """Agent tools for planning data. Kept read/update-biased: the roadmap is
    the user's product intent, so the agent updates status/body but the UI
    remains the place where items are born (create_* stays server-side)."""

    async def list_planning() -> str:
        """Read the project's planning data: roadmap items, open tickets, and recent design decisions."""
        road = store.list_roadmap(workdir)
        tickets = store.list_tickets(workdir)
        decisions = store.list_decisions(workdir)
        if not (road or tickets or decisions):
            return 'No planning data recorded for this project yet.'
        lines = ['# Roadmap']
        lines += [
            f"- [{r['status']}] #{r['id']} {r['title']}" for r in road
        ] or ['- (empty)']
        lines.append('# Tickets')
        lines += [
            f"- [{t['status']}] #{t['id']} {t['title']}"
            + (f" (closed by {t['commit_sha']})" if t['commit_sha'] else '')
            for t in tickets
        ] or ['- (empty)']
        lines.append('# Design decisions')
        lines += [f"- #{d['id']} {d['title']}" for d in decisions[:10]] or ['- (empty)']
        return '\n'.join(lines)

    async def update_roadmap_item(item_id: int, status: str, body: str | None = None) -> str:
        """Update a roadmap item's status ('open'|'in_progress'|'done') and optionally its body."""
        if status not in ROADMAP_STATUSES:
            raise ValueError(f'status must be one of {ROADMAP_STATUSES}')
        fields: dict = {'status': status}
        if body is not None:
            fields['body'] = body
        if not store.update_roadmap_item(workdir, item_id, **fields):
            return f'roadmap item #{item_id} not found'
        return f'roadmap item #{item_id} → {status}'

    async def create_ticket(title: str, body: str = '', blocked_by: str | None = None) -> str:
        """Create a ticket (tracer bullet) for this project, optionally blocked by another ticket's id."""
        tid = store.create_ticket(workdir, title, body, blocked_by)
        return f'ticket #{tid} created: {title}'

    async def update_ticket(ticket_id: int, status: str, body: str | None = None) -> str:
        """Update a ticket's status ('todo'|'in_progress'|'done'). Marking 'done' records the current HEAD commit as closing it."""
        if status not in TICKET_STATUSES:
            raise ValueError(f'status must be one of {TICKET_STATUSES}')
        fields: dict = {'status': status}
        if body is not None:
            fields['body'] = body
        if not store.update_ticket(workdir, ticket_id, **fields):
            return f'ticket #{ticket_id} not found'
        extra = ''
        if status == 'done':
            sha = _head_sha(workdir)
            if sha:
                extra = f' (closing commit {sha})'
        return f'ticket #{ticket_id} → {status}{extra}'

    async def record_decision(title: str, body: str = '') -> str:
        """Record a design decision (ADR-style): what was decided, context, and consequences in body."""
        did = store.create_decision(workdir, title, body)
        return f'design decision #{did} recorded: {title}'

    return FunctionToolset([
        list_planning,
        update_roadmap_item,
        create_ticket,
        update_ticket,
        record_decision,
    ])
