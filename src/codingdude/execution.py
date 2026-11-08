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
import re
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


#: Attempt-level evaluator budget (DE-2, decision #96): the release pass,
#: fix loops, and milestone passes share it; exhaustion stops the loop and
#: surfaces NEEDS_OPERATOR — the convergence alarm against runaway cost.
EVALUATOR_CAP = 3

#: Plan-step marker syntax (DE-2 #296, pinned by test): leading [tag] groups
#: on a plan step — [milestone] flags a boundary evaluation; [function:name]
#: carries the DE-7 function tag (#299 consumes it). Recognized only at the
#: start of the text; the text itself is kept verbatim.
_TAG_RE = re.compile(r'^(?:\[(milestone|function:[A-Za-z][\w-]*)\]\s*)+')
_TAG_ONLY_RE = re.compile(r'^\[(milestone|function:[A-Za-z][\w-]*)\]\s*')


def _parse_step_tags(text: str) -> dict:
    """Marker flags for one plan-step text: {'milestone': True} and/or
    {'function': name}; {} for an untagged step (byte-compat default)."""
    tags: dict = {}
    rest = text
    while True:
        m = _TAG_ONLY_RE.match(rest)
        if m is None:
            break
        name = m.group(1)
        if name == 'milestone':
            tags['milestone'] = True
        else:
            tags['function'] = name.removeprefix('function:')
        rest = rest[m.end():]
    return tags


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
        """Claim a ticket. Crash-safe: an attempt held by another session
        whose run is verifiably dead (terminal runs row) is taken over
        immediately — inheriting its plan, steps, evidence, and waivers —
        one held by a session with no terminal run only yields to heartbeat
        staleness (marked 'stale', no inheritance); a fresh one blocks.
        Same-session claims reuse their attempt."""
        live = self.db._conn.execute(
            "SELECT * FROM ticket_execution"
            " WHERE ticket_id = ? AND workdir = ? AND status = 'claimed'"
            ' ORDER BY id DESC LIMIT 1',
            (ticket_id, self.workdir),
        ).fetchone()
        if live is not None and live['session_id'] != session_id:
            run_status = self._newest_run_status(live['session_id'])
            if run_status is not None and run_status != 'running':
                # DE-4: death-verified takeover — the runs-table join is the
                # only trigger (never heartbeat staleness alone, which can
                # misread a live session under load).
                return self._take_over(live, session_id)
            if run_status is not None:
                # The holder's run is still 'running': live, whatever the
                # heartbeat says (a busy tool call can lag it). The reaper
                # and boot reconcile turn a dead run terminal within seconds,
                # so takeover never waits on staleness in practice.
                raise ValueError(
                    f'ticket #{ticket_id} already claimed by session'
                    f" {live['session_id']} (run still {run_status})"
                )
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
                    [{'text': s, 'status': 'todo', 'evidence': None,
                      **_parse_step_tags(s)}
                     for s in plan_steps or []]
                ),
                _now(),
                _now(),
            ),
        )
        self.db._conn.commit()
        return self._by_id(cur.lastrowid)  # type: ignore[arg-type, return-value]

    def _newest_run_status(self, session_id: str) -> str | None:
        """The newest run row's status for a session, None when it has none.

        Terminal statuses ('completed' / 'failed' / 'gate_aborted' /
        'interrupted' — everything but 'running') are the R72 forensics
        verdict: the reaper, boot reconcile, and worker finish all write
        them, so 'not running' means verifiably dead."""
        row = self.db._conn.execute(
            'SELECT status FROM runs WHERE session_id = ?'
            ' ORDER BY started_at DESC, rowid DESC LIMIT 1',
            (session_id,),
        ).fetchone()
        return row['status'] if row else None

    def _take_over(self, live, session_id: str) -> dict:
        """Supersede a dead session's attempt (DE-4): mark it 'stale', open
        a new claimed attempt that inherits plan, steps (status + evidence),
        and waivers wholesale, and record the superseded attempt id."""
        self.db._conn.execute(
            "UPDATE ticket_execution SET status = 'stale' WHERE id = ?",
            (live['id'],),
        )
        cur = self.db._conn.execute(
            'INSERT INTO ticket_execution'
            ' (ticket_id, workdir, session_id, status, plan_json, steps_json,'
            '  waivers_json, superseded_attempt_id, heartbeat_at, created_at)'
            " VALUES (?, ?, ?, 'claimed', ?, ?, ?, ?, ?, ?)",
            (
                live['ticket_id'],
                self.workdir,
                session_id,
                live['plan_json'],
                live['steps_json'],
                live['waivers_json'] if live['waivers_json'] else '[]',
                live['id'],
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
    ) -> dict:
        """Record one plan step. A 'done' step requires structured evidence
        (command, exit_code, key_output_line) — the evidence gate raises
        EvidenceError otherwise; non-done statuses are unaffected.
        Returns the updated step (marker keys like milestone/function are
        preserved, so triggers can read them)."""
        attempt = self._by_id(attempt_id)
        if attempt is None:
            raise KeyError(f'no execution attempt #{attempt_id}')
        steps = json.loads(attempt['steps_json'])
        if not (0 <= index < len(steps)):
            raise ValueError(f'step index {index} is out of range')
        evidence = None
        if status == 'done':
            evidence = _validated_evidence(index, command, exit_code, key_output_line)
        steps[index] = {**steps[index], 'status': status, 'evidence': evidence}
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
        return steps[index]

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

    def interrupted(self) -> list[dict]:
        """Discovery seam (DE-4): claimed attempts in this workdir whose
        session's newest run is verifiably dead — the work a replacement
        session can take over. Each row carries the resume anchors the
        bootstrap renders: done count and the first non-done step index."""
        rows = self.db._conn.execute(
            "SELECT * FROM ticket_execution"
            ' WHERE workdir = ? AND status = \'claimed\' ORDER BY id',
            (self.workdir,),
        ).fetchall()
        out = []
        for r in rows:
            run_status = self._newest_run_status(r['session_id'])
            if run_status is None or run_status == 'running':
                continue  # live session, or no run evidence: not interruptible
            steps = json.loads(r['steps_json'])
            done_count = sum(1 for s in steps if s.get('status') == 'done')
            next_index = next(
                (i for i, s in enumerate(steps) if s.get('status') != 'done'),
                None,
            )
            out.append({
                'ticket_id': r['ticket_id'],
                'attempt_id': r['id'],
                'session_id': r['session_id'],
                'run_status': run_status,
                'done_count': done_count,
                'next_step_index': next_index,
            })
        return out

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

    def record_evaluation(self, attempt_id: int, record: dict) -> None:
        """Append one evaluator verdict record (DE-2) to the attempt's
        evaluations_json — the audit trail the cap counts and resume
        rendering reads."""
        attempt = self._by_id(attempt_id)
        if attempt is None:
            raise KeyError(f'no execution attempt #{attempt_id}')
        evaluations = self.evaluations(attempt_id)
        evaluations.append({**record, 'at': _now()})
        self.db._conn.execute(
            'UPDATE ticket_execution SET evaluations_json = ?'
            ' WHERE id = ? AND workdir = ?',
            (json.dumps(evaluations), attempt_id, self.workdir),
        )
        self.db._conn.commit()

    def evaluations(self, attempt_id: int) -> list[dict]:
        """Verdict records on one attempt, oldest first."""
        attempt = self._by_id(attempt_id)
        if attempt is None:
            raise KeyError(f'no execution attempt #{attempt_id}')
        raw = attempt.get('evaluations_json')
        return json.loads(raw) if raw else []

    def render_resume(self, ticket_id: int) -> str:
        """The resume-state render (the get_resume_state tool body): attempt
        line, per-step progress with evidence, drift, waivers, and the
        latest NEEDS_WORK findings — the next session's orientation read."""
        state = self.resume_state(ticket_id)
        if state is None:
            return (
                f'No execution history for ticket #{ticket_id} — claim it'
                ' and start fresh.'
            )
        steps = json.loads(state['steps_json'])
        lines = [
            f"attempt #{state['id']} [{state['status']}] by session"
            f" {state['session_id']}"
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
        drift = self.drift(ticket_id)
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
        for waiver in self.waivers(ticket_id):
            lines.append(
                f"waived: steps {waiver['indices']} — {waiver['reason']}"
            )
        needs_work = [
            e for e in self.evaluations(state['id'])
            if e.get('verdict') == 'NEEDS_WORK'
        ]
        if needs_work:
            latest = needs_work[-1]
            lines.append(
                f"evaluator: NEEDS_WORK ({latest.get('trigger')} —"
                f" {latest.get('summary')})"
            )
            for f in latest.get('findings', []):
                where = f.get('file', '?') + (
                    f':{f["symbol"]}' if f.get('symbol') else '')
                lines.append(
                    f'  - {where} [{f.get("severity", "?")}]'
                    f' {f.get("note", "")}'
                )
        return '\n'.join(lines)

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


def build_execution_toolset(
    store: ExecutionStore, session_id: str, evaluator=None,
) -> FunctionToolset:
    """Agent tools for resumable ticket execution. First move on a claimed
    ticket is get_resume_state, not re-deriving everything from git.

    `evaluator` (#296 DE-2): a WorkEvaluator seam. When set, a 'done'
    release and a milestone-flagged step completion each trigger an
    evaluation pass (persisted, capped — non-blocking until the long-run
    flag lands); without one the triggers skip with an honest note."""

    active: list[int] = []

    def _attempt() -> int:
        if not active:
            raise LookupError('No active claim — call claim_ticket first.')
        return active[-1]

    async def _run_evaluation(trigger: str, step_index: int | None = None,
                              ticket_id: int | None = None) -> str:
        """One evaluator pass on the active attempt: capped, persisted,
        honest about a missing evaluator. Never fails the calling tool."""
        attempt_id = _attempt()
        if evaluator is None:
            return '(evaluation skipped: no evaluator configured)'
        passed = [
            e for e in store.evaluations(attempt_id)
            if e.get('verdict') == 'PASS'
        ]
        if passed:
            return '(evaluation already PASSED on this attempt)'
        count = len(store.evaluations(attempt_id))
        if count >= EVALUATOR_CAP:
            evaluations = store.evaluations(attempt_id)
            if not evaluations or evaluations[-1].get('verdict') != 'NEEDS_OPERATOR':
                store.record_evaluation(attempt_id, {
                    'trigger': trigger,
                    'verdict': 'NEEDS_OPERATOR',
                    'findings': [],
                    'summary': (
                        f'evaluator cap ({EVALUATOR_CAP}) exhausted without'
                        ' PASS — convergence alarm; operator must decide'
                    ),
                })
            last = [
                e for e in evaluations if e.get('verdict') == 'NEEDS_WORK'
            ]
            findings_note = (
                f' last findings: {last[-1].get("summary")}' if last else '')
            return (
                'NEEDS_OPERATOR: evaluator cap'
                f' ({EVALUATOR_CAP}) exhausted without PASS{findings_note}.'
                ' Stop looping — surface to the operator.'
            )
        try:
            record = await evaluator.evaluate(
                ticket_id if ticket_id is not None else _ticket_id_of(attempt_id),
                attempt_id, trigger=trigger, step_index=step_index,
            )
        except Exception as exc:  # noqa: BLE001 — evaluation never kills the tool
            return f'(evaluation failed: {type(exc).__name__}: {exc})'
        return (
            f'evaluation [{trigger}]: {record.get("verdict")} —'
            f' {record.get("summary")}'
        )

    def _ticket_id_of(attempt_id: int) -> int:
        attempt = store._by_id(attempt_id)
        return attempt['ticket_id'] if attempt else 0

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
            step = store.set_step(_attempt(), index, status, command=command,
                                  exit_code=exit_code,
                                  key_output_line=key_output_line)
        except EvidenceError as exc:
            return str(exc)
        result = f'step {index} → {status}' + (
            ' (evidence recorded)' if status == 'done' else ''
        )
        if status == 'done' and step.get('milestone'):
            # DE-2 boundary evaluation: milestones are graded when completed
            # — catching drift mid-course while it is cheap to fix.
            result += '\n' + await _run_evaluation('milestone', step_index=index)
        return result

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
        result = f'attempt #{attempt_id} → {status}'
        if status == 'done':
            # DE-2: the release-boundary evaluation. Non-blocking until the
            # long-run flag lands (#300); the verdict is persisted and loud.
            result += '\n' + await _run_evaluation('release')
        active.pop()
        return result

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

    async def evaluate_work(ticket_id: int) -> str:
        """Run one evaluator pass on the active attempt: a fresh read-only
        session grades the work against this ticket's contract (verdict
        PASS/NEEDS_WORK + findings, persisted on the attempt; capped at 3
        passes per attempt)."""
        return await _run_evaluation('manual', ticket_id=ticket_id)

    async def get_resume_state(ticket_id: int) -> str:
        """Read the resume state for a ticket: who claimed it, plan, per-step progress and evidence."""
        return store.render_resume(ticket_id)

    return FunctionToolset([
        claim_ticket,
        update_execution_step,
        heartbeat_claim,
        release_ticket,
        waive_drift,
        evaluate_work,
        get_resume_state,
    ])
