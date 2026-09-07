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

from .config import Config
from .db import Database
from .messages import decode_messages, encode_messages
from .tools import (
    GateRequired,
    build_delegation_toolset,
    build_shell_toolset,
    build_toolset,
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
    ):
        self._config = config
        self._db = db
        # History payload size (chars) after which old turns are compacted.
        self._compaction_threshold = compaction_threshold

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
    ) -> RunOutcome:
        if session_id is None:
            session_id = self._db.create_session(workdir, title=prompt[:80])
            created_session = True
        else:
            created_session = False

        try:
            resolved = model if isinstance(model, Model) else self.build_model()
            model_name = getattr(resolved, 'model_name', str(resolved))

            history = decode_messages(self._db.load_messages(session_id))
            history, compacted = await self._maybe_compact(history, resolved, on_event)
            if compacted:
                self._db.replace_messages(
                    session_id, [encode_messages([m]) for m in history]
                )

            toolsets = [build_toolset(workdir, on_edit=on_event)]
            if approvals is not None:
                from .config import load_project_config

                project_shell = load_project_config(workdir).get(
                    'shell', self._config.shell.default
                )
                toolsets.append(
                    build_shell_toolset(workdir, approvals, shell_bin=project_shell)
                )

            subagent = subagent_model or self._build_subagent_model()
            if subagent is not None:
                toolsets.append(build_delegation_toolset(workdir, subagent))

            instructions = INSTRUCTIONS
            agent_md = workdir / 'AGENT.md'
            if agent_md.exists():
                instructions += (
                    '\n\nProject Context (AGENT.md, follow these instructions):\n'
                    + agent_md.read_text(encoding='utf-8', errors='replace')
                )

            agent: Agent = Agent(
                model=resolved, instructions=instructions, toolsets=toolsets
            )
            try:
                result = await agent.run(prompt, message_history=history or None)
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
        return RunOutcome(
            session_id=session_id,
            output=result.output,
            model_name=model_name,
        )

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
