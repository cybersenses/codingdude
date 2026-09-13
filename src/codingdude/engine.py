"""The engine: one entry point — start a Run (Session + prompt), get an outcome.

Both frontends (web worker, headless CLI) drive this identical seam.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel

from .checkpoints import CheckpointStore
from .config import Config, parse_thinking
from .context import ContextManager
from .db import Database
from .messages import decode_messages, encode_messages, sanitize_history
from .tools import (
    GateRequired,
)


def _base_instructions() -> str:
    from .prompts import load_prompt

    return load_prompt('base_instructions')


INSTRUCTIONS = _base_instructions()


def _zai_fallback(model_name: str, base_url: str | None) -> Model:
    """Build the ZAI fallback model, optionally pointed at a custom endpoint."""
    from openai import AsyncOpenAI
    from pydantic_ai.providers.zai import ZaiProvider

    api_key = os.environ.get('ZAI_API_KEY')
    client = (
        AsyncOpenAI(api_key=api_key, base_url=base_url)
        if base_url
        else AsyncOpenAI(api_key=api_key)
    )
    provider = ZaiProvider(openai_client=client)
    from pydantic_ai.models.zai import ZaiModel

    return ZaiModel(model_name, provider=provider)


def _strip_provider_prefix(model: str) -> str:
    return model.split(':', 1)[1] if ':' in model else model


def _model_from_name(name: str, base_url: str | None) -> Model:
    """A model from a `provider:name` string.

    A Z.AI model must use the configured endpoint: the coding-plan endpoint
    (`fallback_base_url`) rejects keys/requests sent to the standard one with
    `code 1113` (insufficient balance). Previously the custom endpoint applied
    only to the configured fallback, so a zai `main` or a run/selector override
    fell through to the standard endpoint and failed.
    """
    if name.startswith('zai:') and base_url:
        return _zai_fallback(_strip_provider_prefix(name), base_url)
    from pydantic_ai.models import infer_model

    return infer_model(name)


_THINKING_PROVIDERS = ('glm', 'deepseek')


def _supports_thinking(model: Model) -> bool:
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


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateRequest:
    """A shell command the agent wanted to run; the user must decide."""

    command: str


@dataclass(frozen=True)
class RunOutcome:
    session_id: str
    output: str
    model_name: str
    status: str = 'complete'  # 'complete' | 'gate_aborted'
    gate: GateRequest | None = None


class Engine:
    def __init__(
        self,
        config: Config,
        db: Database,
        compaction_threshold: int | None = 80_000,
        extraction_model: Model | None = None,
        budget_cap_usd: float | None = None,
        embedder=None,
    ):
        self._config = config
        self._db = db
        # History payload size (chars) after which old turns are compacted.
        self._compaction_threshold = compaction_threshold
        # Cheap model that extracts missed facts into Memory post-session.
        self._extraction_model = extraction_model
        # Optional hard-stop on session spend. Survives --yolo by design.
        self._budget_cap_usd = budget_cap_usd
        # Optional embedder: enables the semantic_search tool + semantic Memory.
        self.embedder = embedder
        # Checkpoint store: per-turn file snapshots before agent edits.
        self.checkpoints = CheckpointStore(
            self._config_home(),
            max_per_session=50,
            max_age_days=30,
        )

    def build_model(
        self, main: Model | str | None = None, fallback: Model | str | None = None
    ) -> Model:
        """Wrap the primary model with the configured failover.

        The fallback is a safety net, not a requirement: if its provider
        credentials are missing, it is dropped with a warning instead of
        blocking every run.
        """
        primary = main or self._config.models.main
        fallback_name = fallback or self._config.models.fallback
        base_url = self._config.models.fallback_base_url
        try:
            primary_model = (
                primary if isinstance(primary, Model) else _model_from_name(primary, base_url)
            )
            fallback_model = (
                fallback_name
                if isinstance(fallback_name, Model)
                else _model_from_name(fallback_name, base_url)
            )
            return FallbackModel(primary_model, fallback_model)
        except Exception as exc:  # noqa: BLE001 — any provider-construction failure
            logger.warning('fallback model unavailable (%s); running without failover', exc)
            if isinstance(primary, Model):
                return primary
            from pydantic_ai.models import infer_model

            return infer_model(primary)

    def _build_subagent_model(self) -> Model | None:
        """The cheap model Subagents run on; None if its provider isn't configured."""
        try:
            from pydantic_ai.models import infer_model

            return infer_model(self._config.models.subagent)
        except Exception as exc:  # noqa: BLE001 — missing credentials etc.
            logger.warning('subagent model unavailable (%s); delegation disabled', exc)
            return None

    def _config_home(self) -> Path:
        from .config import config_home

        return config_home()

    async def review_diff(self, session_id: str) -> str:
        """On-demand review of the Session's working-tree diff (UI button)."""
        from .planning import review_diff_findings

        return await review_diff_findings(
            self._db, session_id, self._config_home(),
            self._extraction_model or self._build_subagent_model(),
            thinking=parse_thinking(self._config.models.thinking),
        )

    def approve_pattern(self, session_id: str, command: str) -> str:
        """Record a Pattern Approval for the rest of the Session (UI calls this)."""
        from .approvals import ApprovalPolicy

        policy = ApprovalPolicy()
        pattern = policy.pattern_for(command)
        self._db.record_pattern_approval(session_id, pattern)
        return pattern

    def _check_budget(self, session_id: str) -> None:
        """Hard-stop the session once spend crosses the cap (off by default;
        never bypassed by --yolo)."""
        if self._budget_cap_usd is None:
            return
        from .exceptions import BudgetExceeded

        totals = self._db.session_usage(session_id)
        spent = totals.get('cost_usd') or 0.0
        if spent >= self._budget_cap_usd:
            raise BudgetExceeded(spent_usd=spent, cap_usd=self._budget_cap_usd)

    def _record_model_usage(self, session_id: str, model, usage) -> None:
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
            pass

    def _usage_limits(self):
        """Per-run request cap (config `models.request_limit`, default 500).

        Without an explicit limit pydantic-ai applies its library default of
        50 model requests per run, which kills long agentic sessions with
        'would exceed the request_limit of 50'.
        """
        from pydantic_ai.usage import UsageLimits

        return UsageLimits(request_limit=self._config.models.request_limit)

    @staticmethod
    def _scrubbed() -> dict:
        from .tools import scrubbed_env

        return scrubbed_env()

    def _diff_nonempty(self, session_id: str) -> bool:
        import subprocess

        workdir = self._db.session_workdir(session_id)
        if not workdir:
            return False
        try:
            result = subprocess.run(
                ['git', 'diff', 'HEAD'], cwd=workdir,
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return bool(result.stdout.strip())

    async def run(
        self,
        *,
        prompt: str,
        workdir: Path,
        session_id: str | None = None,
        model: Model | str | None = None,
        on_event: Callable[[object], None] | None = None,
        approvals=None,
        subagent_model: Model | None = None,
        emit: Callable[[dict], None] | None = None,
        trace: bool = True,
        fix_loop: bool = False,
        test_command: str = 'pytest -q',
        max_test_iterations: int = 3,
        image_path: Path | None = None,
        vision_model: Model | None = None,
    ) -> RunOutcome:
        if session_id is None:
            session_id = self._db.create_session(workdir, title=prompt[:80])
            created_session = True
        else:
            created_session = False

        trace_file = self._config_home() / 'traces' / f'{session_id}.jsonl'

        def traced(event: dict) -> None:
            import json
            from datetime import UTC as _UTC
            from datetime import datetime as _dt

            if trace:
                trace_file.parent.mkdir(parents=True, exist_ok=True)
                payload = json.dumps({'ts': _dt.now(_UTC).isoformat(), **event})
                with open(trace_file, 'a', encoding='utf-8') as f:
                    f.write(payload + '\n')
            if emit:
                emit(event)

        def persist_snapshot(msgs):
            self._db.replace_messages(
                session_id, [encode_messages([m]) for m in msgs]
            )

        try:
            self._check_budget(session_id)
            if isinstance(model, Model):
                resolved = model
            elif isinstance(model, str):
                resolved = self.build_model(main=model)
            else:
                resolved = self.build_model()
            if image_path is not None and vision_model is not None:
                resolved = vision_model
            model_name = getattr(resolved, 'model_name', str(resolved))

            history = sanitize_history(
                decode_messages(self._db.load_messages(session_id))
            )
            traced({'type': 'USER_PROMPT', 'text': prompt})
            cm = self._context_manager(model_name)
            history, compacted = await self._maybe_compact(
                history, resolved, on_event, session_id, cm=cm
            )
            if compacted:
                self._db.replace_messages(
                    session_id, [encode_messages([m]) for m in history]
                )
            ctx_stats = cm.usage(history)
            traced({
                'type': 'CONTEXT_USAGE',
                'total_tokens': ctx_stats.total_tokens,
                'model_limit': ctx_stats.model_limit,
                'usage_percent': round(ctx_stats.usage_percent, 4),
            })
            self._db.update_session_context(
                session_id, ctx_stats.total_tokens, ctx_stats.model_limit
            )

            cp_holder: list[str] = []

            def capture_for_checkpoints(abs_path: Path) -> None:
                if not cp_holder:
                    cp_holder.append(self.checkpoints.begin(session_id))
                self.checkpoints.capture_file(session_id, cp_holder[0], workdir, abs_path)

            def on_edit_dispatch(ec: dict) -> None:
                traced(ec)
                if on_event:
                    on_event(ec)

            thinking = parse_thinking(self._config.models.thinking)

            # Pattern Approvals are session-scoped: load what past runs saved.
            if approvals is not None:
                approvals.patterns.update(self._db.session_patterns(session_id))
                if fix_loop:
                    approvals.patterns.add(test_command.strip())
                approvals.on_pattern = (
                    lambda pattern: self._db.record_pattern_approval(session_id, pattern)
                )

            from .config import load_project_config
            project_shell = load_project_config(workdir).get(
                'shell', self._config.shell.default
            )
            subagent = subagent_model or self._build_subagent_model()

            from .plugins import PluginContext, build_all

            plugin_ctx = PluginContext(
                workdir=workdir,
                config=self._config,
                db=self._db,
                session_id=session_id,
                home=self._config_home(),
                shell_bin=project_shell,
                test_command=test_command,
                fix_loop=fix_loop,
                approvals=approvals,
                subagent_model=subagent,
                thinking=thinking,
                review_model=self._extraction_model,
                vision_model=vision_model,
                embedder=self.embedder,
                on_edit=on_edit_dispatch,
                capture=capture_for_checkpoints,
                emitter=traced,
            )
            toolsets = await build_all(plugin_ctx)

            from .memory import MemoryStore
            from .skills import SkillRegistry

            registry = SkillRegistry(self._config_home())
            store = MemoryStore(self._db)

            instructions = INSTRUCTIONS
            from .repo_map import build_repo_map

            repo_map_text = build_repo_map(workdir)
            if repo_map_text:
                instructions += (
                    '\n\n## Repository overview (auto-generated map)\n' + repo_map_text
                )
            from .directives import build_directive_layers

            directive_layers = build_directive_layers(self._config_home(), workdir)
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
            if self.embedder is not None:
                relevant = [
                    content
                    for content, _score in store.retrieve_semantic(
                        self.embedder, str(workdir), query=prompt
                    )
                ]
            else:
                relevant = [
                    e['content'] for e in store.retrieve(str(workdir), query=prompt)
                ]
            if relevant:
                lines = '\n'.join(f'- {c}' for c in relevant)
                instructions += (
                    '\n\nMemory (durable facts from earlier sessions; respect them):\n'
                    + lines
                )

            from pydantic_ai.settings import ModelSettings

            model_settings: ModelSettings = ModelSettings(timeout=300, max_tokens=65536)
            if self._config.models.max_tokens:
                model_settings['max_tokens'] = self._config.models.max_tokens
            if thinking is not None and _supports_thinking(resolved):
                model_settings['thinking'] = thinking
            agent: Agent = Agent(
                model=resolved, instructions=instructions, toolsets=toolsets,
                model_settings=model_settings, retries=2,
            )
            run_prompt: str | list = prompt
            if image_path is not None:
                from pydantic_ai.messages import BinaryContent

                image_bytes = Path(image_path).read_bytes()
                media = 'image/png' if str(image_path).lower().endswith('.png') else 'image/jpeg'
                run_prompt = [prompt, BinaryContent(data=image_bytes, media_type=media)]
            try:
                result = await self._run_agent(
                    agent, run_prompt, history, model_name, traced,
                    cp_holder=cp_holder,
                    persist=persist_snapshot,
                    stream=emit is not None,
                    usage_limits=self._usage_limits(),
                )
            except GateRequired as gate:
                # ADR-0003: unattended runs abort on gates. The Session keeps
                # its prior turns; after approval the next run re-issues.
                return RunOutcome(
                    session_id=session_id,
                    output=f'gate required: {gate.command}',
                    model_name=model_name,
                    status='gate_aborted',
                    gate=GateRequest(command=gate.command),
                )
        except Exception:
            # A run that died before producing anything leaves no husk Session.
            if created_session and not self._db.load_messages(session_id):
                self._db.delete_session(session_id)
            raise

        self._db.replace_messages(
            session_id, [encode_messages([m]) for m in result.all_messages()]
        )
        # Prefer the provider's own token count for the final request (it
        # includes instructions + history); fall back to the estimate.
        self._persist_actual_context(session_id, result, cm)

        # Fix-until-green loop: run the tests, feed failures back, repeat.
        if fix_loop and approvals is not None:
            import asyncio

            from .config import load_project_config
            from .tools import shell_argv

            shell_bin = load_project_config(workdir).get(
                'shell', self._config.shell.default
            )
            for _ in range(max_test_iterations):
                proc = await asyncio.create_subprocess_exec(
                    *shell_argv(test_command, shell_bin),
                    cwd=workdir, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, env=self._scrubbed(),
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
                except TimeoutError:
                    proc.kill()
                    break
                test_out = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()[:4000]
                passed = proc.returncode == 0
                if emit:
                    emit({'type': 'TEST_RUN', 'passed': passed, 'output': test_out})
                if passed:
                    break
                retry_agent: Agent = Agent(
                    model=resolved, instructions=instructions, toolsets=toolsets
                )
                history = history + list(result.new_messages()) if result else history
                failure_text = (
                    'The test suite is still failing. Output:\n' + test_out + '\n'
                )
                result = await retry_agent.run(
                    failure_text
                    + 'Fix the failures. Do not declare success until the tests pass.',
                    message_history=history,
                )
                self._record_model_usage(session_id, resolved, result.usage)
                self._db.replace_messages(
                    session_id,
                    [encode_messages([m]) for m in result.all_messages()],
                )
                self._check_budget(session_id)

        usage = result.usage
        self._db.record_usage(
            session_id,
            model=model_name,
            requests=usage.requests or 0,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cost_usd=float(usage.cost) if usage.cost is not None else None,
        )
        if self._extraction_model is not None:
            await self._extract_memory(session_id, workdir)
        if self._diff_nonempty(session_id):
            await self._verify_claims(
                session_id, result, workdir, approvals, emit,
                resolved=resolved, history=history,
                toolsets=toolsets, instructions=instructions,
            )
        self._check_budget(session_id)
        return RunOutcome(
            session_id=session_id,
            output=result.output,
            model_name=model_name,
        )

    async def _extract_memory(self, session_id: str, workdir: Path) -> None:
        """Post-session pass: bank durable facts the run didn't explicitly remember
        and retire entries this session made obsolete (via `FORGET:` lines)."""
        from pydantic_ai import Agent

        from .memory import MemoryStore

        store = MemoryStore(self._db)
        known = store.all_entries()
        known_lines = '\n'.join(f"- {e['content']}" for e in known[:50])
        transcript = '\n'.join(self._db.load_messages(session_id))[:12000]
        agent: Agent = Agent(model=self._extraction_model)
        try:
            result = await agent.run(
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
            )
        except Exception:  # noqa: BLE001 — extraction must never fail a run
            return
        self._record_model_usage(session_id, self._extraction_model, result.usage)
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

    def _context_manager(self, model_name: str) -> ContextManager:
        """The ContextManager for the resolved model: per-model context limit
        (config override wins; see context.model_limit_for)."""
        from .context import model_limit_for

        return ContextManager(
            model_limit=model_limit_for(model_name, self._config.models.context_limit)
        )

    def _persist_actual_context(self, session_id: str, result, cm) -> None:
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
            self._db.update_session_context(
                session_id, total, cm.model_limit
            )
        except Exception as exc:  # noqa: BLE001 - accounting must never fail a run
            logger.warning('context snapshot not persisted: %s', exc)

    async def _maybe_compact(self, history, resolved: Model, on_event, session_id: str,
                             cm: ContextManager | None = None):
        """Compact old turns into a summary when history approaches the
        model's context window (token-based) or the legacy char threshold.

        Returns (history, compacted?) — compacted True means history changed.
        """
        if len(history) < 3:
            return history, False
        over_tokens = cm is not None and cm.usage(history).needs_compaction
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
        self._record_model_usage(session_id, resolved, summary_result.usage)
        # RAG: the summary becomes retrievable Memory, so facts that fell out
        # of the window resurface in future runs' instructions (R3).
        try:
            from .memory import MemoryStore

            MemoryStore(self._db).add(
                f'Compacted conversation summary: {summary}',
                scope='workdir',
                workdir=self._db.session_workdir(session_id) or '',
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

    async def _run_agent(self, agent, prompt, history, model_name, traced, cp_holder,
                         persist=None, stream: bool = True, usage_limits=None):
        """Drive one agent run; stream AG-UI deltas only when `stream` is set.

        History is snapshotted after every tool turn (self-review H7), so a
        crash or stop never loses the in-flight exchange — for headless runs
        too. When streaming, deltas go to the UI via `traced`. When NOT
        streaming (headless) we deliberately skip `node.stream()` so
        pydantic-ai executes the model on its non-streaming path and reports
        exact usage — keeping the Budget Cap correct. `traced` is a no-op
        when no emitter is attached.
        """
        from pydantic_ai.messages import (
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            PartDeltaEvent,
            PartStartEvent,
            TextPart,
            TextPartDelta,
        )

        emit = traced
        if stream:
            emit({'type': 'RUN_STARTED'})
        async with agent.iter(prompt, message_history=history or None,
                              usage_limits=usage_limits) as run:
            async for node in run:
                if agent.is_model_request_node(node):
                    if not stream:
                        continue
                    emit({'type': 'TEXT_MESSAGE_START', 'role': 'assistant'})
                    async with node.stream(run.ctx) as node_stream:
                        async for event in node_stream:
                            if isinstance(event, PartStartEvent) and isinstance(
                                event.part, TextPart
                            ):
                                emit({
                                    'type': 'TEXT_MESSAGE_CONTENT',
                                    'delta': event.part.content,
                                })
                            elif isinstance(event, PartDeltaEvent):
                                delta = event.delta
                                if isinstance(delta, TextPartDelta) and delta.content_delta:
                                    emit({
                                        'type': 'TEXT_MESSAGE_CONTENT',
                                        'delta': delta.content_delta,
                                    })
                                elif (
                                    hasattr(delta, 'args_delta')
                                    and delta.args_delta
                                ):
                                    emit({
                                        'type': 'TOOL_CALL_ARGS',
                                        'delta': delta.args_delta,
                                    })
                    emit({'type': 'TEXT_MESSAGE_END'})
                elif agent.is_call_tools_node(node):
                    # Persist incrementally so gates/stops/crashes keep history.
                    if persist is not None:
                        persist(run.all_messages())
                    if not stream:
                        continue
                    async with node.stream(run.ctx) as node_stream:
                        async for event in node_stream:
                            if isinstance(event, FunctionToolCallEvent):
                                emit({
                                    'type': 'TOOL_CALL_START',
                                    'tool_name': event.part.tool_name,
                                    'args': event.part.args,
                                })
                            elif isinstance(event, FunctionToolResultEvent):
                                result_part = event.part
                                emit({
                                    'type': 'TOOL_CALL_END',
                                    'tool_name': result_part.tool_name,
                                    'result': str(result_part.content)[:2000],
                                })
            result = run.result
        # NB: terminal RUN_FINISHED is emitted by the worker after persistence.
        return result

    async def _verify_claims(self, session_id: str, result, workdir: Path, approvals, emit,
                             resolved=None, history=None, toolsets=None, instructions=None) -> None:
        """Anti-slop: cross-check the final summary's verification claims against
        recorded tool results; re-execute explicitly claimed verifications once;
        give the model one round to address unsupported claims."""

        from pydantic_ai import Agent

        from .prompts import load_prompt

        if self._extraction_model is None:
            return

        final_text = result.output
        payloads = decode_messages(self._db.load_messages(session_id))
        tool_results = []
        for m in payloads:
            for part in m.parts:
                name = getattr(part, 'tool_name', None)
                if name in ('shell', 'run_coverage'):
                    content = str(getattr(part, 'content', ''))[:300]
                    tool_results.append(f'{name}: exit {content[:120]}')

        auditor = Agent(model=self._extraction_model)
        audit_prompt = (
            load_prompt('claim_check')
            + '\n\nSUMMARY:\n'
            + final_text[:3000]
            + '\n\nRECORDED COMMAND RESULTS:\n'
            + ('\n'.join(tool_results)[-4000:] if tool_results else '(none recorded)')
        )
        try:
            audit = await auditor.run(audit_prompt)
        except Exception:  # noqa: BLE001 — verification must never fail the run
            return
        self._record_model_usage(session_id, self._extraction_model, audit.usage)
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
        retry_agent: Agent = Agent(
            model=resolved, instructions=instructions or INSTRUCTIONS,
            toolsets=toolsets,
        )
        try:
            retry = await retry_agent.run(
                f'{findings}\nBack these claims by actually running the checks now '
                '(use the tools), or correct your summary.',
                message_history=history + list(result.new_messages()),
                usage_limits=self._usage_limits(),
            )
            self._record_model_usage(session_id, resolved, retry.usage)
            self._db.replace_messages(
                session_id, [encode_messages([m]) for m in retry.all_messages()]
            )
            emit({'type': 'CLAIMS_ADDRESSED', 'response': str(retry.output)[:1500]})
        except Exception:  # noqa: BLE001 — best effort; report unverified either way
            pass
        emit({'type': 'CLAIMS_UNVERIFIED', 'claims': unsupported})

