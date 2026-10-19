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
"""Fix-until-green loop: test runs feed failures back, iterations capped."""

from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
)

from codingdude.approvals import ApprovalPolicy

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


async def test_fix_loop_bills_every_request_exactly_once(engine, workdir, capsys):
    """#81: the fix loop's retries plus the main run must total exactly one
    accounting pass — no double-billed retry, no lost main-run requests."""
    from pydantic_ai.usage import RunUsage

    def agent_behavior(messages, info):
        # First model request (main run) vs retry (history now contains the
        # failure feedback). Distinct usage per request so totals are exact.
        seen_failure = any(
            'still failing' in str(getattr(p, 'content', ''))
            for m in messages for p in m.parts
        )
        if seen_failure:
            return ModelResponse(
                parts=[TextPart(content='fixed now')],
                usage=RunUsage(input_tokens=20, output_tokens=7, requests=1),
            )
        return ModelResponse(
            parts=[TextPart(content='working on it')],
            usage=RunUsage(input_tokens=10, output_tokens=5, requests=1),
        )

    script = workdir / 'run_tests.sh'
    script.write_text(
        '#!/usr/bin/env bash\n'
        'if [ -f flag.done ]; then echo "all tests passed"; exit 0; fi\n'
        'touch flag.done\n'
        'echo "1 failed"\n'
        'exit 1\n'
    )

    events: list[dict] = []
    outcome = await engine.run(
        prompt='make the tests pass',
        workdir=workdir,
        model=scripted(agent_behavior),
        approvals=ApprovalPolicy(),
        fix_loop=True,
        test_command=f'bash {script}',
        max_test_iterations=2,
        emit=events.append,
    )
    assert outcome.status == 'complete'
    usage_events = [e for e in events if e['type'] == 'RUN_USAGE']
    # One accounting pass for the whole sequence (main run + retries).
    assert len(usage_events) == 1
    event = usage_events[0]
    assert event['input_tokens'] > 0 and event['output_tokens'] > 0
    # Exactly one usage row in the ledger — the old code double-billed the
    # retry (loop record_model_usage + finalize record_run_usage) and its
    # row disagreed with the event. (FunctionModel estimates tokens, so the
    # property under test is single, consistent accounting, not exact counts.)
    rows = list(engine._db._conn.execute(
        'select * from usage where session_id = ?', (outcome.session_id,)
    ).fetchall())
    assert len(rows) == 1
    assert rows[0]['requests'] == event['requests']
    assert rows[0]['input_tokens'] == event['input_tokens']


def test_sum_usages_adds_requests_tokens_and_costs():
    """#81: combined billing across fix-loop retries adds, never double-counts."""
    from pydantic_ai.usage import RunUsage

    from codingdude.telemetry import sum_usages

    a = RunUsage(input_tokens=10, output_tokens=5, requests=1)
    b = RunUsage(input_tokens=20, output_tokens=7, requests=1)
    b.cost = 0.5
    total = sum_usages([a, b])
    assert total.requests == 2
    assert total.input_tokens == 30
    assert total.output_tokens == 12
    assert total.cost == 0.5  # provider cost: sum of the parts that report one
    assert sum_usages([]).requests == 0
