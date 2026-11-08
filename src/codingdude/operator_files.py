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
"""R80-3 #295 (DE-5): operator kill-switch and steer files.

Operator controls that work without the UI, checked at the tool-call
dispatch boundary the agent already crosses — poll-free, no watcher thread:

- ``AGENT_STOP`` at the workdir root: no tool executes; the run ends with a
  truthful ``WORKER_HALTED`` terminal event and a non-zero worker exit
  (R77 truthful-delivery semantics).
- ``STEER.md`` at the workdir root: content is injected once into the
  model-visible tool result and the file is truncated to zero
  (consume-once, cwc steer.sh semantics).

Race semantics (documented, pinned by test): a call already in flight
completes — the stop takes effect at the next boundary. A steer written
before a *failing* tool call is not consumed: it stays on disk and is
injected at the next successful boundary instead of being lost.

Both names are gitignored (scaffold seeds them; see ensure_project_scaffold).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai._run_context import RunContext
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

AGENT_STOP_NAME = 'AGENT_STOP'
STEER_NAME = 'STEER.md'

_STEER_MARKER = '[OPERATOR STEER]'
#: Steering text is operator-authored and bounded to keep one rogue file
#: from blowing the run's context; the marker says when it was cut.
_STEER_MAX_CHARS = 8000


class OperatorHalt(Exception):
    """Raised at the dispatch boundary when AGENT_STOP is present.

    Control flow, not a tool failure: it must escape the toolset unconverted
    (this wrapper sits outside error_feedback_toolset) and abort the run —
    the engine maps it to RunOutcome(status='halted').
    """


def stop_requested(workdir: Path) -> bool:
    """True when the AGENT_STOP kill-switch file exists at the workdir root."""
    return (workdir / AGENT_STOP_NAME).exists()


def peek_steer(workdir: Path) -> str:
    """STEER.md content when present and non-empty, '' otherwise.

    Read-only: consumption (truncate) is a separate step so content written
    before a failing tool call is not lost (see module docstring).
    """
    try:
        text = (workdir / STEER_NAME).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return text.strip()


def clear_steer(workdir: Path) -> None:
    """Consume the steer: truncate STEER.md to zero bytes (file stays)."""
    try:
        (workdir / STEER_NAME).write_text('', encoding='utf-8')
    except OSError:
        pass  # best-effort; an unconsumed file just re-injects next boundary


def _steer_block(content: str) -> str:
    if len(content) > _STEER_MAX_CHARS:
        content = content[:_STEER_MAX_CHARS] + '\n… (truncated)'
    return f'\n\n{_STEER_MARKER}\n{content}'


@dataclass
class OperatorFilesToolset(WrapperToolset):
    """Dispatch-boundary checks: kill-switch before the call, steer injection
    after a successful result (consumed only then)."""

    workdir: Path

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[Any],
        tool: ToolsetTool[Any],
    ) -> Any:
        if stop_requested(self.workdir):
            raise OperatorHalt(
                'operator halt: AGENT_STOP present at the workdir root — '
                'no further tool calls execute'
            )
        steer = peek_steer(self.workdir)
        result = await super().call_tool(name, tool_args, ctx, tool)
        if steer:
            # Consume only after the call succeeded, so a steer written
            # before a failing call survives to the next boundary.
            clear_steer(self.workdir)
            if isinstance(result, str):
                result = result + _steer_block(steer)
            else:
                result = f'{result}{_steer_block(steer)}'
        return result


def operator_files_toolset(
    toolsets: AbstractToolset[Any] | list[AbstractToolset[Any]], workdir: Path,
) -> OperatorFilesToolset:
    """Wrap toolset(s) with OperatorFilesToolset (one call site per Agent,
    so the main agent's every tool call crosses the operator-file boundary)."""
    if isinstance(toolsets, AbstractToolset):
        return OperatorFilesToolset(wrapped=toolsets, workdir=workdir)
    return OperatorFilesToolset(
        wrapped=CombinedToolset(list(toolsets)), workdir=workdir,
    )

