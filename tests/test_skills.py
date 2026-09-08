"""Skills: registry scan, index-in-context, progressive-disclosure load tool."""

import json

from helpers import scripted

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine
from codingdude.skills import SkillRegistry
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def write_skill(base, name, description, body):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / 'SKILL.md').write_text(
        json.dumps({'name': name, 'description': description}) + '\n\n' + body
    )


def test_registry_merges_global_and_project_project_wins(home, workdir):
    write_skill(home / 'skills', 'tdd', 'Global tdd description', 'global body')
    write_skill(home / 'skills', 'debugging', 'Debug procedures', 'debug body')
    write_skill(workdir / '.codingdude' / 'skills', 'tdd', 'Project tdd description', 'project body')

    reg = SkillRegistry(home, workdir)
    index = reg.index()
    by_name = {s['name']: s for s in index}
    assert set(by_name) == {'tdd', 'debugging'}
    assert by_name['tdd']['description'] == 'Project tdd description'
    assert by_name['debugging']['description'] == 'Debug procedures'

    assert reg.load('tdd') == 'project body'
    assert reg.load('debugging') == 'debug body'
    assert reg.load('nope') is None


async def test_index_injected_into_instructions(home, workdir):
    write_skill(home / 'skills', 'tdd', 'Test-driven development playbook', 'body')

    def instruction_echo(messages, info):
        text = (getattr(info, 'instructions', '') or '')
        return ModelResponse(parts=[TextPart(content=text[-6000:])])

    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(prompt='hi', workdir=workdir, model=scripted(instruction_echo))
    assert 'Test-driven development playbook' in outcome.output
    assert 'body' not in outcome.output  # progressive disclosure: body NOT in context


async def test_load_skill_tool_fetches_body(home, workdir):
    write_skill(home / 'skills', 'tdd', 'TDD playbook', 'RED-GREEN-REFACTOR loop')

    def skill_loader(messages, info):
        if not any(p.part_kind == 'tool-call' for m in messages for p in m.parts):
            from pydantic_ai.messages import ToolCallPart
            return ModelResponse(
                parts=[ToolCallPart(tool_name='load_skill', args={'name': 'tdd'})]
            )
        from pydantic_ai.messages import ToolReturnPart
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        return ModelResponse(
            parts=[TextPart(content='loaded' if 'RED-GREEN-REFACTOR' in '\n'.join(returns) else 'no')]
        )

    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(
        prompt='load the tdd skill', workdir=workdir, model=scripted(skill_loader)
    )
    assert outcome.output == 'loaded'
