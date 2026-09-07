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
from .tools import build_toolset

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
class RunOutcome:
    session_id: str
    output: str
    model_name: str


class Engine:
    def __init__(self, config: Config, db: Database):
        self._config = config
        self._db = db

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

    async def run(
        self,
        *,
        prompt: str,
        workdir: Path,
        session_id: str | None = None,
        model: Model | str | None = None,
        on_event: Callable[[object], None] | None = None,
    ) -> RunOutcome:
        if session_id is None:
            session_id = self._db.create_session(workdir, title=prompt[:80])

        history = decode_messages(self._db.load_messages(session_id))

        resolved = model or self.build_model()
        model_name = getattr(resolved, 'model_name', str(resolved))
        agent: Agent = Agent(
            model=resolved,
            instructions=INSTRUCTIONS,
            toolsets=[build_toolset(workdir, on_edit=on_event)],
        )
        result = await agent.run(prompt, message_history=history or None)

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
