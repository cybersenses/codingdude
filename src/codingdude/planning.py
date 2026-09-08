"""Planning mode: propose → approve → execute with tracked steps → review.

The `propose_plan` tool starts the split: the plan persists, the user approves
(interactive) or the run aborts with the plan as its report (headless,
ADR-0003). Steps are tracked via `update_step`; completing the last step
triggers an automatic review pass whose findings go back to the model.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PlanStore:
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
    db, session_id: str, policy, emit, review_model=None
) -> FunctionToolset:
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
            findings = await _run_review(db, session_id, review_model, plan)
            if findings:
                emit({'type': 'REVIEW_FINDINGS', 'findings': findings})
                return (
                    f'Step marked done. All steps complete — the reviewer flagged:\n'
                    f'{findings}\nAddress these findings before finishing.'
                )
        return f'step {index} → {status}'

    return FunctionToolset([propose_plan, update_step])


async def _run_review(db, session_id: str, review_model, plan: dict) -> str:
    """Review pass: diff + plan + directives checklist → findings (or '')."""
    import subprocess
    from pydantic_ai import Agent

    from .directives import build_directive_layers
    from .config import config_home

    workdir = db.session_workdir(session_id)
    diff = ''
    if workdir:
        diff_process = subprocess.run(
            ['git', 'diff', 'HEAD'], cwd=workdir, capture_output=True, text=True, timeout=30
        )
        diff = diff_process.stdout
    checklist = build_directive_layers(config_home(), Path(workdir)) if workdir else ''

    reviewer = Agent(model=review_model)
    prompt = (
        'You are a code reviewer. Review this diff against the plan and the '
        'project directives. Report concrete findings only (bugs, standard '
        'violations, missing tests), one per line prefixed "- ". If the work '
        'is clean, return exactly: CLEAN\n\n'
        f'PLAN:\n{plan["goal"]}\n'
        + '\n'.join(f"- {s['text']}" for s in plan['steps'])
        + f'\n\nDIRECTIVES:\n{checklist[:2000]}\n\nDIFF:\n{diff[:8000]}'
    )
    try:
        result = await reviewer.run(prompt)
    except Exception:  # noqa: BLE001 — review must never fail the run
        return ''
    output = result.output.strip()
    if output.upper().startswith('CLEAN'):
        return ''
    return output[:2000]
