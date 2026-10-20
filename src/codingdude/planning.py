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
"""Planning mode: propose → approve → execute with tracked steps → review.

The `propose_plan` tool starts the split: the plan persists, the user approves
(interactive) or the run aborts with the plan as its report (headless,
ADR-0003). Steps are tracked via `update_step`; completing the last step
triggers an automatic review pass whose findings go back to the model.
"""

import json
from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from .config import ThinkingSetting
from .db import utc_now_iso as _now


class PlanStore:
    """SQLite-backed store of plans, plan steps, and their statuses."""
    def __init__(self, db):
        self.db = db

    def create(self, session_id: str, goal: str, steps: list[str]) -> int:
        cur = self.db._conn.execute(
            'INSERT INTO plans (session_id, goal, steps, status, created_at)'
            " VALUES (?, ?, ?, 'approved', ?)",
            (
                session_id,
                goal,
                json.dumps([{'text': s, 'status': 'todo'} for s in steps]),
                _now(),
            ),
        )
        self.db._conn.commit()
        return cur.lastrowid

    def latest(self, session_id: str) -> dict | None:
        row = self.db._conn.execute(
            'SELECT * FROM plans WHERE session_id = ? ORDER BY id DESC LIMIT 1',
            (session_id,),
        ).fetchone()
        if not row:
            return None
        plan = dict(row)
        plan['steps'] = json.loads(plan['steps'])
        return plan

    def set_step_status(self, plan_id: int, index: int, status: str) -> dict | None:
        plan = self._by_id(plan_id)
        if not plan or not (0 <= index < len(plan['steps'])):
            return None
        plan['steps'][index]['status'] = status
        all_done = all(s['status'] == 'done' for s in plan['steps'])
        plan_status = 'done' if all_done else 'in_progress'
        self.db._conn.execute(
            'UPDATE plans SET steps = ?, status = ? WHERE id = ?',
            (json.dumps(plan['steps']), plan_status, plan_id),
        )
        self.db._conn.commit()
        plan['status'] = plan_status
        return plan

    def set_status(self, plan_id: int, status: str) -> None:
        self.db._conn.execute(
            'UPDATE plans SET status = ? WHERE id = ?', (status, plan_id)
        )
        self.db._conn.commit()

    def _by_id(self, plan_id: int) -> dict | None:
        row = self.db._conn.execute(
            'SELECT * FROM plans WHERE id = ?', (plan_id,)
        ).fetchone()
        if not row:
            return None
        plan = dict(row)
        plan['steps'] = json.loads(plan['steps'])
        return plan


def build_planning_toolset(
    db, session_id: str, policy, emit, review_model=None, thinking=None
) -> FunctionToolset:
    """Agent tools for plan CRUD (propose_plan/update_step)."""
    store = PlanStore(db)
    emit = emit or (lambda event: None)

    async def propose_plan(
        goal: str, steps: list[str], files_to_touch: list[str], risks: str
    ) -> str:
        """Propose a plan for a non-trivial task. Steps must be concrete and ordered."""
        plan_id = store.create(session_id, goal, steps)
        emit({
            'type': 'PLAN_PROPOSED',
            'goal': goal,
            'steps': steps,
            'files_to_touch': files_to_touch,
            'risks': risks,
        })
        # Interactive: wait for the decision. Headless: abort with the plan
        # as the report (ADR-0003).
        from .approvals import NEEDS_GATE

        if policy is None:
            from .tools import GateRequired

            raise GateRequired(f'plan approval: {goal}')
        decision = policy.decide(f'plan: {goal}')
        if decision == NEEDS_GATE:
            if policy.ask is None:
                from .tools import GateRequired

                raise GateRequired(f'plan approval: {goal}')
            answer = await policy.ask(f'plan: {goal}')
            if answer == 'deny':
                store.set_status(plan_id, 'rejected')
                raise ModelRetry(
                    'The user REJECTED this plan. Revise the approach — '
                    'do not simply re-propose the same plan.'
                )
            store.set_status(plan_id, 'approved')
            emit({'type': 'PLAN_APPROVED', 'plan_id': plan_id})
        return (
            f'Plan approved (id {plan_id}). Execute the steps one by one, calling '
            f'update_step(index, "done") as each completes.'
        )

    async def update_step(index: int, status: str) -> str:
        """Mark a plan step 'done' or 'in_progress' (index is 0-based)."""
        plan = store.latest(session_id)
        if not plan:
            raise ModelRetry('No plan exists — call propose_plan first.')
        updated = store.set_step_status(plan['id'], index, status)
        if not updated:
            raise ModelRetry(f'Step index {index} is out of range.')
        emit({
            'type': 'PLAN_STEP',
            'index': index,
            'status': status,
            'text': updated['steps'][index]['text'],
        })
        if updated['status'] == 'done' and review_model is not None:
            findings = await _run_review(db, session_id, review_model, plan, thinking=thinking)
            if findings:
                emit({'type': 'REVIEW_FINDINGS', 'findings': findings})
                return (
                    f'Step marked done. All steps complete — the reviewer flagged:\n'
                    f'{findings}\nAddress these findings before finishing.'
                )
        return f'step {index} → {status}'

    return FunctionToolset([propose_plan, update_step])


async def review_diff_findings(db, session_id: str, config_home, review_model, thinking: ThinkingSetting | None = None) -> str:
    """On-demand review of the Session's working-tree diff (UI 'Run review')."""
    from .config import config_home as _ch
    from .directives import build_directive_layers

    workdir = db.session_workdir(session_id)
    checklist = build_directive_layers(_ch(), Path(workdir)) if workdir else ''
    return await _review_impl(db, session_id, review_model, checklist, plan=None, thinking=thinking)


async def _run_review(db, session_id: str, review_model, plan: dict, thinking: ThinkingSetting | None = None) -> str:
    """Review pass: diff + plan + directives checklist → findings (or '')."""
    from .config import config_home
    from .directives import build_directive_layers

    workdir = db.session_workdir(session_id)
    checklist = build_directive_layers(config_home(), Path(workdir)) if workdir else ''
    return await _review_impl(db, session_id, review_model, checklist, plan=plan, thinking=thinking)


async def _review_impl(db, session_id: str, review_model, checklist: str, plan, thinking: ThinkingSetting | None = None) -> str:
    import subprocess

    from pydantic_ai import Agent

    workdir = db.session_workdir(session_id)
    diff = ''
    if workdir:
        # encoding + errors: diffs may contain bytes invalid in the platform
        # ANSI codepage; a cp1252 decode failure kills the reader thread and
        # leaves stdout=None (crashed the review with TypeError).
        diff_process = subprocess.run(
            ['git', 'diff', 'HEAD'], cwd=workdir, capture_output=True,
            encoding='utf-8', errors='replace', timeout=30,
        )
        diff = diff_process.stdout or ''

    from pydantic_ai.settings import ModelSettings

    settings: ModelSettings = ModelSettings(timeout=300)
    if thinking is not None:
        settings['thinking'] = thinking
    reviewer = Agent(model=review_model, model_settings=settings)
    plan_section = ''
    if plan:
        plan_section = (
            f'PLAN:\n{plan["goal"]}\n'
            + '\n'.join(f"- {s['text']}" for s in plan['steps'])
            + '\n\n'
        )
    prompt = (
        f'{plan_section}'
        f'DIRECTIVES:\n{checklist[:2000]}\n\nDIFF:\n{diff[:8000]}'
    )
    try:
        result = await reviewer.run(prompt)
    except Exception:  # noqa: BLE001 — review must never fail the run
        return ''
    output = result.output.strip()
    if output.upper().startswith('CLEAN'):
        return ''
    return output[:2000]
