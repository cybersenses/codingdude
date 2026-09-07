"""Engine seam: shell tool, approval tiers, pattern approval, headless gates."""

from dataclasses import dataclass, field

from helpers import scripted

from codingdude.approvals import APPROVED, DENIED, NEEDS_GATE, ApprovalPolicy
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def shell_then_answer(command: str, answer_check):
    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name='shell', args={'command': command})])
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, (ToolReturnPart, RetryPromptPart))
        ]
        return ModelResponse(parts=[TextPart(content=answer_check(returns))])

    return scripted(fn)


def test_policy_tiers():
    policy = ApprovalPolicy()
    # reads and git reads are auto
    assert policy.decide('ls -la') == APPROVED
    assert policy.decide('git status') == APPROVED
    assert policy.decide('git log --oneline') == APPROVED
    # ordinary shell commands need a gate
    assert policy.decide('pytest -q') == NEEDS_GATE
    # always-gated tier: remote mutations and destructive ops
    assert policy.decide('git push origin main') == DENIED
    assert policy.decide('gh pr create --fill') == DENIED
    assert policy.decide('rm -rf src') == DENIED


def test_pattern_approval_unlocks_matching_commands_only():
    policy = ApprovalPolicy()
    assert policy.decide('pytest -q') == NEEDS_GATE
    policy.approve_pattern('pytest')
    assert policy.decide('pytest -q tests/') == APPROVED
    assert policy.decide('pytest') == APPROVED
    # patterns never unlock the always-gated tier
    policy.approve_pattern('git push')
    assert policy.decide('git push origin main') == DENIED


def test_yolo_unlocks_everything():
    policy = ApprovalPolicy(yolo=True)
    assert policy.decide('pytest -q') == APPROVED
    assert policy.decide('rm -rf src') == APPROVED
    assert policy.decide('git push') == APPROVED


async def test_approved_shell_runs_and_returns_output(engine, workdir):
    outcome = await engine.run(
        prompt='list files',
        workdir=workdir,
        model=shell_then_answer('ls', lambda r: 'ran' if any('README.md' in x for x in r) else 'no'),
        approvals=ApprovalPolicy(patterns={'ls'}),
    )
    assert outcome.output == 'ran'


async def test_gated_shell_aborts_headless_run_with_report(engine, workdir):
    outcome = await engine.run(
        prompt='run tests',
        workdir=workdir,
        model=shell_then_answer('pytest -q', lambda r: 'should-not-happen'),
        approvals=ApprovalPolicy(),
    )
    assert outcome.status == 'gate_aborted'
    assert outcome.gate is not None
    assert outcome.gate.command == 'pytest -q'


async def test_gate_approval_via_pattern_completes(engine, workdir):
    outcome = await engine.run(
        prompt='greet',
        workdir=workdir,
        model=shell_then_answer('printf hello-from-shell', lambda r: (
            'saw-output' if any('hello-from-shell' in x for x in r) else 'no-output'
        )),
        approvals=ApprovalPolicy(),
    )
    assert outcome.status == 'gate_aborted'

    # Pattern Approval is session-scoped: recorded once, picked up by later
    # runs on this Session even with a fresh policy object.
    engine.approve_pattern(outcome.session_id, 'printf hello-from-shell')
    outcome2 = await engine.run(
        prompt='greet again',
        workdir=workdir,
        session_id=outcome.session_id,
        model=shell_then_answer('printf hello-from-shell', lambda r: (
            'saw-output' if any('hello-from-shell' in x for x in r) else 'no-output'
        )),
        approvals=ApprovalPolicy(),
    )
    assert outcome2.status == 'complete'
    assert outcome2.output == 'saw-output'


async def test_always_gated_aborts_headless_run(engine, workdir):
    """DENIED commands abort with a report like gates do — not a silent retry."""
    outcome = await engine.run(
        prompt='ship it',
        workdir=workdir,
        model=shell_then_answer('git push origin main', lambda r: 'nope'),
        approvals=ApprovalPolicy(),
    )
    assert outcome.status == 'gate_aborted'
    assert 'git push' in outcome.gate.command


async def test_default_run_has_no_shell_tool(engine, workdir):
    """Without an ApprovalPolicy the shell tool isn't offered at all."""
    def must_not_have_shell(messages, info):
        names = {t.name for t in info.tools} if hasattr(info, 'tools') else set()
        return ModelResponse(parts=[TextPart(content=f"shell={'shell' in names}")])

    outcome = await engine.run(
        prompt='check tools', workdir=workdir, model=scripted(must_not_have_shell)
    )
    assert outcome.output == 'shell=False'


async def test_headless_exit_code_for_gate(engine, workdir):
    import codingdude.cli as cli

    code = cli.run_headless(
        engine, workdir, 'run tests',
        model=shell_then_answer('pytest -q', lambda r: 'nope'),
        approvals=ApprovalPolicy(),
    )
    assert code == 2
