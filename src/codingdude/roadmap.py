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
"""First-class planning data (R4): roadmap items, tickets, design decisions, PRDs, tech designs.

Planning state lives in SQLite scoped by project workdir — not in markdown
files the agent must remember to update. Exposes a store for the server's
CRUD endpoints and an agent toolset so the agent reads/updates planning data
as part of doing work. Marking a ticket 'done' automatically records the
current HEAD sha, so every closed ticket links to the commit that closed it.
"""

import logging
import re
import subprocess
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .db import Database
from .db import utc_now_iso as _now

logger = logging.getLogger(__name__)

ROADMAP_STATUSES = ('open', 'in_progress', 'done')
TICKET_STATUSES = ('todo', 'in_progress', 'done')
PRD_STATUSES = ('draft', 'active', 'sunset')
DESIGN_STATUSES = ('draft', 'approved', 'superseded')


# ---- ROADMAP.md bridge -----------------------------------------------------
#
# The markdown file is the canonical roadmap source; the DB-backed Planning UI
# must serve it live and write back to it. `parse_roadmap_md` reads `## R<n> —
# Title` sections with a `**Status:**` line; `upsert_roadmap_md` mutates one
# section in place (status/body) or appends a new one.

_MD_ITEM_RE = re.compile(r'^## (R\d+) — (.+)$', re.MULTILINE)
_MD_STATUS_RE = re.compile(r'^\*\*Status:?\*{0,2}\s*(.*)$', re.MULTILINE)
_MD_STATUS_MAP = {'in-progress': 'in_progress', 'in progress': 'in_progress'}


def _norm_status(raw: str) -> str:
    s = raw.strip().split('·')[0].strip().lower()
    for bad, good in _MD_STATUS_MAP.items():
        if s.startswith(bad):
            return good
    for known in ROADMAP_STATUSES:
        if s.startswith(known):
            return known
    return 'open'


def parse_roadmap_md(path: Path | str) -> list[dict]:
    """Parse ROADMAP.md into [{id, title, status, body}] (body excludes title/status)."""
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    matches = list(_MD_ITEM_RE.finditer(text))
    items: list[dict] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]
        status = 'open'
        body = section
        sm = _MD_STATUS_RE.search(section)
        if sm:
            first_para = re.split(r'\n[ \t\r]*\n', section.lstrip('\r\n'), maxsplit=1)[0]
            if _MD_STATUS_RE.search(first_para):
                status = _norm_status(sm.group(1))
                body = section[:sm.start()] + section[sm.end():]
        items.append({
            'id': m.group(1),
            'title': m.group(2).strip(),
            'status': status,
            'body': body.strip(),
        })
    return items


def upsert_roadmap_md(path: Path | str, item_id: str | None,
                      title: str | None = None, body: str | None = None,
                      status: str | None = None) -> None:
    """Update one section's status (and optionally body), or append a new item."""
    path = Path(path)
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    matches = list(_MD_ITEM_RE.finditer(text))
    if item_id is None:
        next_n = 1 + max((int(m.group(1)[1:]) for m in matches), default=0)
        new_id = f'R{next_n}'
        section = (f'## {new_id} — {title or "Untitled"}\n'
                   f'**Status:** {status or "open"}\n\n{body or ""}\n')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text.rstrip('\n') + '\n\n' + section)
        return
    for i, m in enumerate(matches):
        if m.group(1) != item_id:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]
        new_section = section
        if body is not None:
            sm = _MD_STATUS_RE.search(new_section)
            if sm:
                new_section = new_section[:sm.end()] + '\n\n' + body + new_section[sm.end():]
            else:
                new_section = f'**Status:** {status or "open"}\n\n' + body + new_section
        if status is not None:
            sm = _MD_STATUS_RE.search(new_section)
            if sm:
                new_section = (new_section[:sm.start()]
                               + f'**Status:** {status}'
                               + new_section[sm.end():])
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text[:start] + new_section + text[end:])
        return
    raise ValueError(f'no such roadmap item in {path.name}: {item_id}')




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
        self, workdir: str, title: str, body: str = '', blocked_by: str | None = None,
        roadmap_id: str | None = None,
    ) -> int:
        now = _now()
        cur = self.db._conn.execute(
            'INSERT INTO tickets (workdir, title, status, body, blocked_by, roadmap_id,'
            ' created_at, updated_at)'
            " VALUES (?, ?, 'todo', ?, ?, ?, ?, ?)",
            (workdir, title, body, blocked_by, roadmap_id, now, now),
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

    # ---- product requirements documents (PRDs) ----

    def list_prds(self, workdir: str) -> list[dict]:
        rows = self.db._conn.execute(
            'SELECT * FROM prds WHERE workdir = ?'
            " ORDER BY CASE status WHEN 'draft' THEN 0 WHEN 'active' THEN 1"
            " ELSE 2 END, id",
            (workdir,),
        ).fetchall()
        return [dict(r) for r in rows]

    def create_prd(
        self, workdir: str, title: str, body: str = '', status: str = 'draft',
    ) -> int:
        now = _now()
        cur = self.db._conn.execute(
            'INSERT INTO prds (workdir, title, status, body, created_at, updated_at)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (workdir, title, status, body, now, now),
        )
        self.db._conn.commit()
        if cur.lastrowid is None:  # pragma: no cover - INSERT always sets it
            raise RuntimeError('INSERT did not yield a rowid')
        return cur.lastrowid

    def update_prd(self, workdir: str, prd_id: int, **fields: str) -> bool:
        return self._update('prds', workdir, prd_id, fields)

    def delete_prd(self, workdir: str, prd_id: int) -> bool:
        # Traceability: designs keep their bodies; the link is severed, not dangled.
        self.db._conn.execute(
            'UPDATE tech_designs SET prd_id = NULL WHERE workdir = ? AND prd_id = ?',
            (workdir, prd_id),
        )
        return self._delete('prds', workdir, prd_id)

    # ---- technical design documents ----

    def list_designs(self, workdir: str) -> list[dict]:
        rows = self.db._conn.execute(
            'SELECT * FROM tech_designs WHERE workdir = ?'
            " ORDER BY CASE status WHEN 'draft' THEN 0 WHEN 'approved' THEN 1"
            " ELSE 2 END, id",
            (workdir,),
        ).fetchall()
        return [dict(r) for r in rows]

    def create_design(
        self, workdir: str, title: str, body: str = '',
        prd_id: int | None = None, status: str = 'draft',
    ) -> int:
        now = _now()
        cur = self.db._conn.execute(
            'INSERT INTO tech_designs (workdir, title, status, body, prd_id,'
            ' created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (workdir, title, status, body, prd_id, now, now),
        )
        self.db._conn.commit()
        if cur.lastrowid is None:  # pragma: no cover - INSERT always sets it
            raise RuntimeError('INSERT did not yield a rowid')
        return cur.lastrowid

    def update_design(self, workdir: str, design_id: int, **fields: str) -> bool:
        return self._update('tech_designs', workdir, design_id, fields)

    def delete_design(self, workdir: str, design_id: int) -> bool:
        return self._delete('tech_designs', workdir, design_id)

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


def build_roadmap_toolset(
    store: RoadmapStore, workdir: str, session_id: str | None = None
) -> FunctionToolset:
    """Agent tools for planning data. Kept read/update-biased: the roadmap is
    the user's product intent, so the agent updates status/body but the UI
    remains the place where items are born (create_* stays server-side)."""

    async def list_planning() -> str:
        """Read the project's planning data: roadmap items, tickets, design decisions, PRDs, and tech designs."""
        md = Path(workdir) / 'ROADMAP.md'
        # ROADMAP.md is the canonical roadmap source; DB is the fallback.
        road = parse_roadmap_md(md) if md.is_file() else store.list_roadmap(workdir)
        tickets = store.list_tickets(workdir)
        decisions = store.list_decisions(workdir)
        prds = store.list_prds(workdir)
        designs = store.list_designs(workdir)
        if not (road or tickets or decisions or prds or designs):
            return 'No planning data recorded for this project yet.'
        lines = ['# PRDs']
        lines += [
            f"- [{p['status']}] #{p['id']} {p['title']}" for p in prds
        ] or ['- (empty)']
        lines.append('# Roadmap')
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
        lines.append('# Tech designs')
        lines += [
            f"- [{d['status']}] #{d['id']} {d['title']}"
            + (f" (PRD #{d['prd_id']})" if d['prd_id'] else '')
            for d in designs
        ] or ['- (empty)']
        return '\n'.join(lines)

    async def update_roadmap_item(item_id: str | int, status: str, body: str | None = None) -> str:
        """Update a roadmap item's status ('open'|'in_progress'|'done') and optionally its body."""
        if status not in ROADMAP_STATUSES:
            raise ValueError(f'status must be one of {ROADMAP_STATUSES}')
        rid = str(item_id)
        rid = rid if rid.startswith('R') else f'R{rid}'
        md = Path(workdir) / 'ROADMAP.md'
        if md.is_file():
            try:
                upsert_roadmap_md(md, rid, body=body, status=status)
            except ValueError:
                return f'roadmap item {rid} not found in ROADMAP.md'
            return f'roadmap item {rid} → {status}'
        fields: dict = {'status': status}
        if body is not None:
            fields['body'] = body
        if not store.update_roadmap_item(workdir, int(rid[1:]), **fields):
            return f'roadmap item {rid} not found'
        return f'roadmap item {rid} → {status}'

    async def create_roadmap_item(title: str, body: str = '') -> str:
        """Create a roadmap item (R<n>) in ROADMAP.md - the planning umbrella every ticket lives under. Do this BEFORE creating tickets for the work."""
        md = Path(workdir) / 'ROADMAP.md'
        if md.is_file():
            upsert_roadmap_md(md, None, title=title, body=body)
            rid = parse_roadmap_md(md)[-1]['id']
            return f'roadmap item {rid} created: {title}'
        did = store.create_roadmap_item(workdir, title, body)
        return f'roadmap item #{did} created: {title}'

    async def create_ticket(
        title: str, body: str = '', blocked_by: str | None = None,
        roadmap_id: str = '',
    ) -> str:
        """Create a ticket (tracer bullet) under a roadmap item. roadmap_id is required (R-id, e.g. 'R3' or '3'); a ticket may not exist without a roadmap item - even stabilization work."""
        if not roadmap_id:
            return ('refused: tickets require a roadmap item. Call create_roadmap_item '
                    'first (every umbrella needs one, even "Stabilization"), then retry '
                    'with its R-id.')
        rid = roadmap_id if roadmap_id.startswith('R') else f'R{roadmap_id}'
        md = Path(workdir) / 'ROADMAP.md'
        if md.is_file():
            known = {r['id'] for r in parse_roadmap_md(md)}
        else:
            known = {f"R{r['id']}" for r in store.list_roadmap(workdir)}
        if rid not in known:
            return f'refused: roadmap item {rid} not found - create it first (create_roadmap_item).'
        tid = store.create_ticket(workdir, title, body, blocked_by, roadmap_id=rid)
        return f'ticket #{tid} created under {rid}: {title}'

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
        if session_id is not None:
            from .artifacts import ArtifactStore
            try:
                ArtifactStore(store.db, session_id).record_decision(title, body)
            except Exception:  # noqa: BLE001 -- history capture is best-effort
                pass
        return f'design decision #{did} recorded: {title}'

    async def create_prd(title: str, body: str = '') -> str:
        """Create a product requirements document (PRD): the WHAT and WHY of a product or epic - problem, users, goals/non-goals, numbered requirements (REQ-<n>), success metrics, open questions. Load the 'prd' skill for the section skeleton. A PRD is the parent of roadmap items and tech designs."""
        pid = store.create_prd(workdir, title, body)
        return f'PRD #{pid} created: {title}'

    async def update_prd(prd_id: int, status: str | None = None, body: str | None = None) -> str:
        """Update a PRD ('draft'|'active'|'sunset') and/or its full body. Read it first via list_planning + read_prd so you merge, not clobber, the body."""
        fields: dict = {}
        if status is not None:
            if status not in PRD_STATUSES:
                raise ValueError(f'status must be one of {PRD_STATUSES}')
            fields['status'] = status
        if body is not None:
            fields['body'] = body
        if not fields:
            return 'refused: nothing to update - pass status and/or body'
        if not store.update_prd(workdir, prd_id, **fields):
            return f'PRD #{prd_id} not found'
        return f'PRD #{prd_id} updated'

    async def read_prd(prd_id: int) -> str:
        """Read one PRD's full body (requirements, metrics, open questions)."""
        for p in store.list_prds(workdir):
            if p['id'] == prd_id:
                return f"# PRD #{prd_id}: {p['title']} [{p['status']}]\n\n{p['body']}"
        return f'PRD #{prd_id} not found'

    async def create_tech_design(title: str, body: str = '', prd_id: int | None = None) -> str:
        """Create a technical design document (TDD): HOW a system meets PRD requirements - context, requirements traceability (REQ-<n> to design elements), architecture, data/API contracts, alternatives considered, risks. Load the 'tech-design' skill for the section skeleton. prd_id links it to the PRD it implements."""
        did = store.create_design(workdir, title, body, prd_id=prd_id)
        link = f' under PRD #{prd_id}' if prd_id else ''
        return f'tech design #{did} created{link}: {title}'

    async def update_tech_design(design_id: int, status: str | None = None, body: str | None = None) -> str:
        """Update a tech design ('draft'|'approved'|'superseded') and/or its body. Supersede rather than rewrite an approved design."""
        fields: dict = {}
        if status is not None:
            if status not in DESIGN_STATUSES:
                raise ValueError(f'status must be one of {DESIGN_STATUSES}')
            fields['status'] = status
        if body is not None:
            fields['body'] = body
        if not fields:
            return 'refused: nothing to update - pass status and/or body'
        if not store.update_design(workdir, design_id, **fields):
            return f'tech design #{design_id} not found'
        return f'tech design #{design_id} updated'

    async def read_tech_design(design_id: int) -> str:
        """Read one tech design's full body."""
        for d in store.list_designs(workdir):
            if d['id'] == design_id:
                link = f" (implements PRD #{d['prd_id']})" if d['prd_id'] else ''
                return (f"# Tech design #{design_id}: {d['title']}"
                        f" [{d['status']}]{link}\n\n{d['body']}")
        return f'tech design #{design_id} not found'

    return FunctionToolset([
        list_planning,
        create_roadmap_item,
        update_roadmap_item,
        create_ticket,
        update_ticket,
        record_decision,
        create_prd,
        read_prd,
        update_prd,
        create_tech_design,
        read_tech_design,
        update_tech_design,
    ])
