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
"""Project notes (user-feedback round 1): per-project guidance the user
leaves during sessions and the agent reads at work.

Notes are workdir-scoped (no cross-project bleed), open by default, and can
be resolved or cleared by both the user (UI) and the agent (`resolve_note`).
"""

import json

from pydantic_ai.toolsets import FunctionToolset


class ProjectNoteStore:
    """SQLite-backed durable guidance notes per project."""
    def __init__(self, db):
        self._db = db

    def add(self, workdir: str, content: str) -> int:
        from .db import utc_now_iso as _now

        cur = self._db._conn.execute(
            'INSERT INTO project_notes (workdir, content, status, created_at)'
            " VALUES (?, ?, 'open', ?)",
            (workdir, content.strip(), _now()),
        )
        self._db._conn.commit()
        return cur.lastrowid or 0

    def list(self, workdir: str, include_resolved: bool = False) -> list[dict]:
        sql = (
            'SELECT id, workdir, content, status, created_at, resolved_at'
            ' FROM project_notes WHERE workdir = ?'
        )
        if not include_resolved:
            sql += " AND status = 'open'"
        rows = self._db._conn.execute(sql + ' ORDER BY id', (workdir,)).fetchall()
        return [dict(r) for r in rows]

    def resolve(self, note_id: int) -> bool:
        from .db import utc_now_iso as _now

        cur = self._db._conn.execute(
            "UPDATE project_notes SET status = 'resolved', resolved_at = ?"
            ' WHERE id = ?',
            (_now(), note_id),
        )
        self._db._conn.commit()
        return cur.rowcount > 0

    def delete(self, note_id: int) -> bool:
        cur = self._db._conn.execute(
            'DELETE FROM project_notes WHERE id = ?', (note_id,)
        )
        self._db._conn.commit()
        return cur.rowcount > 0


def build_project_notes_toolset(store: ProjectNoteStore, workdir: str) -> FunctionToolset:
    """Agent tools to read the user's per-project guidance and maintain it."""

    def read_project_notes(include_resolved: bool = False) -> str:
        """Read this project's guidance notes (open ones by default)."""
        notes = store.list(workdir, include_resolved=include_resolved)
        if not notes:
            return 'no project notes'
        return json.dumps(notes)

    def add_project_note(content: str) -> str:
        """Record a durable guidance note for this project."""
        return json.dumps({'id': store.add(workdir, content)})

    def resolve_note(note_id: int) -> str:
        """Mark a note as dealt with once its guidance has been applied."""
        if store.resolve(note_id):
            return f'note {note_id} resolved'
        return f'no note with id {note_id}'

    return FunctionToolset([read_project_notes, add_project_note, resolve_note])
