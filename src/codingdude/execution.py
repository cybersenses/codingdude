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
"""R9: crash-safe execution claims on tickets.

A ticket claim is an *attempt*: it records who claimed the ticket, the plan,
per-step progress with verification evidence, and a heartbeat. A fresh session
resumes by reading the latest attempt instead of re-deriving state from git.
"""

import json
from datetime import UTC, datetime, timedelta

from pydantic_ai import FunctionToolset

from .db import utc_now_iso as _now
from .roadmap import RoadmapStore


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class ExecutionStore:
    """Attempt lineage for tickets, scoped by workdir."""

    def __init__(self, db, workdir: str, stale_after_s: int = 900):
        self.db = db
        self.workdir = workdir
        self.stale_after_s = stale_after_s

    def claim(
        self,
        ticket_id: int,
        session_id: str,
        plan_steps: list[str] | None = None,
    ) -> dict:
        """Claim a ticket. Crash-safe: an attempt held by another session with
        a fresh heartbeat blocks the claim; a stale one is marked 'stale' and
        a new attempt opens. Same-session claims reuse their attempt."""
        live = self.db._conn.execute(
            "SELECT * FROM ticket_execution"
            " WHERE ticket_id = ? AND workdir = ? AND status = 'claimed'"
            ' ORDER BY id DESC LIMIT 1',
            (ticket_id, self.workdir),
        ).fetchone()
        if live is not None and live['session_id'] != session_id:
            cutoff = _iso(datetime.now(UTC) - timedelta(seconds=self.stale_after_s))
            if live['heartbeat_at'] <= cutoff:
                self.db._conn.execute(
                    "UPDATE ticket_execution SET status = 'stale' WHERE id = ?",
                    (live['id'],),
                )
                self.db._conn.commit()
            else:
                raise ValueError(
                    f'ticket #{ticket_id} already claimed by session'
                    f" {live['session_id']} (heartbeat {live['heartbeat_at']})"
                )
        if live is not None and live['session_id'] == session_id:
            return dict(live)
        cur = self.db._conn.execute(
            'INSERT INTO ticket_execution'
            ' (ticket_id, workdir, session_id, status, plan_json, steps_json,'
            '  heartbeat_at, created_at)'
            " VALUES (?, ?, ?, 'claimed', ?, ?, ?, ?)",
            (
                ticket_id,
                self.workdir,
                session_id,
                json.dumps(plan_steps or []),
                json.dumps(
                    [{'text': s, 'status': 'todo', 'evidence': None}
                     for s in plan_steps or []]
                ),
                _now(),
                _now(),
            ),
        )
        self.db._conn.commit()
        return self._by_id(cur.lastrowid)  # type: ignore[arg-type, return-value]

    def heartbeat(self, attempt_id: int) -> None:
        cur = self.db._conn.execute(
            'UPDATE ticket_execution SET heartbeat_at = ? WHERE id = ? AND workdir = ?',
            (_now(), attempt_id, self.workdir),
        )
        self.db._conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f'no execution attempt #{attempt_id}')

    def set_step(
        self, attempt_id: int, index: int, status: str, evidence: str | None = None
    ) -> None:
        attempt = self._by_id(attempt_id)
        if attempt is None:
            raise KeyError(f'no execution attempt #{attempt_id}')
        steps = json.loads(attempt['steps_json'])
        if not (0 <= index < len(steps)):
            raise ValueError(f'step index {index} is out of range')
        steps[index] = {'text': steps[index]['text'], 'status': status,
                        'evidence': evidence}
        self.db._conn.execute(
            'UPDATE ticket_execution SET steps_json = ?, heartbeat_at = ? WHERE id = ?',
            (json.dumps(steps), _now(), attempt_id),
        )
        self.db._conn.execute(
            "UPDATE tickets SET status = 'in_progress', updated_at = ?"
            ' WHERE id = ? AND workdir = ? AND status != \'done\'',
            (_now(), attempt['ticket_id'], self.workdir),
        )
        self.db._conn.commit()

    def release(self, attempt_id: int, status: str = 'released') -> None:
        if status not in ('released', 'done'):
            raise ValueError("status must be 'released' or 'done'")
        attempt = self._by_id(attempt_id)
        if attempt is None:
            raise KeyError(f'no execution attempt #{attempt_id}')
        self.db._conn.execute(
            'UPDATE ticket_execution SET status = ?, heartbeat_at = ? WHERE id = ?',
            (status, _now(), attempt_id),
        )
        self.db._conn.commit()
        if status == 'done':
            RoadmapStore(self.db).update_ticket(
                self.workdir, attempt['ticket_id'], status='done'
            )

    def attempts(self, ticket_id: int) -> list[dict]:
        """Full attempt lineage for a ticket, oldest first."""
        rows = self.db._conn.execute(
            'SELECT * FROM ticket_execution WHERE ticket_id = ? AND workdir = ?'
            ' ORDER BY id',
            (ticket_id, self.workdir),
        ).fetchall()
        return [dict(r) for r in rows]

    def resume_state(self, ticket_id: int) -> dict | None:
        row = self.db._conn.execute(
            'SELECT * FROM ticket_execution WHERE ticket_id = ? AND workdir = ?'
            ' ORDER BY id DESC LIMIT 1',
            (ticket_id, self.workdir),
        ).fetchone()
        return dict(row) if row else None

    def drift(self, ticket_id: int) -> dict:
        """Plan diffing (R9 thickener): compare the latest attempt's claimed
        plan against its actual step progress. Flags steps marked 'done'
        without verification evidence, and steps completed out of order."""
        state = self.resume_state(ticket_id)
        if state is None:
            raise KeyError(f'no execution history for ticket #{ticket_id}')
        steps = json.loads(state['steps_json'])
        without_evidence = [
            i for i, s in enumerate(steps)
            if s['status'] == 'done' and not s.get('evidence')
        ]
        out_of_order = []
        seen_todo = False
        for i, s in enumerate(steps):
            if s['status'] != 'done':
                seen_todo = True
            elif seen_todo:
                out_of_order.append(i)
        return {
            'attempt_id': state['id'],
            'done_without_evidence': without_evidence,
            'out_of_order': out_of_order,
        }

    def _by_id(self, attempt_id: int) -> dict | None:
        row = self.db._conn.execute(
            'SELECT * FROM ticket_execution WHERE id = ? AND workdir = ?',
            (attempt_id, self.workdir),
        ).fetchone()
        return dict(row) if row else None


def build_execution_toolset(store: ExecutionStore, session_id: str) -> FunctionToolset:
    """Agent tools for resumable ticket execution. First move on a claimed
    ticket is get_resume_state, not re-deriving everything from git."""

    active: list[int] = []

    def _attempt() -> int:
        if not active:
            raise LookupError('No active claim — call claim_ticket first.')
        return active[-1]

    async def claim_ticket(ticket_id: int, plan_steps: list[str] | None = None) -> str:
        """Claim a ticket for this session with an ordered plan; resumes your own claim if you already hold it."""
        try:
            attempt = store.claim(ticket_id, session_id, plan_steps=plan_steps)
        except ValueError as exc:
            return f'Cannot claim ticket #{ticket_id}: {exc}'
        active.append(attempt['id'])
        return f"Attempt #{attempt['id']} claimed on ticket #{ticket_id}. Call get_resume_state if resuming."

    async def update_execution_step(
        index: int, status: str, evidence: str | None = None
    ) -> str:
        """Record plan-step progress ('todo'|'done') with verification evidence (test counts, commands run)."""
        store.set_step(_attempt(), index, status, evidence)
        return f'step {index} → {status}' + (f' (evidence: {evidence})' if evidence else '')

    async def heartbeat_claim() -> str:
        """Keep the current claim alive (call periodically during long work)."""
        store.heartbeat(_attempt())
        return 'heartbeat ok'

    async def release_ticket(status: str = 'released') -> str:
        """Finish the claim: 'done' (closes the ticket) or 'released' (steps aside)."""
        attempt_id = _attempt()
        store.release(attempt_id, status)
        active.pop()
        return f'attempt #{attempt_id} → {status}'

    async def get_resume_state(ticket_id: int) -> str:
        """Read the resume state for a ticket: who claimed it, plan, per-step progress and evidence."""
        state = store.resume_state(ticket_id)
        if state is None:
            return f'No execution history for ticket #{ticket_id} — claim it and start fresh.'
        steps = json.loads(state['steps_json'])
        lines = [
            f"attempt #{state['id']} [{state['status']}] by session {state['session_id']}"
            f' (heartbeat {state["heartbeat_at"]})',
        ]
        plan = json.loads(state['plan_json'])
        for i, step in enumerate(steps or plan):
            text = step['text'] if 'text' in step else step
            st = step.get('status', 'todo') if isinstance(step, dict) else 'todo'
            ev = step.get('evidence') if isinstance(step, dict) else None
            line = f'- step {i} [{st}] {text}'
            if ev:
                line += f' — evidence: {ev}'
            lines.append(line)
        drift = store.drift(ticket_id)
        if drift['done_without_evidence'] or drift['out_of_order']:
            lines.append(
                f"drift: done-without-evidence steps {drift['done_without_evidence']}, "
                f"out-of-order steps {drift['out_of_order']} — reconcile before finishing"
            )
        return '\n'.join(lines)

    return FunctionToolset([
        claim_ticket,
        update_execution_step,
        heartbeat_claim,
        release_ticket,
        get_resume_state,
    ])
