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
"""Directives: global rules injected into every run, budget-capped, gate-protected."""


from helpers import scripted
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.directives import DIRECTIVES_BUDGET, DIRECTIVES_FILENAME, build_directive_layers
from codingdude.engine import Engine


def instruction_echo(messages, info):
    text = ''.join(
        str(p.content) for m in messages for p in m.parts if hasattr(p, 'content')
    )
    text += getattr(info, 'instructions', '') or ''
    return ModelResponse(parts=[TextPart(content=text[-6000:])])


def test_build_directive_layers_combines_global_and_project(home, workdir):
    home.mkdir(parents=True, exist_ok=True)
    (home / DIRECTIVES_FILENAME).write_text('GLOBAL RULE: prefer composition.')
    (workdir / 'AGENT.md').write_text('PROJECT RULE: never touch generated/.')
    layers = build_directive_layers(home, workdir)
    assert 'prefer composition' in layers
    assert 'never touch generated/' in layers


def test_directive_budget_truncates_global_first(home, workdir):
    home.mkdir(parents=True, exist_ok=True)
    (home / DIRECTIVES_FILENAME).write_text('G' * (DIRECTIVES_BUDGET + 500))
    (workdir / 'AGENT.md').write_text('PROJECT RULE: precious')
    layers = build_directive_layers(home, workdir)
    assert len(layers) <= DIRECTIVES_BUDGET + 200  # header + project, global truncated
    assert 'precious' in layers  # project layer survives the global overflow
    assert layers.endswith('[directives truncated]') or 'precious' in layers[-200:]


async def test_directives_reach_the_model(home, workdir):
    home.mkdir(parents=True, exist_ok=True)
    (home / DIRECTIVES_FILENAME).write_text('Always end replies with ZEBRA-RULE.')
    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=scripted(instruction_echo)
    )
    assert 'ZEBRA-RULE' in outcome.output


async def test_directives_file_edits_are_gated(home, workdir):
    """Editing DIRECTIVES.md needs approval even though it's inside the Workdir."""
    home.mkdir(parents=True, exist_ok=True)
    (workdir / DIRECTIVES_FILENAME).write_text('old rule\n')  # NB: inside workdir
    (home / DIRECTIVES_FILENAME).write_text('real one')

    def edit_directives(messages, info):
        if not any(p.part_kind == 'tool-call' for m in messages for p in m.parts):
            from pydantic_ai.messages import ToolCallPart
            return ModelResponse(
                parts=[ToolCallPart(
                    tool_name='edit_file',
                    args={'path': DIRECTIVES_FILENAME, 'old_text': 'old rule', 'new_text': 'new rule'},
                )]
            )
        from pydantic_ai.messages import RetryPromptPart
        retries = [str(p.content) for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]
        return ModelResponse(parts=[TextPart(content='gated' if retries else 'wrote-ungated')])

    from codingdude.approvals import ApprovalPolicy
    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(
        prompt='update the directives',
        workdir=workdir,
        approvals=ApprovalPolicy(),
        model=scripted(edit_directives),
    )
    # Directives files are gated like AGENT.md: interactive runs abort with a
    # report (ADR-0003) and the file stays untouched until approval.
    assert outcome.status == 'gate_aborted'
    assert 'DIRECTIVES.md' in outcome.gate.command
    assert 'old rule' in (workdir / DIRECTIVES_FILENAME).read_text()
