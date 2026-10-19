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
"""Gold-task benchmark harness (ticket 22).

Run gold tasks against the engine and check observable outcomes. Two modes:

- scripted (default): model responses are canned — validates the harness and
  regressions in engine behavior, no API keys needed. Runs in CI via pytest.
- live (--live): real model calls; costs money and needs keys. For manual
  before/after comparisons when changing prompts or models.

Adding a gold task: append a GoldTask to TASKS. `check(outcome, workdir)`
returns None on success or a failure string.
"""

import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine

sys.path.insert(0, str(Path(__file__).parent / 'tests'))
from helpers import scripted


@dataclass
class GoldTask:
    name: str
    prompt: str
    setup: object  # callable(workdir) -> None
    check: object  # callable(outcome, workdir) -> str | None


def _setup_edit_task(workdir):
    (workdir / 'app.py').write_text('def greet():\n    return "hi"\n')


def _check_edit(outcome, workdir):
    content = (workdir / 'app.py').read_text()
    if 'hello' not in content:
        return 'greeting was not changed to hello'


def _setup_plan_task(workdir):
    pass


def _check_plan(outcome, workdir):
    if outcome.status != 'gate_aborted':
        return 'headless plan should abort (ADR-0003)'
    if 'plan' not in outcome.gate.command:
        return 'gate report should mention the plan'


def _check_directive(outcome, workdir):
    if 'zebra' not in outcome.output:
        return 'directive in DIRECTIVES.md was not followed'


TASKS = [
    GoldTask(
        name='edit-surgical',
        prompt='Change the greeting in app.py from "hi" to "hello". Use edit_file.',
        setup=_setup_edit_task,
        check=_check_edit,
    ),
    GoldTask(
        name='directive-compliance',
        prompt='say hi',
        setup=lambda workdir: None,
        check=_check_directive,
    ),
    GoldTask(
        name='plan-headless-abort',
        prompt='Design and build a whole caching layer with three modules.',
        setup=_setup_plan_task,
        check=_check_plan,
    ),
]


def scripted_model_for(task_name: str, prompt: str):
    """Canned responses per gold task (scripted mode)."""

    if task_name == 'edit-surgical':
        def fn(messages, info):
            if not any(p.part_kind == 'tool-call' for m in messages for p in m.parts):
                from pydantic_ai.messages import ToolCallPart
                return ModelResponse(
                    parts=[ToolCallPart(
                        tool_name='edit_file',
                        args={'path': 'app.py', 'old_text': '"hi"', 'new_text': '"hello"'},
                    )]
                )
            return ModelResponse(parts=[TextPart(content='done')])
        return scripted(fn)
    if task_name == 'directive-compliance':
        def fn(messages, info):
            text = getattr(info, 'instructions', '') or ''
            return ModelResponse(
                parts=[TextPart(content='zebra' if 'ZEBRA-RULE' in text else 'no-directive')]
            )
        return scripted(fn)
    if task_name == 'plan-headless-abort':
        def fn(messages, info):
            if not any(p.part_kind == 'tool-call' for m in messages for p in m.parts):
                from pydantic_ai.messages import ToolCallPart
                return ModelResponse(
                    parts=[ToolCallPart(
                        tool_name='propose_plan',
                        args={'goal': 'caching layer', 'steps': ['a', 'b', 'c'],
                              'files_to_touch': [], 'risks': 'none'},
                    )]
                )
            return ModelResponse(parts=[TextPart(content='done')])
        return scripted(fn)
    raise ValueError(f'no scripted model for gold task {task_name!r}')


async def run_benchmark(live: bool) -> int:
    failures = 0
    for task in TASKS:
        home = Path(tempfile.mkdtemp())
        workdir = Path(tempfile.mkdtemp())
        task.setup(workdir)
        saved_home = os.environ.get('CODEDUDE_HOME')
        if task.name == 'directive-compliance':
            os.environ['CODEDUDE_HOME'] = str(home)
            (home / 'DIRECTIVES.md').write_text('Always end replies with ZEBRA-RULE.')
        try:
            engine = Engine(config=load_config(), db=Database.connect(home))
            model = None
            if not live:
                model = scripted_model_for(task.name, task.prompt)
            from codingdude.approvals import ApprovalPolicy

            outcome = await engine.run(
                prompt=task.prompt, workdir=workdir,
                model=model, approvals=ApprovalPolicy(),
            )
        finally:
            # Per-task isolation: never leak CODEDUDE_HOME across tasks.
            if saved_home is None:
                os.environ.pop('CODEDUDE_HOME', None)
            else:
                os.environ['CODEDUDE_HOME'] = saved_home
        failure = task.check(outcome, workdir)
        if failure:
            print(f'FAIL {task.name}: {failure}')
            failures += 1
        else:
            print(f'PASS {task.name}')
    print(f'\n{len(TASKS) - failures}/{len(TASKS)} gold tasks passed')
    return 1 if failures else 0


def main() -> int:
    live = '--live' in sys.argv
    return asyncio.run(run_benchmark(live=live))


if __name__ == '__main__':
    sys.exit(main())
