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


class EvidenceError(Exception):
    """The evidence gate (DE-1, decision #95): a 'done' step lacks the
    structured evidence required to verify it, or a 'done' release is
    blocked by drift. The only bypass is a recorded waiver."""


def _validated_evidence(
    index: int,
    command: str | None,
    exit_code: int | None,
    key_output_line: str | None,
) -> dict:
    """Structured evidence for a 'done' step. Free text is not accepted:
    narrative assertion is the unverifiable class this gate closes."""
    command = command.strip() if isinstance(command, str) else ''
    key_line = key_output_line.strip() if isinstance(key_output_line, str) else ''
    missing = []
    if not command:
        missing.append('command')
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        missing.append('exit_code')
    if not key_line:
        missing.append('key_output_line')
    if missing:
        raise EvidenceError(
            f'step {index} marked done without complete evidence — missing or'
            f' invalid: {", ".join(missing)}. Evidence is structured, not free'
            ' text: command = the verification command you ran, exit_code ='
            ' its exit code, key_output_line = the output line that proves it'
            ' (e.g. "3 passed"). Run the check, then record it.'
        )
    return {
        'command': command,
        'exit_code': exit_code,
        'key_output_line': key_line,
    }


def _drift_flags(steps: list[dict]) -> dict:
    """Drift signals for one attempt's steps — the single source both
    drift() (audit view) and release() (write-time gate) read. Legacy
    free-text evidence strings are demoted to 'unverified', honestly."""
    without_evidence: list[int] = []
    unverified: list[int] = []
    out_of_order: list[int] = []
    seen_todo = False
    for i, step in enumerate(steps):
        if step['status'] != 'done':
            seen_todo = True
            continue
        evidence = step.get('evidence')
        if evidence is None:
            without_evidence.append(i)
        elif isinstance(evidence, str):
            unverified.append(i)
        if seen_todo:
            out_of_order.append(i)
    return {
        'done_without_evidence': without_evidence,
        'unverified_evidence': unverified,
        'out_of_order': out_of_order,
    }


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
        self, attempt_id: int, index: int, status: str, *,
        command: str | None = None,
        exit_code: int | None = None,
        key_output_line: str | None = None,
    ) -> None:
        """Record one plan step. A 'done' step requires structured evidence
        (command, exit_code, key_output_line) — the evidence gate raises
        EvidenceError otherwise; non-done statuses are unaffected."""
        attempt = self._by_id(attempt_id)
        if attempt is None:
            raise KeyError(f'no execution attempt #{attempt_id}')
        steps = json.loads(attempt['steps_json'])
        if not (0 <= index < len(steps)):
            raise ValueError(f'step index {index} is out of range')
        evidence = None
        if status == 'done':
            evidence = _validated_evidence(index, command, exit_code, key_output_line)
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
        if status == 'done':
            self._enforce_evidence_gate(attempt)
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
        without structured evidence, legacy free-text evidence (demoted to
        'unverified'), and steps completed out of order."""
        state = self.resume_state(ticket_id)
        if state is None:
            raise KeyError(f'no execution history for ticket #{ticket_id}')
        return {'attempt_id': state['id'],
                **_drift_flags(json.loads(state['steps_json']))}

    def waive_drift(
        self, attempt_id: int, indices: list[int], reason: str,
    ) -> list[dict]:
        """Record an explicit waiver for drift-flagged step indices — the
        only bypass for the release gate (always-gated philosophy: bypasses
        exist but are recorded). Persisted on the attempt, rendered by the
        resume tool, auditable via waivers()."""
        attempt = self._by_id(attempt_id)
        if attempt is None:
            raise KeyError(f'no execution attempt #{attempt_id}')
        if not reason or not reason.strip():
            raise ValueError('a waiver needs a reason')
        if not indices:
            raise ValueError('a waiver needs at least one step index')
        already = set(indices) & self._waived_indices(attempt)
        if already:
            raise ValueError(
                f'step(s) {sorted(already)} already waived — one waiver per step'
            )
        flags = _drift_flags(json.loads(attempt['steps_json']))
        flaggable = set(flags['done_without_evidence']) | set(flags['out_of_order'])
        unknown = sorted(set(indices) - flaggable)
        if unknown:
            raise ValueError(
                f'step(s) {unknown} are not drift-flagged — waive only flagged'
                f' steps (flagged: {sorted(flaggable)})'
            )
        waivers = self._waivers(attempt)
        waivers.append({
            'indices': sorted(set(indices)),
            'reason': reason.strip(),
            'at': _now(),
        })
        self.db._conn.execute(
            'UPDATE ticket_execution SET waivers_json = ?'
            ' WHERE id = ? AND workdir = ?',
            (json.dumps(waivers), attempt_id, self.workdir),
        )
        self.db._conn.commit()
        return waivers

    def waivers(self, ticket_id: int) -> list[dict]:
        """Recorded waivers on the latest attempt (audit view)."""
        state = self.resume_state(ticket_id)
        if state is None:
            return []
        return self._waivers(state)

    def _enforce_evidence_gate(self, attempt: dict) -> None:
        """Release-time gate (DE-1): a 'done' release requires every done
        step to carry structured evidence and ordered progress; waived
        indices are exempt."""
        flags = _drift_flags(json.loads(attempt['steps_json']))
        blocked = sorted(
            (set(flags['done_without_evidence']) | set(flags['out_of_order']))
            - self._waived_indices(attempt)
        )
        if blocked:
            raise EvidenceError(
                f'cannot release attempt #{attempt["id"]} as done: step(s)'
                f' {blocked} lack verified evidence or ran out of order.'
                ' Complete them with update_execution_step (command,'
                ' exit_code, key_output_line) or explicitly waive_drift('
                'indices, reason) — waivers are recorded on the attempt.'
            )

    def _waivers(self, attempt: dict) -> list[dict]:
        raw = attempt.get('waivers_json')
        return json.loads(raw) if raw else []

    def _waived_indices(self, attempt: dict) -> set[int]:
        return {i for w in self._waivers(attempt) for i in w['indices']}

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
        index: int, status: str, *,
        command: str | None = None,
        exit_code: int | None = None,
        key_output_line: str | None = None,
    ) -> str:
        """Record plan-step progress ('todo'|'done'). A 'done' step requires
        structured evidence from a check you actually ran: command (the
        verification command), exit_code (its exit code), key_output_line
        (the output line proving it, e.g. "3 passed"). Free text is not
        evidence; run the check, then record it."""
        try:
            store.set_step(_attempt(), index, status, command=command,
                           exit_code=exit_code, key_output_line=key_output_line)
        except EvidenceError as exc:
            return str(exc)
        return f'step {index} → {status}' + (
            ' (evidence recorded)' if status == 'done' else ''
        )

    async def heartbeat_claim() -> str:
        """Keep the current claim alive (call periodically during long work)."""
        store.heartbeat(_attempt())
        return 'heartbeat ok'

    async def release_ticket(status: str = 'released') -> str:
        """Finish the claim: 'done' (closes the ticket) or 'released' (steps aside).
        'done' is blocked while steps lack verified evidence or ran out of order."""
        attempt_id = _attempt()
        try:
            store.release(attempt_id, status)
        except EvidenceError as exc:
            return str(exc)
        active.pop()
        return f'attempt #{attempt_id} → {status}'

    async def waive_drift(indices: list[int], reason: str) -> str:
        """Explicitly waive drift-flagged steps (missing evidence / out of
        order) with a reason; the recorded waiver is the only bypass for the
        release gate and stays visible on the attempt."""
        try:
            waivers = store.waive_drift(_attempt(), indices, reason)
        except ValueError as exc:
            return f'waiver not recorded: {exc}'
        last = waivers[-1]
        return (
            f"waived steps {last['indices']} — {last['reason']}"
            ' (recorded on the attempt; visible in resume_state)'
        )

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
        drift_bits = []
        if drift['done_without_evidence']:
            drift_bits.append(
                f"done-without-evidence steps {drift['done_without_evidence']}"
            )
        if drift['unverified_evidence']:
            drift_bits.append(
                'unverified (legacy free-text) evidence on steps'
                f" {drift['unverified_evidence']}"
            )
        if drift['out_of_order']:
            drift_bits.append(f"out-of-order steps {drift['out_of_order']}")
        if drift_bits:
            lines.append('drift: ' + '; '.join(drift_bits)
                         + ' — reconcile before finishing')
        for waiver in store.waivers(ticket_id):
            lines.append(
                f"waived: steps {waiver['indices']} — {waiver['reason']}"
            )
        return '\n'.join(lines)

    return FunctionToolset([
        claim_ticket,
        update_execution_step,
        heartbeat_claim,
        release_ticket,
        waive_drift,
        get_resume_state,
    ])
