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
"""R80-4 #296 (DE-2): the evaluator pass — a fresh-context grader.

One WorkEvaluator per run: it gathers the ticket contract, the attempt's
plan + step evidence, and the work diff, then hands all of it to a
read-only delegate session (Anthropic's fresh-context-evaluator primitive:
the session that did the work is the least able to judge it). The delegate
explores read-only and returns a structured verdict through its single
submit_verdict tool — no prose parsing. The verdict record is persisted on
the attempt by the caller (ExecutionStore.record_evaluation); NEEDS_WORK
findings ride the resume render into the next work prompt.

Model resolution (today): subagent → main; the DE-7 registry re-points it
to the evaluator function profile in #299. No model → callers skip with an
honest note; evaluation is never fabricated.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .db import Database
from .execution import ExecutionStore
from .tools import build_toolset, run_captured

logger = logging.getLogger(__name__)

#: Bounded context: the diff the evaluator sees (chars).
_DIFF_CAP = 20_000


def resolve_evaluator_model(subagent_model, main_model):
    """The evaluator's model today: explicit subagent slot → main run model.
    Both None → the caller skips evaluation honestly (never fabricated)."""
    return subagent_model or main_model or None


def resolve_evaluator_from_config(config, model_resolver=None):
    """The evaluator's model from its DE-7a function profile (#298).

    When `[models.functions.evaluator]` sets an explicit model, resolve it
    through `model_resolver` (default: the engine's `_model_from_name`
    seam, lazy-imported — plugins must not import engine at module level)
    and return `(model, parsed_thinking)`; the profile thinking is gated by
    `supports_thinking` like every other thinking setting. Without an
    explicit profile model, returns `(None, None)` and the caller falls
    back to the `resolve_evaluator_model` chain (subagent → main), which
    stays byte-compatible with pre-#298 behavior.
    """
    entry = config.models.functions.get('evaluator')
    if entry is None or not entry.model:
        return None, None

    def _default_resolver(name: str):
        from .engine import _model_from_name

        return _model_from_name(
            name, config.models.fallback_base_url, config.providers)

    model = (model_resolver or _default_resolver)(entry.model)
    thinking = None
    if entry.thinking is not None:
        from .config import parse_thinking
        from .run_pipeline import supports_thinking

        parsed = parse_thinking(entry.thinking)
        if parsed is not None and supports_thinking(model):
            thinking = parsed
    return model, thinking


def _ticket_contract(db: Database, workdir: str, ticket_id: int) -> str:
    row = db._conn.execute(
        'SELECT title, body FROM tickets WHERE id = ? AND workdir = ?',
        (ticket_id, workdir),
    ).fetchone()
    if row is None:
        return f'(ticket #{ticket_id} not found)'
    return f'ticket #{ticket_id}: {row["title"]}\n{row["body"] or ""}'


class WorkEvaluator:
    """Grades work against the ticket contract with a fresh read-only
    session; the verdict record is returned for the caller to persist."""

    def __init__(
        self, db: Database, workdir: Path, model,
        thinking=None, delegation_config=None, db_session: str = '',
        models=None,
    ) -> None:
        self.db = db
        self.workdir = Path(workdir)
        self.model = model
        self.thinking = thinking
        self.max_requests = getattr(delegation_config, 'max_requests', 12)
        self.db_session = db_session
        # R91 #338: one-shot cache profile — every grading pass re-sends the
        # same long instructions over a different ticket/diff.
        from .agent_caps import ONE_SHOT, cache_capabilities

        self._cache_capabilities = cache_capabilities(models, ONE_SHOT)

    def _attempt_summary(self, store: ExecutionStore, attempt_id: int) -> str:
        attempt = store._by_id(attempt_id)
        if attempt is None:
            return '(no attempt record)'
        steps = attempt['steps_json']
        evidence_lines = []
        for i, step in enumerate(json_steps(steps)):
            status = step.get('status', 'todo')
            line = f'- step {i} [{status}] {step.get("text", "")}'
            ev = step.get('evidence')
            if ev:
                line += f' — evidence: {ev}'
            evidence_lines.append(line)
        return '\n'.join(evidence_lines) or '(no steps recorded)'

    async def _work_diff(self) -> str:
        """The work the evaluator grades: tracked diff + untracked files
        (with bounded contents — `git diff HEAD` alone hides new files).
        Strictly read-only: no `git add -N` index mutation."""
        parts: list[str] = []
        cap = await run_captured(
            ['git', 'diff', 'HEAD'], cwd=self.workdir, timeout=60)
        if cap is None:
            parts.append('(diff unavailable — timed out)')
        elif cap.code != 0:
            # not a git repo (or broken): say so, never feed raw stderr
            # to the grader as if it were a diff
            parts.append('(no git diff available — grade from repo reads)')
        elif cap.combined.strip():
            parts.append(cap.combined[:12_000])
        status = await run_captured(
            ['git', 'ls-files', '--others', '--exclude-standard'],
            cwd=self.workdir, timeout=30)
        untracked = (
            [ln for ln in (status.stdout or '').splitlines() if ln.strip()]
            if status is not None and status.code == 0 else []
        )
        if untracked:
            parts.append(
                'untracked files (new work): ' + ', '.join(untracked[:50]))
            shown = 0
            for name in untracked:
                if shown >= 5:
                    parts.append(f'(… {len(untracked) - 5} more untracked)')
                    break
                target = self.workdir / name
                try:
                    text = target.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                parts.append(f'--- {name} (untracked, first 4000 chars)\n'
                             f'{text[:4000]}')
                shown += 1
        return '\n'.join(parts)[:_DIFF_CAP] if parts else '(empty diff)'

    def _bill(self, usage) -> None:
        if not self.db_session:
            return
        try:
            cost = getattr(usage, 'cost', None)
            self.db.record_usage(
                self.db_session,
                model=str(getattr(self.model, 'model_name', self.model)),
                requests=getattr(usage, 'requests', 0) or 0,
                input_tokens=getattr(usage, 'input_tokens', 0) or 0,
                output_tokens=getattr(usage, 'output_tokens', 0) or 0,
                cost_usd=float(cost) if cost is not None else None,
                # M6 (#298): evaluator spend is tagged to its function so
                # cost attribution per function works.
                function_name='evaluator',
            )
        except Exception:  # noqa: BLE001 — accounting must never fail grading
            logger.warning('evaluator usage billing failed', exc_info=True)

    async def evaluate(
        self, ticket_id: int, attempt_id: int, trigger: str,
        step_index: int | None = None,
    ) -> dict:
        """One grading pass; returns the verdict record (the caller
        persists it via ExecutionStore.record_evaluation)."""
        import uuid as _uuid

        from pydantic_ai import Agent
        from pydantic_ai.exceptions import UsageLimitExceeded
        from pydantic_ai.settings import ModelSettings
        from pydantic_ai.toolsets import FunctionToolset
        from pydantic_ai.usage import UsageLimits

        from .prompts import load_prompt
        from .tool_errors import error_feedback_toolset

        store = ExecutionStore(self.db, str(self.workdir))
        contract = _ticket_contract(self.db, str(self.workdir), ticket_id)
        evidence = self._attempt_summary(store, attempt_id)
        diff = await self._work_diff()
        # The rubric lives in the agent instructions; the prompt carries the
        # graded artifacts (contract, evidence, diff) — stated once each.
        prompt = (
            f'## Ticket contract\n{contract}\n\n'
            f'## Claimed plan and step evidence\n{evidence}\n\n'
            f'## Work diff\n{diff}\n\n'
            'Grade this work now: explore the repo read-only if you need '
            'more context, then call submit_verdict exactly once.'
        )

        captured: dict = {}

        async def submit_verdict(verdict: str, findings: list[dict],
                                 summary: str) -> str:
            captured['record'] = {
                'trigger': trigger,
                'step_index': step_index,
                'verdict': verdict,
                'findings': findings,
                'summary': summary,
            }
            return 'verdict recorded'

        settings: ModelSettings = ModelSettings(timeout=300)
        if self.thinking is not None:
            settings['thinking'] = self.thinking
        toolsets = [error_feedback_toolset([
            build_toolset(self.workdir, read_only=True),
            FunctionToolset([submit_verdict]),
        ])]
        agent = Agent(
            model=self.model,
            instructions=load_prompt('evaluator'),
            toolsets=toolsets,
            model_settings=settings,
            capabilities=self._cache_capabilities,
        )
        eval_id = 'eval-' + _uuid.uuid4().hex[:8]
        try:
            result = await agent.run(
                prompt, usage_limits=UsageLimits(request_limit=self.max_requests),
            )
        except UsageLimitExceeded:
            captured['record'] = {
                'trigger': trigger,
                'step_index': step_index,
                'verdict': 'NEEDS_WORK',
                'findings': [],
                'summary': (
                    'evaluator session exceeded its request budget before '
                    'submitting a verdict'
                ),
            }
        else:
            self._bill(result.usage)
        record = captured.get('record') or {
            'trigger': trigger,
            'step_index': step_index,
            # Skeptical default: no verdict submitted is never a PASS.
            'verdict': 'NEEDS_WORK',
            'findings': [],
            'summary': 'evaluator session produced no verdict',
        }
        record.setdefault('verdict', 'NEEDS_WORK')
        record['verdict'] = (
            'PASS' if record['verdict'] == 'PASS' else 'NEEDS_WORK'
        )
        # Findings contract is {file, symbol?, note, severity}; live models
        # use varied prose keys (type/description/expected/...) — fold the
        # first alternative into `note` so resume rendering stays uniform.
        for f in record.get('findings', []):
            if not f.get('note'):
                for alt in ('description', 'verdict_detail', 'expected',
                            'type', 'message'):
                    if f.get(alt):
                        f['note'] = str(f[alt])
                        break
        store.record_evaluation(attempt_id, record)
        logger.info(
            'EVALUATION %s ticket=%s attempt=%s verdict=%s findings=%d',
            eval_id, ticket_id, attempt_id, record['verdict'],
            len(record.get('findings', [])),
        )
        return record


def json_steps(raw: str) -> list[dict]:
    import json

    return json.loads(raw)
