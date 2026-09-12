"""Tests for the ContextManager (token estimation, limits, importance)."""
from codingdude.context import ContextManager


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
