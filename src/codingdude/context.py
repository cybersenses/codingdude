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
"""Context window management: token estimation, limit monitoring, importance scoring.

Usage (from engine.run):
    cm = ContextManager(model_limit=128_000)
    stats = cm.usage(history)
    if stats.needs_compaction:
        history = compact(history)
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

DEFAULT_MODEL_LIMIT = 128_000
DEFAULT_COMPACT_AT = 0.80
CHARS_PER_TOKEN = 4
# Flat per-binary-item token cost (images etc.): providers bill images at a
# roughly fixed size-classed rate, NOT proportional to byte length. Never
# str() binary content — stringifying megabytes of bytes overcounts ~2000x.
IMAGE_TOKENS = 1_600
# Non-ASCII text (CJK-heavy strings): ~1 token per character in modern
# tokenizers vs 4 chars/token for English; 2 chars/token is the documented
# middle approximation. Undercounting by 2x beats undercounting by 4x.
NONASCII_CHARS_PER_TOKEN = 2

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
        """~4 chars per token for English/code; non-ASCII runs heavier.

        Non-ASCII characters are counted at NONASCII_CHARS_PER_TOKEN
        (approximation — the provider-reported count still wins wherever
        it is recorded, see HistoryManager.persist_actual_context).
        """
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        nonascii = len(text) - ascii_chars
        return ascii_chars // CHARS_PER_TOKEN + nonascii // NONASCII_CHARS_PER_TOKEN

    def message_tokens(self, message) -> int:
        """Estimated tokens for one message's wire payload.

        Counts what the request actually carries, not just readable text:
        tool-call JSON args (absent content), binary content as a flat
        per-item cost, non-ASCII text heavier than the 4-chars/token
        English approximation.
        """
        total = 0
        for part in getattr(message, "parts", []):
            kind = getattr(part, "part_kind", "")
            if kind == "tool-call":
                args = getattr(part, "args", None)
                if args:
                    total += self.estimate_tokens(str(args))
                continue
            content = getattr(part, "content", None)
            if content is None:
                data = getattr(part, "data", None)  # BinaryContent
                if isinstance(data, (bytes, bytearray)) and len(data):
                    total += IMAGE_TOKENS
                continue
            if isinstance(content, (bytes, bytearray)):
                if len(content):
                    total += IMAGE_TOKENS
                continue
            if hasattr(content, "data") and isinstance(
                getattr(content, "data", None), (bytes, bytearray)
            ):
                # BinaryContent wrapped object: flat cost, never str() it
                # (stringifying megabytes of bytes overcounts ~2000x).
                total += IMAGE_TOKENS
                continue
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


CLEARED_STUB = "[earlier tool result cleared to reclaim context]"
_TRUNCATED_MARK = "…[truncated to reclaim context]"


def mechanical_compact(
    messages,
    cm: ContextManager,
    *,
    keep_budget_fraction: float = 0.5,
    max_part_chars: int = 8000,
) -> tuple[list, int]:
    """LLM-free per-request compaction: stub/truncate oversized tool returns.

    Called when `cm.usage(messages).needs_compaction` before a model
    request (R91 #337). A token-budget walk from the newest message
    backwards keeps messages until their estimated tokens exhaust
    `keep_budget_fraction` of the model limit — a message-count window
    lies, because pydantic-ai merges consecutive user turns in-run and
    tool-return sizes vary wildly (the deepseek-400 shape). Tool-return
    parts past the budget are replaced by `CLEARED_STUB`; any oversized
    tool-return part is truncated to `max_part_chars` with a marker
    regardless of age. Parts are never dropped — tool-call/result pairing
    must survive pydantic-ai's history validation — and user-prompt parts
    stay verbatim wherever they sit. The input list and its messages are
    not mutated.

    Returns (new_messages, cleared_count).
    """
    if not cm.usage(messages).needs_compaction:
        return messages, 0
    keep_budget = cm.model_limit * keep_budget_fraction
    # Walk newest -> oldest; once the budget is spent, everything older
    # (by index) is eligible for stubbing.
    spent = 0
    budget_start = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        spent += cm.message_tokens(messages[i])
        if spent > keep_budget:
            budget_start = i + 1
            break
    else:
        budget_start = 0
    out: list = []
    cleared = 0
    for i, msg in enumerate(messages):
        parts = list(getattr(msg, "parts", []))
        new_parts = []
        changed = False
        for part in parts:
            kind = getattr(part, "part_kind", "")
            content = getattr(part, "content", None)
            if kind != "tool-return" or not isinstance(content, str):
                new_parts.append(part)
                continue
            if len(content) > max_part_chars:
                new_parts.append(
                    _replaced_part(part, content[:max_part_chars] + _TRUNCATED_MARK)
                )
                changed = True
            elif i < budget_start:
                new_parts.append(_replaced_part(part, CLEARED_STUB))
                changed = True
            else:
                new_parts.append(part)
        if changed:
            cleared += 1
            out.append(_cloned_message(msg, new_parts))
        else:
            out.append(msg)
    return out, cleared


def _replaced_part(part, text: str):
    """A copy of `part` carrying `text` as its content (type preserved)."""
    clone = copy.copy(part)
    clone.content = text
    return clone


def _cloned_message(msg, parts):
    clone = copy.copy(msg)
    clone.parts = parts
    return clone
