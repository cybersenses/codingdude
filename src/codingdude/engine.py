"""The engine: one entry point — start a Run (Session + prompt), get an outcome.

Both frontends (web worker, headless CLI) drive this identical seam.
`run` is a flat orchestrator over the three run seams in `run_pipeline`:
PromptAssembler (instructions + Agent), HistoryManager (load/compact/
persist + context), PostRunPipeline (usage, memory, claim verification).
"""

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel

from .checkpoints import CheckpointStore
from .config import Config, parse_thinking
from .db import Database
from .run_pipeline import (
    HistoryManager,
    PostRunPipeline,
    PromptAssembler,
    RunServices,
)
from .tools import (
    GateRequired,
)

# Generous cap for waiting out background post-run passes before the next
# turn: each pass is already bounded by _POST_RUN_LLM_TIMEOUT_S (run_pipeline).
_POST_RUN_DRAIN_TIMEOUT_S = 300.0


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
        # Set through the public `extraction_model` property, never poked directly.
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
        # The three run seams (arch review Candidate 2): shared services +
        # prompt / history / post-run ownership.
        self._services = RunServices(
            config, db, self._config_home(),
            extraction_model=lambda: self._extraction_model,
            budget_cap_usd=budget_cap_usd,
        )
        self._prompts = PromptAssembler()
        self._history = HistoryManager(self._services, compaction_threshold)
        self._post = PostRunPipeline(self._services)
        # Background post-run tails, keyed by session (drained before the
        # next turn so extraction lands before it can matter).
        self._pending_post_run: dict[str, asyncio.Task] = {}

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

    @property
    def extraction_model(self) -> Model | None:
        return self._extraction_model

    @extraction_model.setter
    def extraction_model(self, model: Model | None) -> None:
        self._extraction_model = model

    async def review(self, session_id: str) -> str:
        """Public review entry point: findings, or the CLEAN verdict.

        Runs on the extraction model when set (worker), else the
        configured subagent model. Never raises for model trouble:
        review_diff_findings swallows failures and returns "".
        """
        findings = await self.review_diff(session_id)
        return findings or 'CLEAN — no findings'

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

    def _scrubbed(self) -> dict:
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

    def _make_tracer(self, session_id: str, workdir: Path, trace: bool, emit):
        """The per-run event sink: trace JSONL + render capture + UI emit."""
        trace_file = self._config_home() / 'traces' / f'{session_id}.jsonl'

        def traced(event: dict) -> None:
            from codingdude.traces import append_trace_line

            if trace:
                # Single atomic append per line (#79): concurrent writers
                # (engine tracer + trace_terminal) must never interleave.
                append_trace_line(trace_file, event)
            if event.get('type') == 'RENDER_CAPTURED' and session_id:
                # R1: capture hook auto-register — persist the render with
                # session provenance; failures never fail the run.
                try:
                    rel = str(event.get('path', ''))
                    image = (workdir / rel).stat()
                    self._db.record_render(
                        session_id, rel, bytes_=image.st_size, mtime=int(image.st_mtime),
                    )
                except OSError:
                    pass
            if emit:
                emit(event)

        return traced

    def _resolve_run_model(
        self, model: Model | str | None,
        image_path: Path | None, vision_model: Model | None,
    ) -> Model:
        """The model this run executes on: explicit override > image-vision >
        configured main (+failover)."""
        if isinstance(model, Model):
            resolved = model
        elif isinstance(model, str):
            resolved = self.build_model(main=model)
        else:
            resolved = self.build_model()
        if image_path is not None and vision_model is not None:
            resolved = vision_model
        return resolved

    async def _run_fix_loop(
        self, session_id: str, resolved: Model, instructions: str, toolsets,
        history: list, result, workdir: Path, test_command: str, shell_bin: str,
        max_test_iterations: int, emit,
    ):
        """Fix-until-green: run the tests, feed failures back, repeat."""
        from .tools import run_captured, shell_argv

        for _ in range(max_test_iterations):
            cap = await run_captured(
                shell_argv(test_command, shell_bin),
                cwd=workdir, timeout=600, env=self._scrubbed(),
            )
            if cap is None:
                break
            test_out = cap.combined[:4000]
            passed = cap.code == 0
            if emit:
                emit({'type': 'TEST_RUN', 'passed': passed, 'output': test_out})
            if passed:
                break
            retry_agent = self._prompts.agent(resolved, instructions, toolsets, retries=1)
            history = history + list(result.new_messages()) if result else history
            failure_text = (
                'The test suite is still failing. Output:\n' + test_out + '\n'
            )
            import asyncio as _asyncio

            from .codegraph_boot import refresh_codegraph_index

            if emit:
                emit({'type': 'INDEX_REFRESHING'})
            refreshed = await _asyncio.to_thread(refresh_codegraph_index, workdir)
            if emit:
                emit({'type': 'INDEX_REFRESHED', 'ok': refreshed is not None})
            result = await retry_agent.run(
                failure_text
                + 'Fix the failures. Do not declare success until the tests pass.',
                message_history=history,
            )
            self._services.record_model_usage(session_id, resolved, result.usage)
            self._history.persist(session_id, result.all_messages())
            self._services.check_budget(session_id)
        return result

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
        # Wait out the previous turn's background post-run passes so memory
        # extraction lands before this prompt is assembled.
        await self._drain_pending_post_run()

        traced = self._make_tracer(session_id, workdir, trace, emit)

        from .codegraph_boot import boot_codegraph, boot_hint
        from .scaffold import ensure_project_scaffold

        scaffold = ensure_project_scaffold(workdir)
        boot_status = boot_codegraph(workdir)
        boot_event: dict = {'type': 'CODEGRAPH_BOOT', 'status': boot_status['status']}
        if boot_status['reason']:
            boot_event['reason'] = boot_status['reason']
        if scaffold['created']:
            boot_event['scaffold_created'] = scaffold['created']
        if scaffold['errors']:
            logger.warning('project scaffold incomplete: %s', scaffold['errors'])
        # Emitted after USER_PROMPT below: the trace contract keeps
        # USER_PROMPT as the first event of a run (test_evals relies on it).

        from datetime import UTC as _UTC
        from datetime import datetime as _dt

        started = _dt.now(_UTC)
        try:
            self._services.check_budget(session_id)
            resolved = self._resolve_run_model(model, image_path, vision_model)
            model_name = getattr(resolved, 'model_name', str(resolved))

            history = self._history.load(session_id)
            traced({'type': 'USER_PROMPT', 'text': prompt})
            traced(boot_event)
            cm = self._history.context_manager(model_name)
            history, compacted = await self._history.maybe_compact(
                history, resolved, on_event, session_id, cm=cm
            )
            if compacted:
                self._history.persist(session_id, history)
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
            # R25: tool runtime errors feed back to the model as retries
            # instead of killing the run (3 strikes in PromptAssembler.agent).
            from .tool_errors import error_feedback_toolset

            toolsets = [error_feedback_toolset(toolsets)]

            from .memory import MemoryStore
            from .skills import SkillRegistry

            registry = SkillRegistry(self._config_home())
            store = MemoryStore(self._db)
            instructions = self._prompts.instructions(
                self._services, workdir, prompt, registry, store, self.embedder
            )
            hint = boot_hint(boot_status)
            if hint:
                instructions += '\n\n' + hint

            agent = self._prompts.agent(
                resolved, instructions, toolsets,
                self._prompts.model_settings(self._services, resolved, thinking),
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
                    persist=lambda msgs: self._history.persist(session_id, msgs),
                    stream=emit is not None,
                    usage_limits=self._services.usage_limits(),
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

        self._history.persist(session_id, result.all_messages())
        # Prefer the provider's own token count for the final request (it
        # includes instructions + history); fall back to the estimate.
        self._history.persist_actual_context(session_id, result, cm)

        # Fix-until-green loop: run the tests, feed failures back, repeat.
        if fix_loop and approvals is not None:
            from .config import load_project_config

            shell_bin = load_project_config(workdir).get(
                'shell', self._config.shell.default
            )
            result = await self._run_fix_loop(
                session_id, resolved, instructions, toolsets,
                history, result, workdir, test_command, shell_bin,
                max_test_iterations, emit,
            )

        self._post.record_run_usage(session_id, model_name, result, started, traced)
        self._services.check_budget(session_id)
        # Post-run passes (extraction ∥ claims audit) run in the background:
        # RUN_FINISHED must not wait ~90s on them (user friction). The next
        # turn drains them before its prompt is assembled, so extraction
        # still lands before it can matter (see _drain_pending_post_run).
        self._pending_post_run[session_id] = asyncio.create_task(
            self._post_run_tail(session_id, result, workdir, approvals, traced,
                                resolved, history, toolsets, instructions)
        )
        return RunOutcome(
            session_id=session_id,
            output=result.output,
            model_name=model_name,
        )

    async def _post_run_tail(self, session_id: str, result, workdir, approvals,
                             traced, resolved, history, toolsets, instructions) -> None:
        """Extraction + claims audit, concurrent, best-effort — never fails a run."""
        try:
            # #24: extraction and the claims audit are independent — run them
            # concurrently so the tail costs max(), not sum().
            if self._diff_nonempty(session_id):
                await asyncio.gather(
                    self._post.extract_memory(session_id, workdir, emit=traced),
                    self._post.verify_claims(
                        session_id, result, workdir, approvals, traced,
                        resolved=resolved, history=history,
                        toolsets=toolsets, instructions=instructions,
                    ),
                )
            else:
                traced({'type': 'CLAIMS_SKIPPED', 'reason': 'empty_diff'})
                await self._post.extract_memory(session_id, workdir, emit=traced)
        except Exception:  # noqa: BLE001 — background tail must never crash the engine
            logging.getLogger(__name__).warning(
                'post-run passes failed for session %s', session_id, exc_info=True
            )
        finally:
            self._pending_post_run.pop(session_id, None)

    async def drain_post_run(self, timeout: float = _POST_RUN_DRAIN_TIMEOUT_S) -> None:
        """Await all pending post-run tails (used before the next turn and on
        shutdown/tests so extraction always lands)."""
        tasks = [t for t in self._pending_post_run.values() if not t.done()]
        if not tasks:
            return
        try:
            await asyncio.wait_for(asyncio.wait(tasks), timeout=timeout)
        except TimeoutError:
            logging.getLogger(__name__).warning(
                'post-run passes still pending after %ss; continuing', timeout
            )

    async def _drain_pending_post_run(self) -> None:
        """Called at the start of every run: wait out the previous turn's
        post-run passes so memory extraction lands before this prompt is
        assembled. Bounded — a stuck tail delays but never blocks."""
        await self.drain_post_run()

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
