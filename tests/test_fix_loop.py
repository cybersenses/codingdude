"""Fix-until-green loop: test runs feed failures back, iterations capped."""

from helpers import scripted

from codingdude.approvals import ApprovalPolicy
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)

# A "test command" that fails on the first run and passes afterwards.
_attempts = {'n': 0}


def flaky_command():
    global _attempts
    return _attempts


async def test_fix_loop_runs_tests_and_converges(engine, workdir):
    marker = workdir / 'flag.txt'

    def agent_behavior(messages: list[ModelMessage], info):
        calls = sum(1 for m in messages for p in m.parts if p.part_kind == 'tool-call')
        if calls == 0:
            return ModelResponse(parts=[TextPart(content='working on it')])
        return ModelResponse(parts=[TextPart(content='attempted fixes')])

    # Deterministic "tests": pass only once the flag file exists.
    def shell_like(command: str):
        if marker.exists():
            return 0, 'all tests passed'
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('go')
        return 1, '1 failed'

    outcome_fail = None

    async def fake_test(command):
        code, out = shell_like(command)
        return code, out

    # Use the engine's test-loop through the real machinery by pre-approving
    # and pointing test_command at a script that flips the flag on first run.
    script = workdir / 'run_tests.sh'
    script.write_text(
        '#!/usr/bin/env bash\n'
        'if [ -f flag.done ]; then echo "all tests passed"; exit 0; fi\n'
        'touch flag.done\n'
        'echo "1 failed"\n'
        'exit 1\n'
    )

    outcome = await engine.run(
        prompt='make the tests pass',
        workdir=workdir,
        model=scripted(agent_behavior),
        approvals=ApprovalPolicy(),
        fix_loop=True,
        test_command=f'bash {script}',
        max_test_iterations=2,
    )
    # The loop ran tests, failed, fed back; final status complete.
    assert outcome.status == 'complete'
