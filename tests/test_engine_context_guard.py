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
"""R91 #337: engine-level wiring of the per-request context guard.

The guard's job is MID-RUN growth: run-start compaction cannot see a tool
return that pushes the history over the limit after request 1. These tests
grow the history through a real read_file of a big file and assert that
request 2 goes out compacted — and that `models.compact_per_request` gates
it.
"""
from __future__ import annotations

from dataclasses import replace

from helpers import scripted
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from codingdude.config import load_config
from codingdude.engine import Engine

CLEARED_STUB = "[earlier tool result cleared to reclaim context]"


def _responder(calls: list[list]):
    """Request 1 reads a big file (history balloons); request 2 finishes."""

    def fn(messages, info):
        calls.append(list(messages))
        if len(calls) == 1:
            return ModelResponse(parts=[
                ToolCallPart(tool_name="read_file",
                             args={"path": "big.txt"}, tool_call_id="c0"),
            ])
        return ModelResponse(parts=[TextPart(content="done")])

    return fn


def _engine(db, home, workdir, *, enabled: bool) -> Engine:
    config = load_config()
    config = replace(config, models=replace(
        config.models, context_limit=6_000, compact_per_request=enabled))
    return Engine(config=config, db=db)


async def test_engine_guard_compacts_mid_run_growth(db, home, workdir):
    (workdir / "big.txt").write_text("r" * 48_000, encoding="utf-8")
    guarded = _engine(db, home, workdir, enabled=True)
    calls: list[list] = []
    events: list = []
    outcome = await guarded.run(
        prompt="read big.txt and summarize", workdir=workdir,
        model=scripted(_responder(calls)), emit=events.append,
    )
    by_type = {e.get("type") for e in events if isinstance(e, dict)}
    assert "CONTEXT_COMPACTED" in by_type, by_type
    # Run-start accounting is untouched and still recorded.
    assert "CONTEXT_USAGE" in by_type
    assert len(calls) == 2
    # Request 2 saw the truncated head, not the 48k-char payload: the
    # oversized branch (max_part_chars) takes precedence over stubbing.
    returns_in_request_2 = [
        str(p.content) for m in calls[1] for p in m.parts
        if isinstance(p, ToolReturnPart)
    ]
    big = [s for s in returns_in_request_2 if s.startswith("rrrrr")]
    assert len(big) == 1
    assert len(big[0]) <= 8100  # cap + marker
    assert big[0].endswith("…[truncated to reclaim context]")
    # The persisted history itself was compacted (H7 persist of all_messages):
    # the stored return carries the truncation marker, not the full payload.
    stored = guarded._history.load(outcome.session_id)
    stored_stubs = [
        p for m in stored for p in m.parts
        if isinstance(p, ToolReturnPart)
        and "truncated to reclaim context" in str(p.content)
    ]
    assert len(stored_stubs) >= 1


async def test_engine_guard_off_keeps_full_return(db, home, workdir):
    (workdir / "big.txt").write_text("r" * 48_000, encoding="utf-8")
    ungated = _engine(db, home, workdir, enabled=False)
    calls: list[list] = []
    events: list = []
    await ungated.run(
        prompt="read big.txt and summarize", workdir=workdir,
        model=scripted(_responder(calls)), emit=events.append,
    )
    by_type = {e.get("type") for e in events if isinstance(e, dict)}
    assert "CONTEXT_COMPACTED" not in by_type, by_type
    assert len(calls) == 2
    full = [
        str(p.content) for m in calls[1] for p in m.parts
        if isinstance(p, ToolReturnPart)
    ]
    assert any(s.startswith("rrrrr") for s in full), full


async def test_fix_loop_retry_agent_carries_capabilities(
    db, home, workdir, monkeypatch,
):
    """R91 #337 review finding: the fix loop's retry agent must carry the
    same capabilities as the main agent — its `message_history` is the
    grown main-run history, so an unguarded retry re-ships the over-limit
    payload the guard exists to stop. Spied at the construction seam: the
    retries=1 agent is built with ProcessHistory iff the gate is on, and
    the retry request's payload reflects the guard's state."""
    from pydantic_ai.capabilities import ProcessHistory

    from codingdude.approvals import ApprovalPolicy
    from codingdude.run_pipeline import PromptAssembler

    (workdir / "big.txt").write_text("r" * 48_000, encoding="utf-8")
    (workdir / "fail.sh").write_text("#!/usr/bin/env bash\nexit 1\n")

    calls: list[list] = []
    constructions: list[dict] = []

    def fn(messages, info):
        calls.append(list(messages))
        if len(calls) == 1:
            return ModelResponse(parts=[
                ToolCallPart(tool_name="read_file",
                             args={"path": "big.txt"}, tool_call_id="c0"),
            ])
        return ModelResponse(parts=[TextPart(content="done")])

    real_agent = PromptAssembler.agent

    def spy(self, resolved, instructions, toolsets, settings=None,
            retries=5, capabilities=None):
        constructions.append(
            {'retries': retries, 'capabilities': capabilities})
        return real_agent(self, resolved, instructions, toolsets, settings,
                          retries=retries, capabilities=capabilities)

    monkeypatch.setattr(PromptAssembler, 'agent', spy)

    async def run_case(enabled: bool):
        calls.clear()
        constructions.clear()
        events: list = []
        engine = _engine(db, home, workdir, enabled=enabled)
        await engine.run(
            prompt="read big.txt and summarize", workdir=workdir,
            model=scripted(fn), emit=events.append,
            approvals=ApprovalPolicy(), fix_loop=True,
            test_command="bash fail.sh", max_test_iterations=1,
        )
        retry_built = [c for c in constructions if c['retries'] == 1]
        assert len(retry_built) == 1, constructions
        caps = retry_built[0]['capabilities'] or []
        guard = any(isinstance(c, ProcessHistory) for c in caps)
        compactions = [
            e for e in events if isinstance(e, dict)
            and e.get('type') == 'CONTEXT_COMPACTED'
        ]
        # Snapshot: `calls` is cleared by the next run_case, so copy now.
        return guard, [list(m) for m in calls], compactions

    guard_on, calls_on, compactions_on = await run_case(enabled=True)
    guard_off, calls_off, _ = await run_case(enabled=False)
    assert guard_on is True, "guarded main => guarded retry"
    assert guard_off is False, "gate off => no guard anywhere"
    assert compactions_on, "guard never fired on-gate"

    def biggest_return(requests, idx):
        sizes = [len(str(p.content)) for m in requests[idx] for p in m.parts
                 if isinstance(p, ToolReturnPart)
                 and str(p.content).startswith("rrrrr")]
        return max(sizes) if sizes else 0

    # calls[2] is the retry request. Under the guard this also shows the
    # in-place writeback at work: ProcessHistory mutates ctx.messages[:],
    # so run.new_messages() — the fix loop's history source — is already
    # compacted before the retry's own guard even runs.
    assert len(calls_on) == 3, len(calls_on)
    assert biggest_return(calls_on, 2) <= 8100  # cap + marker
    assert len(calls_off) == 3, len(calls_off)
    assert biggest_return(calls_off, 2) > 8100  # the unguarded 400 shape
