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
import logging
from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from .config import ThinkingSetting
from .db import utc_now_iso as _now
from .review_gate import collect_review_diff

logger = logging.getLogger(__name__)


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
    db, session_id: str, policy, emit, review_model=None, thinking=None,
    models=None,
) -> FunctionToolset:
    """Agent tools for plan CRUD (propose_plan/update_step).

    `models` is the resolved `[models]` config, threaded to the reviewer so
    it carries the cache capability (R91 #338).
    """
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
            findings = await _run_review(
                db, session_id, review_model, plan, thinking=thinking,
                models=models,
            )
            if findings:
                emit({'type': 'REVIEW_FINDINGS', 'findings': findings})
                return (
                    f'Step marked done. All steps complete — the reviewer flagged:\n'
                    f'{findings}\nAddress these findings before finishing.'
                )
        return f'step {index} → {status}'

    return FunctionToolset([propose_plan, update_step])


async def review_diff_findings(db, session_id: str, config_home, review_model, thinking: ThinkingSetting | None = None, models=None) -> str:
    """On-demand review of the Session's working-tree diff (UI 'Run review')."""
    from .config import config_home as _ch
    from .directives import build_directive_layers

    workdir = db.session_workdir(session_id)
    checklist = build_directive_layers(_ch(), Path(workdir)) if workdir else ''
    return await _review_impl(
        db, session_id, review_model, checklist, plan=None, thinking=thinking,
        models=models,
    )


async def _run_review(db, session_id: str, review_model, plan: dict, thinking: ThinkingSetting | None = None, models=None) -> str:
    """Review pass: diff + plan + directives checklist → findings (or '')."""
    from .config import config_home
    from .directives import build_directive_layers

    workdir = db.session_workdir(session_id)
    checklist = build_directive_layers(config_home(), Path(workdir)) if workdir else ''
    return await _review_impl(
        db, session_id, review_model, checklist, plan=plan, thinking=thinking,
        models=models,
    )


def _capped_diff(diff: str, limit: int = 8000) -> str:
    """Cap the diff for the reviewer, and say when a cap was applied.

    The old silent `diff[:8000]` let a reviewer pass judgement on a range it had
    only partly read — and the range now spans the whole branch, so the cut is
    likelier. An explicit marker keeps the review honest about its own reach.
    """
    if len(diff) <= limit:
        return diff
    return diff[:limit] + f'\n… [{len(diff) - limit} more characters not shown]'


async def _review_impl(db, session_id: str, review_model, checklist: str, plan, thinking: ThinkingSetting | None = None, models=None) -> str:
    from pydantic_ai import Agent
    from pydantic_ai.usage import UsageLimits

    from .agent_caps import ONE_SHOT, cache_capabilities
    from .prompts import load_prompt
    from .tools import build_toolset

    workdir = db.session_workdir(session_id)
    # R92 #339: review the BRANCH, not just the work tree. The old `git diff
    # HEAD` is empty once work is committed — which is exactly when a pre-push
    # review runs — so the seam reviewed nothing and reported CLEAN. The same
    # helper keys the push gate, so one definition decides what "the diff" is.
    diff = collect_review_diff(Path(workdir)) if workdir else ''

    from pydantic_ai.settings import ModelSettings

    settings: ModelSettings = ModelSettings(timeout=300)
    if thinking is not None:
        settings['thinking'] = thinking
    # R90 #335: the reviewer needs repo access to honor its own directives
    # (read the target area, verify before reporting). Same read-only seam as
    # the evaluator: glob/grep/list_dir/read_file against the session workdir.
    # Without it the Agent raised "No tools available" for any read attempt
    # and the directives were unfulfillable by construction.
    toolsets = [build_toolset(Path(workdir), read_only=True)] if workdir else []
    # R91 #338: one-shot cache profile — the reviewer re-sends its long
    # instructions with a different diff every call, so only the prefix is
    # worth caching.
    reviewer_caps = cache_capabilities(models, ONE_SHOT)
    reviewer = Agent(
        model=review_model,
        instructions=load_prompt('review'),
        toolsets=toolsets,
        model_settings=settings,
        capabilities=reviewer_caps,
    )
    plan_section = ''
    if plan:
        plan_section = (
            f'PLAN:\n{plan["goal"]}\n'
            + '\n'.join(f"- {s['text']}" for s in plan['steps'])
            + '\n\n'
        )
    prompt = (
        f'{plan_section}'
        f'DIRECTIVES:\n{checklist[:2000]}\n\nDIFF:\n{_capped_diff(diff)}'
    )
    try:
        # request_limit bounds the read loop so a tool-happy reviewer cannot
        # spin inside the 300s timeout (same pattern as the evaluator pass).
        result = await reviewer.run(prompt, usage_limits=UsageLimits(request_limit=8))
    except Exception as exc:  # noqa: BLE001 — a review failure must not fail the run
        # Returning '' here read as CLEAN: a reviewer that never ran was
        # indistinguishable from one that found nothing (the #266 class). The
        # push gate depends on this being loud, so say what happened.
        logger.warning('review pass failed: %s: %s', type(exc).__name__, exc)
        return (
            'REVIEW FAILED — the reviewer did not run '
            f'({type(exc).__name__}: {exc}). Treat this diff as UNREVIEWED, '
            'never as clean: re-run the review before pushing.'
        )
    output = result.output.strip()
    if output.upper().startswith('CLEAN'):
        return ''
    return output[:2000]
