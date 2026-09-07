"""The engine: one entry point — start a Run (Session + prompt), get an outcome.

Both frontends (web worker, headless CLI) drive this identical seam.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel

from .config import Config
from .db import Database
from .messages import decode_messages, encode_messages

INSTRUCTIONS = (
    'You are CodingDude, a personal coding agent working in a repository. '
    'Use tools to explore, edit files and run commands to complete the task. '
    'Prefer minimal, targeted edits. When done, summarize what you changed and why.'
)


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
        """Wrap the primary model with the configured failover."""
        return FallbackModel(
            main or self._config.models.main,
            fallback or self._config.models.fallback,
        )

    async def run(
        self,
        *,
        prompt: str,
        workdir: Path,
        session_id: str | None = None,
        model: Model | str | None = None,
    ) -> RunOutcome:
        if session_id is None:
            session_id = self._db.create_session(workdir, title=prompt[:80])

        history = decode_messages(self._db.load_messages(session_id))

        resolved = model or self.build_model()
        agent: Agent = Agent(model=resolved, instructions=INSTRUCTIONS)
        result = await agent.run(prompt, message_history=history or None)

        self._db.append_messages(session_id, encode_messages(list(result.new_messages())))
        usage = result.usage
        self._db.record_usage(
            session_id,
            model=getattr(resolved, 'model_name', str(resolved)),
            requests=usage.requests or 0,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cost_usd=float(usage.cost) if usage.cost is not None else None,
        )
        return RunOutcome(
            session_id=session_id,
            output=result.output,
            model_name=getattr(resolved, 'model_name', str(resolved)),
        )
