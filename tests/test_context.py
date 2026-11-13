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
"""Tests for the ContextManager (token estimation, limits, importance)."""
from codingdude.context import ContextManager, mechanical_compact, model_limit_for


class FakePart:
    def __init__(self, content: str, part_kind: str = "text"):
        self.content = content
        self.part_kind = part_kind


class FakeMessage:
    def __init__(self, *parts):
        self.parts = list(parts)


def test_estimate_tokens():
    cm = ContextManager()
    assert cm.estimate_tokens("hello world") == 2
    assert cm.estimate_tokens("") == 0
    assert cm.estimate_tokens("a" * 400) == 100


def test_usage_percent():
    cm = ContextManager(model_limit=1000)
    messages = [FakeMessage(FakePart("x" * 400))]
    stats = cm.usage(messages)
    assert 0 < stats.usage_percent <= 1
    assert stats.total_tokens == 100  # 400 chars / 4


def test_importance_scoring():
    cm = ContextManager()
    user_msg = FakeMessage(FakePart("deploy now", "user-prompt"))
    error_result = FakeMessage(FakePart("exit 1: test failed", "tool-return"))
    normal = FakeMessage(FakePart("some output", "text"))
    assert cm.importance(user_msg) >= 8
    assert cm.importance(error_result) >= 9
    assert cm.importance(normal) == 5


def test_needs_compaction():
    cm = ContextManager(model_limit=100, compact_at=0.80)
    small = [FakeMessage(FakePart("x" * 100))]
    large = [FakeMessage(FakePart("x" * 1000))]
    assert not cm.usage(small).needs_compaction
    assert cm.usage(large).needs_compaction


def test_model_limit_for():
    # Known provider names resolve from the table.
    assert model_limit_for("deepseek:deepseek-v4-pro") == 128_000
    assert model_limit_for("zai:glm-5.3") == 200_000
    # Unknown names fall back to the default.
    assert model_limit_for("openai:gpt-99") == 128_000
    # An explicit config override always wins.
    assert model_limit_for("zai:glm-5.3", override=64_000) == 64_000


def test_tool_call_args_count_toward_usage():
    # A real ToolCallPart has NO .content attribute — its JSON args ride in
    # .args (the deepseek-400 incident: 400k chars of args estimated as 0).
    class FakeToolCall:
        part_kind = "tool-call"

        def __init__(self, args):
            self.args = args

    cm = ContextManager()
    msg = FakeMessage(FakeToolCall('{"path": "' + "x" * 400 + '"}'))
    assert cm.message_tokens(msg) >= 100  # 400+ chars of args, not 0


def test_binary_content_counts_flat():
    # str(BinaryContent) stringifies megabytes of bytes (~2000x overcount);
    # images are billed a flat per-image token cost instead.
    class FakeBinary:
        data = b"\x89PNG" + b"\x00" * (3 * 1024 * 1024)
        part_kind = "user-prompt"

    cm = ContextManager()
    msg = FakeMessage(FakeBinary())
    assert 0 < cm.message_tokens(msg) <= 5000


def test_non_ascii_counts_heavier():
    # CJK text runs ~1 token per char, not 4 chars per token; 2 chars/token
    # is the documented approximation (under-triggering 2x is safer than 4x).
    cm = ContextManager()
    ascii_tokens = cm.message_tokens(FakeMessage(FakePart("a" * 400)))
    cjk_tokens = cm.message_tokens(FakeMessage(FakePart("好" * 400)))
    assert cjk_tokens >= ascii_tokens * 2


# --- mechanical_compact (R91 #337): per-request, LLM-free compaction ---


class FakeToolReturn:
    """Tool-return part shaped like pydantic-ai's (content + part_kind)."""

    def __init__(self, content: str, part_kind: str = "tool-return"):
        self.content = content
        self.part_kind = part_kind


def _over_limit_history(cm: ContextManager) -> list:
    """Old big tool returns (5), then the recent 10 messages. Crosses
    compact_at so mechanical_compact has work to do."""
    old = [FakeMessage(FakeToolReturn("r" * 4000)) for _ in range(5)]
    recent = [FakeMessage(FakePart(f"turn {i}")) for i in range(10)]
    return old + recent


def test_mechanical_compact_stubs_old_tool_returns():
    # Budget, not message count: 5 x 1000 tokens of returns vs a 3000-token
    # keep budget (50% of 6000) — everything past the budget is stubbed.
    cm = ContextManager(model_limit=6_000)
    history = _over_limit_history(cm)
    assert cm.usage(history).needs_compaction  # 5010/6000 > 0.80
    compacted, cleared = mechanical_compact(history, cm)
    # Worked example of the budget walk (keep budget = 6000 x 0.5 = 3000):
    # newest-first, the 10 recent turns cost ~10 tokens; each big return
    # costs 1000; adding the third return reaches 3010 > 3000, so the walk
    # stops there and idx 0..2 (returns 1-3, the oldest) are stubbed.
    assert cleared == 3
    assert compacted[:3] != history[:3]  # stubbed
    assert compacted[3:5] == history[3:5]  # newest two returns kept
    assert compacted[5:] == history[5:]
    # ...no parts dropped (tool-call/result pairing survives validation).
    assert [len(m.parts) for m in compacted] == [len(m.parts) for m in history]
    # The result is actually under the trigger.
    assert not cm.usage(compacted).needs_compaction


def test_mechanical_compact_stubs_big_returns_inside_the_window():
    # pydantic-ai merges consecutive user turns in-run, so message-count
    # windows lie: big returns can sit inside the newest 10 MESSAGES. The
    # budget walk still reclaims the oldest of them (2 of 5 here) — size,
    # not recency-by-count, decides what gets stubbed.
    cm = ContextManager(model_limit=6_000)
    history = [FakeMessage(FakePart("start"))]
    history += [FakeMessage(FakeToolReturn("r" * 4000)) for _ in range(5)]
    history += [FakeMessage(FakePart("a")) for _ in range(3)]
    assert cm.usage(history).needs_compaction
    compacted, cleared = mechanical_compact(history, cm)
    # Budget walk: newest 3 tiny messages, then 3 big returns fill the
    # 3000-token budget; returns 4 and 5 are stubbed (still inside any
    # message-count window — the window would have kept all five).
    assert cleared == 2


def test_mechanical_compact_noop_under_threshold():
    cm = ContextManager(model_limit=100_000)
    history = [FakeMessage(FakeToolReturn("small"))]
    compacted, cleared = mechanical_compact(history, cm)
    assert cleared == 0
    assert compacted == history


def test_mechanical_compact_keeps_user_prompts_verbatim():
    # User intent is never stubbed, wherever it sits in the budget walk.
    cm = ContextManager(model_limit=6_000)
    history = [FakeMessage(FakePart("user intent", "user-prompt"))]
    history += [FakeMessage(FakeToolReturn("r" * 4000)) for _ in range(5)]
    history += [FakeMessage(FakePart("a")) for _ in range(3)]
    assert cm.usage(history).needs_compaction
    compacted, cleared = mechanical_compact(history, cm)
    for msg in compacted:
        if msg.parts[0].part_kind == "user-prompt":
            assert msg.parts[0].content == "user intent"


def test_mechanical_compact_truncates_oversized_recent_return():
    cm = ContextManager(model_limit=10_000)
    big = FakeToolReturn("x" * 50_000)
    history = [FakeMessage(big), FakeMessage(FakePart("now"))]
    compacted, cleared = mechanical_compact(history, cm,
                                            max_part_chars=8000)
    assert cleared == 1  # the oversized recent return had to be reclaimed
    assert len(compacted[0].parts[0].content) <= 8100  # cap + marker
    assert compacted[1] == history[1]


def test_mechanical_compact_does_not_mutate_input():
    cm = ContextManager(model_limit=6_000)
    history = _over_limit_history(cm)
    snapshot = [list(m.parts) for m in history]
    mechanical_compact(history, cm)
    assert [list(m.parts) for m in history] == snapshot
