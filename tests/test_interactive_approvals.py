"""Engine seam: interactive approvals — the async `ask` callback flow."""

from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from codingdude.approvals import APPROVED, NEEDS_GATE, ApprovalPolicy
from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine


def shell_then_answer(command: str, answer_check):
    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name='shell', args={'command': command})])
        parts = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, (ToolReturnPart, RetryPromptPart))
        ]
        return ModelResponse(parts=[TextPart(content=answer_check('\n'.join(parts)))])

    return scripted(fn)


def engine_with_ask(home, ask):
    policy = ApprovalPolicy()
    policy.ask = ask
    engine = Engine(config=load_config(), db=Database.connect(home))
    return engine, policy


async def test_ask_approve_lets_command_run(home, workdir):
    asked = []

    async def ask(command):
        asked.append(command)
        return 'approve'

    engine, policy = engine_with_ask(home, ask)
    outcome = await engine.run(
        prompt='greet',
        workdir=workdir,
        approvals=policy,
        model=shell_then_answer('printf hello-interactive', lambda r: (
            'ran' if 'hello-interactive' in r else 'no'
        )),
    )
    assert outcome.status == 'complete'
    assert asked == ['printf hello-interactive']
    assert outcome.output == 'ran'


async def test_ask_deny_returns_refusal_to_model(home, workdir):
    async def ask(command):
        return 'deny'

    engine, policy = engine_with_ask(home, ask)
    outcome = await engine.run(
        prompt='greet',
        workdir=workdir,
        approvals=policy,
        model=shell_then_answer('printf nope', lambda r: (
            'refused-ack' if 'denied' in r.lower() else 'no-refusal'
        )),
    )
    assert outcome.status == 'complete'
    assert outcome.output == 'refused-ack'


async def test_ask_pattern_persists_for_future_runs(home, workdir):
    answers = iter(['pattern'])

    async def ask(command):
        return next(answers)

    engine, policy = engine_with_ask(home, ask)
    first = await engine.run(
        prompt='greet',
        workdir=workdir,
        approvals=policy,
        model=shell_then_answer('printf hello-pattern', lambda r: 'done'),
    )
    assert first.status == 'complete'
    # The pattern is persisted, not just in-memory.
    assert engine._db.session_patterns(first.session_id) == ['printf']

    # A later run with a fresh policy (no ask) runs ungated via the pattern.
    second = await engine.run(
        prompt='greet again',
        workdir=workdir,
        session_id=first.session_id,
        approvals=ApprovalPolicy(),
        model=shell_then_answer('printf hello-pattern', lambda r: (
            'ungated' if 'hello-pattern' in r else 'no'
        )),
    )
    assert second.output == 'ungated'


async def test_ask_on_always_gated_pattern_never_persists(home, workdir):
    git_init(workdir)
    asked = []

    async def ask(command):
        asked.append(command)
        return 'pattern'  # user clicked approve-all on a push: must NOT persist

    engine, policy = engine_with_ask(home, ask)
    outcome = await engine.run(
        prompt='push',
        workdir=workdir,
        approvals=policy,
        model=shell_then_answer('git push origin main', lambda r: 'done'),
    )
    assert outcome.status == 'complete'  # single approve went through
    assert engine._db.session_patterns(outcome.session_id) == []  # nothing persisted


async def test_ask_pattern_for_interpreter_persists_exact_command(home, workdir):
    """Self-review C1: approving an interpreter command persists that exact
    command, never the bare binary, so a sibling `python -c` stays gated."""
    async def ask(command):
        return 'pattern'

    engine, policy = engine_with_ask(home, ask)
    cmd = 'python -m pytest -q'
    first = await engine.run(
        prompt='run the tests', workdir=workdir, approvals=policy,
        model=shell_then_answer(cmd, lambda r: 'done'),
    )
    assert first.status == 'complete'
    assert engine._db.session_patterns(first.session_id) == [cmd]

    # Reloading the persisted session pattern into a fresh policy approves the
    # exact command but still gates a sibling python invocation.
    fresh = ApprovalPolicy()
    fresh.patterns.update(engine._db.session_patterns(first.session_id))
    assert fresh.decide(cmd) == APPROVED
    assert fresh.decide('python -c "print(1)"') == NEEDS_GATE


def git_init(workdir):
    import subprocess
    subprocess.run(['git', 'init', '-b', 'main'], cwd=workdir, capture_output=True)


async def test_headless_still_aborts_without_ask(home, workdir):
    """ADR-0003: no ask callback (headless) → gate aborts the run."""
    engine, policy = engine_with_ask(home, None)
    outcome = await engine.run(
        prompt='greet',
        workdir=workdir,
        approvals=policy,
        model=shell_then_answer('printf hello-headless', lambda r: 'should-not-finish'),
    )
    assert outcome.status == 'gate_aborted'
