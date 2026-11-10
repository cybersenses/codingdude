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
"""The three run seams extracted from Engine (arch review, Candidate 2).

`Engine.run` stays the sole orchestrator; these modules own the three
responsibilities it used to inline:

- `RunServices` — shared accounting (usage, budget, request limits).
- `PromptAssembler` — instructions + model settings + Agent construction.
- `HistoryManager` — load/persist/compact history + context accounting.
- `PostRunPipeline` — everything after the agent run (usage, memory
  extraction, claim verification, budget re-check).

Ordering of steps inside `Engine.run` is unchanged; these are pure
ownership moves, not behavior changes.
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model

logger = logging.getLogger(__name__)

# Post-run LLM passes (memory extraction, claim audit) are best-effort and
# must never wedge the run's tail: bound them.
# ponytail: flat 120s; per-model tuning only if legit audits start timing out.
_POST_RUN_LLM_TIMEOUT_S = 120

#: Tools whose results carry verification evidence for the claims audit
#: (#312): evaluate_work/submit_verdict verdicts were invisible, so true
#: 'Evaluator verdict: PASS' claims got challenged. Review round on
#: c19464f: auto-release verdicts ride on release_ticket/update_execution_
#: step results, delegated evidence arrives as the delegate tool's final
#: report — all three added. submit_verdict is kept defensively: its
#: ToolReturnPart never persists today (the evaluator agent's messages are
#: throwaway; the verdict lands in evaluations_json), but the name is
#: evidence-shaped if that ever changes.
_AUDIT_EVIDENCE_TOOLS = frozenset({
    'shell', 'run_coverage', 'evaluate_work', 'submit_verdict',
    'release_ticket', 'update_execution_step', 'delegate',
})
#: Per-entry budget — keep the TAIL of each result: gate verdicts
#: ('7 passed', 'clean') sit at the end of long outputs; the old head
#: slice (~120 chars) hid exactly the lines that verify a claim. Honest
#: trade: for results longer than this budget the leading 'exit code: N'
#: header falls off (the old head slice always kept it) — pass/fail is
#: still visible via the tail's verdict lines; silent-success commands
#: (empty output) keep their header whole.
_AUDIT_ENTRY_CHARS = 600
#: Overall evidence window (was 4000 — one long gate output evicted
#: everything else). Newest entries survive the cap; old ones fall off,
#: matching how the final summary cites its most recent checks.
_AUDIT_WINDOW_CHARS = 12000


class RunServices:
    """Shared per-run services: DB access, config, accounting helpers.

    One home for the billing/budget seam so HistoryManager and
    PostRunPipeline don't each need a back-reference to the Engine.
    """

    def __init__(self, config, db, config_home: Path,
                 extraction_model: 'Callable[[], Model | None]',
                 budget_cap_usd: float | None = None) -> None:
        self._config = config
        self._db = db
        self._config_home = config_home
        # Extraction model resolved lazily: it can be attached to the Engine
        # after construction (tests, worker wiring).
        self._get_extraction_model = extraction_model
        self._budget_cap_usd = budget_cap_usd

    @property
    def db(self):
        return self._db

    @property
    def config(self):
        return self._config

    @property
    def config_home(self) -> Path:
        return self._config_home

    @property
    def extraction_model(self) -> Model | None:
        return self._get_extraction_model()

    def check_budget(self, session_id: str) -> None:
        """Hard-stop the session once spend crosses the cap (off by default;
        never bypassed by --yolo)."""
        if self._budget_cap_usd is None:
            return
        from .exceptions import BudgetExceeded

        totals = self._db.session_usage(session_id)
        spent = totals.get('cost_usd') or 0.0
        if spent >= self._budget_cap_usd:
            raise BudgetExceeded(spent_usd=spent, cap_usd=self._budget_cap_usd)

    def record_model_usage(self, session_id: str, model, usage) -> None:
        """Bill an auxiliary model call to the Session (self-review H6).

        Compaction, memory extraction, claim verification and fix-loop
        retries are real spend; leaving them out under-counted the cost
        meter and let the Budget Cap be exceeded.
        """
        try:
            cost = getattr(usage, 'cost', None)
            self._db.record_usage(
                session_id,
                model=str(getattr(model, 'model_name', model)),
                requests=getattr(usage, 'requests', 0) or 0,
                input_tokens=getattr(usage, 'input_tokens', 0) or 0,
                output_tokens=getattr(usage, 'output_tokens', 0) or 0,
                cost_usd=float(cost) if cost is not None else None,
            )
        except Exception:  # noqa: BLE001 - accounting must never fail a run
            logger.warning(
                'usage recording failed for session %s', session_id, exc_info=True
            )

    def usage_limits(self):
        """Per-run request cap (config `models.request_limit`, default 500).

        Without an explicit limit pydantic-ai applies its library default of
        50 model requests per run, which kills long agentic sessions with
        'would exceed the request_limit of 50'.
        """
        from pydantic_ai.usage import UsageLimits

        return UsageLimits(request_limit=self._config.models.request_limit)


class PromptAssembler:
    """System instructions + model settings + Agent construction."""

    def instructions(self, services: RunServices, workdir: Path, prompt: str,
                     registry, store, embedder) -> str:
        """System instructions: base + repo map + directive layers + skills
        index (with auto-triggered bodies) + relevant Memory."""
        from .prompts import load_prompt

        instructions = load_prompt('base_instructions')

        from .guidance import contract_block, platform_block

        instructions += platform_block(workdir) + contract_block()
        from .repo_map import build_repo_map

        repo_map_text = build_repo_map(workdir)
        if repo_map_text:
            instructions += (
                '\n\n## Repository overview (auto-generated map)\n' + repo_map_text
            )
        from .directives import build_directive_layers

        directive_layers = build_directive_layers(services.config_home, workdir)
        if directive_layers:
            instructions += '\n\n' + directive_layers

        skills_index = registry.index()
        if skills_index:
            lines = '\n'.join(
                f"- {s['name']}: {s['description']}" for s in skills_index
            )
            instructions += (
                '\n\n## Skills (procedures you can load)\n'
                'Scan this index before every response. If any skill matches the '
                'request — by name, description, or topic — call load_skill(name) '
                'BEFORE acting and follow it. Loading a matching skill is mandatory, '
                'not optional:\n'
                + lines
            )
            triggered = registry.matching(prompt)
            if triggered:
                preloaded = '\n\n'.join(
                    f"### Pre-loaded skill: {s['name']} (auto-triggered by this request)\n\n"
                    + s['body']
                    for s in triggered
                )
                instructions += (
                    '\n\n## Skills auto-triggered by this request\n'
                    'The matching skill bodies are already loaded here — follow them '
                    'now. Call load_skill only for a companion file or a different '
                    'skill from the index.\n\n' + preloaded
                )
        # R49 referential solutions: always injected (forced recall), bounded;
        # excluded from the RAG Memory block below so nothing double-injects.
        solutions = store.solutions(str(workdir))
        if solutions:
            lines = '\n'.join(f'- {s["content"][:500]}' for s in solutions)[:6000]
            instructions += (
                '\n\n## Referential solutions (solved problems; consult these '
                'before re-diagnosing a known issue, and record_solution when '
                'you solve something new):\n' + lines
            )
        if embedder is not None:
            relevant = [
                content
                for content, _score in store.retrieve_semantic(
                    embedder, str(workdir), query=prompt, kind='fact'
                )
            ]
        else:
            relevant = [
                e['content'] for e in store.retrieve(
                    str(workdir), query=prompt, kind='fact'
                )
            ]
        if relevant:
            lines = '\n'.join(f'- {c}' for c in relevant)
            instructions += (
                '\n\nMemory (durable facts from earlier sessions; respect them):\n'
                + lines
            )
        from .onboarding import onboarding_block, onboarding_needed

        if onboarding_needed(store, workdir):
            instructions += '\n\n' + onboarding_block(workdir)
        return instructions

    def model_settings(
        self, services: RunServices, resolved: Model, thinking,
    ):
        """ModelSettings for the run: timeout, token cap, thinking flag."""
        from pydantic_ai.settings import ModelSettings

        model_settings: ModelSettings = ModelSettings(timeout=300, max_tokens=65536)
        if services.config.models.max_tokens:
            model_settings['max_tokens'] = services.config.models.max_tokens
        if thinking is not None and supports_thinking(resolved):
            model_settings['thinking'] = thinking
        return model_settings

    def agent(self, resolved: Model, instructions: str, toolsets, settings=None,
              retries: int = 5) -> Agent:
        """The run's Agent: model + instructions + toolsets + settings.

        R25: tool retries — errors are fed back to the model (see
        codingdude.tool_errors) and only stop the run when the consecutive
        failure budget is spent. Default raised 3 -> 5 (gate diff-scope):
        deterministic edit failures (gate findings, staleness races with a
        concurrent writer) were exhausting the old budget before the model
        could re-read and adapt.
        """
        return Agent(
            model=resolved, instructions=instructions, toolsets=toolsets,
            model_settings=settings, retries=retries,
        )


_THINKING_PROVIDERS = ('glm', 'deepseek')


def supports_thinking(model: Model) -> bool:
    """True when the model (or any failover target) accepts the unified
    `thinking` setting: ZAI GLM and DeepSeek (V4/flash) profiles."""
    candidates: list[Model] = [model]
    candidates.extend(getattr(model, 'models', ()) or ())  # FallbackModel
    for m in candidates:
        if type(m).__name__ == 'ZaiModel':
            return True
        name = str(getattr(m, 'model_name', '')).lower()
        if any(p in name for p in _THINKING_PROVIDERS):
            return True
    return False


class HistoryManager:
    """Load, compact, persist and account for run history."""

    def __init__(self, services: RunServices, compaction_threshold: int | None) -> None:
        self._services = services
        self._compaction_threshold = compaction_threshold

    def load(self, session_id: str) -> list:
        """Decoded, sanitized history for the session (may be empty)."""
        from .messages import decode_messages, sanitize_history

        return sanitize_history(
            decode_messages(self._services.db.load_messages(session_id))
        )

    def persist(self, session_id: str, msgs) -> None:
        from .messages import encode_messages

        self._services.db.replace_messages(
            session_id, [encode_messages([m]) for m in msgs]
        )

    def context_manager(self, model_name: str):
        """The ContextManager for the resolved model: per-model context limit
        (config override wins; see context.model_limit_for)."""
        from .context import ContextManager, model_limit_for

        return ContextManager(
            model_limit=model_limit_for(
                model_name, self._services.config.models.context_limit
            )
        )

    async def maybe_compact(self, history, resolved: Model, on_event,
                            session_id: str, cm=None):
        """Compact old turns into a summary when history approaches the
        model's context window (token-based) or the legacy char threshold.

        Returns (history, compacted?) — compacted True means history changed.
        """
        if len(history) < 3:
            return history, False
        over_tokens = cm is not None and cm.usage(history).needs_compaction
        from .messages import encode_messages

        over_chars = (
            self._compaction_threshold is not None
            and sum(len(encode_messages([m])) for m in history) > self._compaction_threshold
        )
        if not (over_tokens or over_chars):
            return history, False

        from pydantic_ai.messages import ModelRequest, UserPromptPart

        # Importance-based retention (R3): recent + high-importance messages
        # stay verbatim; everything else is summarised.
        keep_idx, summarise_idx = cm.plan_compaction(history) if cm is not None else (
            [len(history) - 1], list(range(len(history) - 1))
        )
        if not summarise_idx:
            # Everything scored as recent/high-importance (e.g. a history of
            # short user prompts): retention would keep the overflow, so fall
            # back to the last message verbatim.
            old, keep = history[:-1], history[-1:]
        else:
            old = [history[i] for i in summarise_idx]
            keep = [history[i] for i in keep_idx]
        digest = '\n'.join(
            f'- {p.content}'
            for m in old
            for p in m.parts
            if hasattr(p, 'content') and p.content
        )
        summarizer: Agent = Agent(model=resolved)
        summary_result = await summarizer.run(
            'Summarize the key facts and decisions of this conversation '
            f'for continuity, in at most 200 words:\n\n{digest[:8000]}'
        )
        summary = summary_result.output
        self._services.record_model_usage(session_id, resolved, summary_result.usage)
        # RAG: the summary becomes retrievable Memory, so facts that fell out
        # of the window resurface in future runs' instructions (R3).
        try:
            from .memory import MemoryStore

            MemoryStore(self._services.db).add(
                f'Compacted conversation summary: {summary}',
                scope='workdir',
                workdir=self._services.db.session_workdir(session_id) or '',
            )
        except Exception as exc:  # noqa: BLE001 - retrieval must not fail compaction
            logger.warning('compaction summary not stored as memory: %s', exc)
        compacted = [
            ModelRequest(
                parts=[UserPromptPart(content=f'[Earlier conversation, compacted]\n{summary}')]
            )
        ] + keep
        if on_event:
            from .events import CompactionCheckpoint

            on_event(
                CompactionCheckpoint(
                    kind='compaction', summarized_messages=len(old), summary=summary
                )
            )
        return compacted, True

    def persist_actual_context(self, session_id: str, result, cm) -> None:
        """Refresh the session's context snapshot with the run's final usage.

        The provider-reported input tokens of the last request are the true
        context size (instructions + full history); the estimate is the
        fallback when usage isn't reported. Accounting must never fail a run.
        """
        try:
            response = getattr(result, 'response', None)
            usage = getattr(response, 'usage', None)
            input_tokens = getattr(usage, 'input_tokens', None)
            messages = result.all_messages()
            estimated = cm.usage(messages).total_tokens
            total = (
                input_tokens
                if isinstance(input_tokens, int) and input_tokens > 0
                else estimated
            )
            self._services.db.update_session_context(
                session_id, total, cm.model_limit
            )
        except Exception as exc:  # noqa: BLE001 - accounting must never fail a run
            logger.warning('context snapshot not persisted: %s', exc)


class PostRunPipeline:
    """Everything that happens after the agent run returns."""

    def __init__(self, services: RunServices) -> None:
        self._services = services

    def record_run_usage(self, session_id: str, model_name: str, usage,
                         started, emit) -> None:
        """Bill the run (usage row + RUN_USAGE trace event with duration).

        `usage` is the combined RunUsage for EVERY request the run made
        (main + fix-loop retries, #81) — one accounting pass, no double count.
        """
        from datetime import UTC as _UTC
        from datetime import datetime as _dt

        from .telemetry import run_usage_event

        run_cost = float(usage.cost) if usage.cost is not None else None
        self._services.db.record_usage(
            session_id,
            model=model_name,
            requests=usage.requests or 0,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cost_usd=run_cost,
        )
        emit(run_usage_event(
            model_name=model_name,
            requests=usage.requests or 0,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cost_usd=run_cost,
            duration_s=(_dt.now(_UTC) - started).total_seconds(),
            pricing=self._services.config.models.pricing,
        ))

    async def extract_memory(self, session_id: str, workdir: Path,
                             emit=None) -> None:
        """Post-session pass: bank durable facts the run didn't explicitly remember
        and retire entries this session made obsolete (via `FORGET:` lines)."""
        extraction_model = self._services.extraction_model
        if extraction_model is None:
            return
        if emit:
            emit({'type': 'MEMORY_EXTRACTING'})
        from .memory import MemoryStore

        store = MemoryStore(self._services.db)
        known = store.all_entries()
        known_lines = '\n'.join(f"- {e['content']}" for e in known[:25])
        # Input is trimmed (R30): the single extraction call is latency-bound,
        # and 6k chars of transcript covers the run's tail, where the facts are.
        transcript = '\n'.join(self._services.db.load_messages(session_id))[:6000]
        agent: Agent = Agent(model=extraction_model)
        try:
            result = await asyncio.wait_for(agent.run(
                'From this conversation transcript, extract durable facts worth '
                'remembering for future sessions (preferences, project facts, '
                'decisions). One fact per line, no numbering. Do not restate a '
                'fact already in the known entries below. If a known entry became '
                'obsolete or was completed during this conversation, emit a line '
                'exactly `FORGET: <distinctive substring of that entry>` so it is '
                'deleted. Return only lines worth keeping — if none, return '
                'nothing.\n\nKnown entries:\n'
                + known_lines
                + '\n\nTranscript:\n'
                + transcript
            ), timeout=_POST_RUN_LLM_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — extraction must never fail a run
            logging.getLogger(__name__).warning(
                'memory extraction failed for session %s', session_id, exc_info=True
            )
            return
        if emit:
            emit({'type': 'MEMORY_EXTRACTED'})
        self._services.record_model_usage(session_id, extraction_model, result.usage)
        for line in result.output.splitlines():
            line = line.strip().lstrip('-•* ')
            if not line:
                continue
            if line.upper().startswith('FORGET:'):
                substring = line[len('FORGET:'):].strip()
                if substring:
                    store.delete_substring(substring)
                continue
            if store.duplicate_ids(line):
                continue
            store.add(line, scope='workdir', workdir=str(workdir))

    async def verify_claims(self, session_id: str, result, workdir: Path,
                            approvals, emit, resolved=None, history=None,
                            instructions=None) -> None:
        """Anti-slop: cross-check the final summary's verification claims against
        recorded tool results; re-execute explicitly claimed verifications once;
        give the model one round to address unsupported claims."""
        from pydantic_ai import Agent

        from .messages import decode_messages, encode_messages
        from .prompts import load_prompt

        extraction_model = self._services.extraction_model
        if extraction_model is None:
            return
        if emit:
            emit({'type': 'CLAIMS_CHECKING'})

        final_text = result.output
        payloads = decode_messages(self._services.db.load_messages(session_id))
        tool_results = []
        for m in payloads:
            for part in m.parts:
                name = getattr(part, 'tool_name', None)
                if name in _AUDIT_EVIDENCE_TOOLS:
                    tail = str(getattr(part, 'content', ''))[
                        -_AUDIT_ENTRY_CHARS:]
                    tool_results.append(f'{name}: {tail}')

        auditor = Agent(model=extraction_model)
        audit_prompt = (
            load_prompt('claim_check')
            + '\n\nSUMMARY:\n'
            + final_text[:3000]
            + '\n\nRECORDED COMMAND RESULTS:\n'
            + ('\n'.join(tool_results)[-_AUDIT_WINDOW_CHARS:]
               if tool_results else '(none recorded)')
        )
        try:
            audit = await asyncio.wait_for(
                auditor.run(audit_prompt), timeout=_POST_RUN_LLM_TIMEOUT_S
            )
        except Exception:  # noqa: BLE001 — verification must never fail the run
            # Review finding on b3817ad: this half previously returned bare,
            # leaving CLAIMS_CHECKING with no terminal event and no log —
            # the same silent-catch class the retry half was fixed for (#23).
            logger.warning(
                'claims audit failed for session %s; claims remain unverified',
                session_id, exc_info=True,
            )
            if emit:
                emit({'type': 'CLAIMS_UNVERIFIED', 'reason': 'audit_failed'})
            return
        self._services.record_model_usage(session_id, extraction_model, audit.usage)
        unsupported = [
            line.strip().lstrip('-•* ')
            for line in audit.output.splitlines()
            if line.strip() and not line.strip().upper().startswith('CLEAN')
        ]
        if not unsupported:
            if emit:
                emit({'type': 'CLAIMS_VERIFIED'})
            return

        findings = 'The reviewer could not verify these claims:\n' + '\n'.join(
            f'- {c}' for c in unsupported
        )
        # One retry round: the model gets the findings plus the conversation so
        # far, and must back the claims with real commands or correct itself.
        # Bounded like the other post-run LLM passes (#23): unbounded, this
        # round was the 8000s post-run stall tail.
        if emit:
            emit({'type': 'CLAIMS_RETRY', 'claims': unsupported})
        # #311: the verifier does NOT run with the run's full toolsets —
        # it gets the narrowed read+shell surface (build_verifier_toolsets),
        # wrapped in the same error-feedback seam as every agent.
        from .processes import ProcessRegistry
        from .tool_errors import error_feedback_toolset

        shell_bin = shell_bin_for(self._services.config, workdir)
        registry = ProcessRegistry(
            on_event=emit, db=self._services.db, session_id=session_id,
        )
        retry_agent: Agent = Agent(
            model=resolved, instructions=instructions or load_prompt('base_instructions'),
            toolsets=[error_feedback_toolset(build_verifier_toolsets(
                workdir, approvals, shell_bin, registry=registry,
            ))],
        )
        try:
            retry = await asyncio.wait_for(
                retry_agent.run(
                    f'{findings}\nBack these claims by actually running the checks now '
                    '(use the tools), or correct your summary.',
                    message_history=(history or []) + list(result.new_messages()),
                    usage_limits=self._services.usage_limits(),
                ),
                timeout=_POST_RUN_LLM_TIMEOUT_S,
            )
            self._services.record_model_usage(session_id, resolved, retry.usage)
            self._services.db.replace_messages(
                session_id, [encode_messages([m]) for m in retry.all_messages()]
            )
            if emit:
                emit({'type': 'CLAIMS_ADDRESSED', 'response': str(retry.output)[:1500]})
        except asyncio.CancelledError:
            # #308: the drain bound cancelled the retry mid-flight (live: run
            # mY5V_HxeMdk lost its verdict exactly this way — CancelledError
            # is a BaseException, so the fall-through below never ran). Emit
            # the verdict anyway, then propagate: the task must still end
            # cancelled so the drain's cancellation gather completes.
            if emit:
                emit({'type': 'CLAIMS_UNVERIFIED', 'claims': unsupported,
                      'reason': 'cancelled'})
            raise
        except Exception as exc:  # noqa: BLE001 — best effort; report unverified either way
            logger.warning(
                'claims-retry round failed for session %s (%s: %s); claims remain '
                'unverified', session_id, type(exc).__name__, exc,
            )
        if emit:
            emit({'type': 'CLAIMS_UNVERIFIED', 'claims': unsupported})


def shell_bin_for(config, workdir: Path) -> str:
    """The shell binary for `workdir`: project config override, else the
    global default. One home for the resolution that used to be copied at
    every shell-seam call site (review finding on b3817ad)."""
    from .config import load_project_config

    return load_project_config(workdir).get('shell', config.shell.default)


def build_verifier_toolsets(workdir: Path, approvals, shell_bin: str,
                            registry=None) -> list:
    """#311: the claims-retry verifier's narrowed toolset.

    Post-terminal verification needs exactly two capabilities: read the
    tree (list_dir/read_file/grep/glob) and re-run claimed verifications
    (shell). Everything else the run carried — edit tools, delegation,
    ask cards, sandbox exec — is verification-inappropriate: the verifier
    audits a finished run and must not mutate what it audits (live: run
    mY5V_HxeMdk's full-toolset retry re-ran builds and UI probes for ~2
    minutes post-terminal)."""
    from .tools import build_shell_toolset, build_toolset

    return [
        build_toolset(workdir, read_only=True),
        build_shell_toolset(workdir, approvals, shell_bin=shell_bin,
                            registry=registry),
    ]
