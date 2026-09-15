"""R25: convert unexpected tool exceptions into feedback the agent can act on.

An unexpected exception inside a tool body (OSError/WinError 32, NameError,
...) used to propagate out of the toolset and kill the whole run. Wrapped
this way, it becomes a `ModelRetry`: pydantic-ai feeds the message back to
the model, which can correct course; only after the retry budget (3) is
exhausted does the run abort.
"""
from __future__ import annotations

from typing import Any

from pydantic_ai._run_context import RunContext
from pydantic_ai.exceptions import (
    ApprovalRequired,
    CallDeferred,
    ModelRetry,
    RunCancelled,
    SkipToolExecution,
    ToolFailed,
)
from pydantic_ai.toolsets import CombinedToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from .errors import GateRequired

# Control-flow, not failure: these mean something other than "the tool blew
# up" and must reach their own handlers untouched.
_PASSTHROUGH: tuple[type[BaseException], ...] = (
    ModelRetry,
    GateRequired,
    ApprovalRequired,
    CallDeferred,
    SkipToolExecution,
    ToolFailed,
    RunCancelled,
)


class ToolErrorFeedback(WrapperToolset):
    """Wrap a toolset so unexpected tool exceptions become ModelRetry."""

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[Any],
        tool: ToolsetTool[Any],
    ) -> Any:
        try:
            return await super().call_tool(name, tool_args, ctx, tool)
        except _PASSTHROUGH as passthrough:
            raise passthrough from None
        except Exception as exc:
            raise ModelRetry(
                f'Tool {name!r} failed unexpectedly: {type(exc).__name__}: {exc}. '
                'Fix the cause and call the tool again.'
            ) from exc


def error_feedback_toolset(toolsets) -> ToolErrorFeedback:
    """Wrap toolset(s) with ToolErrorFeedback (one call site per Agent, so
    the main agent and delegation sub-agents behave alike)."""
    from pydantic_ai.toolsets import AbstractToolset

    if isinstance(toolsets, (AbstractToolset,)):
        return ToolErrorFeedback(toolsets)
    return ToolErrorFeedback(CombinedToolset(list(toolsets)))
