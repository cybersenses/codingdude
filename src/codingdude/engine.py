"""The engine: one entry point — start a Run (Session + prompt), get an outcome.

Both frontends (web worker, headless CLI) drive this identical seam.
"""

from dataclasses import dataclass
from pathlib import Path
import os
import sys
from typing import Callable

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.toolsets import AbstractToolset

from .config import Config
from .db import Database
from .messages import decode_messages, encode_messages
from .tools import (
    GateRequired,
    build_delegation_toolset,
    build_shell_toolset,
    build_toolset,
    build_web_toolset,
)

INSTRUCTIONS = (
    'You are CodingDude, a personal coding agent working in a repository. '
    'Use the file tools (list_dir, read_file, grep, glob) to explore the codebase. '
    'Complete the task, then summarize what you found or did.'
)


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
        compaction_threshold: int | None = None,
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
        try:
            if isinstance(fallback_name, str) and (
                self._config.models.fallback_base_url
                and fallback_name.startswith('zai:')
            ):
                fallback_model = _zai_fallback(
                    _strip_provider_prefix(fallback_name),
                    self._config.models.fallback_base_url,
                )
                return FallbackModel(primary, fallback_model)
            return FallbackModel(primary, fallback_name)
        except Exception as exc:  # noqa: BLE001 — any provider-construction failure
            print(
                f'warning: fallback model unavailable ({exc}); '
                'running without failover',
                file=sys.stderr,
            )
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
            print(f'warning: subagent model unavailable ({exc}); delegation disabled', file=sys.stderr)
            return None

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
    ) -> RunOutcome:
        if session_id is None:
            session_id = self._db.create_session(workdir, title=prompt[:80])
            created_session = True
        else:
            created_session = False

        try:
            self._check_budget(session_id)
            resolved = model if isinstance(model, Model) else self.build_model()
            model_name = getattr(resolved, 'model_name', str(resolved))

            history = decode_messages(self._db.load_messages(session_id))
            history, compacted = await self._maybe_compact(history, resolved, on_event)
            if compacted:
                self._db.replace_messages(
                    session_id, [encode_messages([m]) for m in history]
                )

            toolsets: list[AbstractToolset] = [
                build_toolset(workdir, on_edit=on_event, approvals=approvals)
            ]
            if approvals is not None:
                from .config import load_project_config

                # Pattern Approvals are session-scoped: load what past runs saved.
                approvals.patterns.update(self._db.session_patterns(session_id))
                # New pattern approvals persist for the rest of the Session.
                approvals.on_pattern = (
                    lambda pattern: self._db.record_pattern_approval(session_id, pattern)
                )
                project_shell = load_project_config(workdir).get(
                    'shell', self._config.shell.default
                )
                toolsets.append(
                    build_shell_toolset(workdir, approvals, shell_bin=project_shell)
                )
            from .tools import build_git_toolset

            toolsets.append(build_git_toolset(workdir, approvals))

            subagent = subagent_model or self._build_subagent_model()
            if subagent is not None:
                toolsets.append(build_delegation_toolset(workdir, subagent))

            toolsets.append(build_web_toolset())
            from .ast_tools import build_ast_toolset

            toolsets.append(build_ast_toolset(workdir))

            from .mcp_config import load_merged_mcp_toolsets

            toolsets.extend(load_merged_mcp_toolsets(self._config_home(), workdir))

            if self.embedder is not None:
                from .semantic import SemanticIndex, build_semantic_toolset

                toolsets.append(
                    build_semantic_toolset(workdir, SemanticIndex(self.embedder, self._db))
                )

            from .memory import MemoryStore, build_memory_toolset

            store = MemoryStore(self._db)
            toolsets.append(build_memory_toolset(store, str(workdir)))

            instructions = INSTRUCTIONS
            from .directives import build_directive_layers

            directive_layers = build_directive_layers(self._config_home(), workdir)
            if directive_layers:
                instructions += '\n\n' + directive_layers
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

            agent: Agent = Agent(
                model=resolved, instructions=instructions, toolsets=toolsets
            )
            try:
                if emit is None:
                    result = await agent.run(prompt, message_history=history or None)
                else:
                    result = await self._run_streaming(
                        agent, prompt, history, model_name, emit
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

        self._db.append_messages(session_id, encode_messages(list(result.new_messages())))
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
        self._check_budget(session_id)
        return RunOutcome(
            session_id=session_id,
            output=result.output,
            model_name=model_name,
        )

    async def _extract_memory(self, session_id: str, workdir: Path) -> None:
        """Post-session pass: bank durable facts the run didn't explicitly remember."""
        from pydantic_ai import Agent

        from .memory import MemoryStore

        transcript = '\n'.join(self._db.load_messages(session_id))[:12000]
        agent: Agent = Agent(model=self._extraction_model)
        try:
            result = await agent.run(
                'From this conversation transcript, extract durable facts worth '
                'remembering for future sessions (preferences, project facts, '
                'decisions). One fact per line, no numbering. Return only lines '
                'worth keeping — if none, return nothing.\n\n' + transcript
            )
        except Exception:  # noqa: BLE001 — extraction must never fail a run
            return
        store = MemoryStore(self._db)
        known = {e['content'] for e in store.all_entries()}
        for line in result.output.splitlines():
            fact = line.strip().lstrip('-•* ')
            if fact and fact not in known:
                store.add(fact, scope='workdir', workdir=str(workdir))
                known.add(fact)

    def _config_home(self) -> Path:
        from .config import config_home

        return config_home()

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

    async def _maybe_compact(self, history, resolved: Model, on_event):
        """Compact old turns into a summary when history passes the threshold.

        Returns (history, compacted?) — compacted True means history changed.
        """
        if not self._compaction_threshold or len(history) < 3:
            return history, False
        total = sum(len(encode_messages([m])) for m in history)
        if total <= self._compaction_threshold:
            return history, False

        from pydantic_ai.messages import ModelRequest, UserPromptPart

        old, keep = history[:-1], history[-1:]
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

    async def _run_streaming(self, agent, prompt, history, model_name, emit):
        """Run the agent, emitting AG-UI-shaped events for the UI layer."""
        from pydantic_ai.messages import (
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            PartDeltaEvent,
            PartStartEvent,
            TextPart,
            TextPartDelta,
        )
        from pydantic_ai._agent_graph import CallToolsNode

        emit({'type': 'RUN_STARTED'})
        async with agent.iter(prompt, message_history=history or None) as run:
            async for node in run:
                if agent.is_model_request_node(node):
                    emit({'type': 'TEXT_MESSAGE_START', 'role': 'assistant'})
                    async with node.stream(run.ctx) as stream:
                        async for event in stream:
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
                elif isinstance(node, CallToolsNode):
                    async with node.stream(run.ctx) as stream:
                        async for event in stream:
                            if isinstance(event, FunctionToolCallEvent):
                                emit({
                                    'type': 'TOOL_CALL_START',
                                    'tool_name': event.part.tool_name,
                                    'args': event.part.args,
                                })
                            elif isinstance(event, FunctionToolResultEvent):
                                result = event.part
                                emit({
                                    'type': 'TOOL_CALL_END',
                                    'tool_name': result.tool_name,
                                    'result': str(result.content)[:2000],
                                })
            result = run.result
        # NB: terminal RUN_FINISHED is emitted by the worker after persistence.
        return result
