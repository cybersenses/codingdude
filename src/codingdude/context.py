"""Context window management: token estimation, limit monitoring, importance scoring.

Usage (from engine.run):
    cm = ContextManager(model_limit=128_000)
    stats = cm.usage(history)
    if stats.needs_compaction:
        history = compact(history)
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MODEL_LIMIT = 128_000
DEFAULT_COMPACT_AT = 0.80
CHARS_PER_TOKEN = 4

# Known context windows (tokens) by provider:model substring, most specific
# first. Anything unmatched falls back to DEFAULT_MODEL_LIMIT.
_MODEL_LIMITS: tuple[tuple[str, int], ...] = (
    ('glm-5', 200_000),
    ('glm-4.5', 128_000),
    ('glm', 128_000),
    ('deepseek', 128_000),
    ('claude', 200_000),
    ('gpt-4o', 128_000),
    ('gpt-5', 400_000),
    ('gemini-2', 1_000_000),
    ('gemini', 128_000),
)


def model_limit_for(name: str, override: int | None = None) -> int:
    """Context window (tokens) for a `provider:model` name.

    An explicit `models.context_limit` config override always wins; otherwise
    the known-limits table applies; otherwise the default.
    """
    if override:
        return override
    lower = name.lower()
    for needle, limit in _MODEL_LIMITS:
        if needle in lower:
            return limit
    return DEFAULT_MODEL_LIMIT


@dataclass(frozen=True)
class ContextStats:
    """Snapshot of context window usage."""

    total_tokens: int
    model_limit: int
    usage_percent: float
    message_count: int
    needs_compaction: bool


class ContextManager:
    """Tracks context window usage and decides when to compact.

    Usage:
        cm = ContextManager(model_limit=128_000, compact_at=0.80)
        stats = cm.usage(history)
        if stats.needs_compaction:
            history = compact(history)
    """

    def __init__(
        self,
        model_limit: int = DEFAULT_MODEL_LIMIT,
        compact_at: float = DEFAULT_COMPACT_AT,
    ):
        self.model_limit = model_limit
        self.compact_at = compact_at

    def estimate_tokens(self, text: str) -> int:
        """~4 chars per token for English/code."""
        return len(text) // CHARS_PER_TOKEN

    def message_tokens(self, message) -> int:
        total = 0
        for part in getattr(message, "parts", []):
            content = getattr(part, "content", None)
            if content:
                total += self.estimate_tokens(str(content))
        return total

    def total_tokens(self, messages) -> int:
        return sum(self.message_tokens(m) for m in messages)

    def usage(self, messages) -> ContextStats:
        total = self.total_tokens(messages)
        return ContextStats(
            total_tokens=total,
            model_limit=self.model_limit,
            usage_percent=total / self.model_limit if self.model_limit else 0.0,
            message_count=len(messages),
            needs_compaction=self.total_tokens(messages)
            >= self.model_limit * self.compact_at,
        )

    def importance(self, message) -> int:
        """Score a message's retention priority (1–9, higher = keep longer).

        user-prompt: 8 · tool-return with error: 9 · tool-return: 7 · default: 5
        """
        score = 5
        for part in getattr(message, "parts", []):
            kind = getattr(part, "part_kind", "")
            content = str(getattr(part, "content", ""))
            if kind == "user-prompt":
                score = max(score, 8)
            elif kind == "tool-return":
                lower = content.lower()
                if "error" in lower or "fail" in lower:
                    score = max(score, 9)
                elif "exit" in lower:
                    score = max(score, 7)
        return score

    def plan_compaction(self, messages, keep_recent: int = 10) -> tuple[list[int], list[int]]:
        """Partition messages into keep and summarise sets by importance.

        keep: recent + high-importance (score >= 7). summarise: rest.
        """
        n = len(messages)
        recent_start = max(0, n - keep_recent)
        keep, summarise = [], []
        for i, msg in enumerate(messages):
            imp = self.importance(msg)
            if i >= recent_start or imp >= 7:
                keep.append(i)
            else:
                summarise.append(i)
        return keep, summarise
