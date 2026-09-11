"""Skills: registry scan, index-in-context, progressive-disclosure load tool."""

import json

from helpers import scripted
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolReturnPart,
)

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine
from codingdude.skills import SkillRegistry


def write_skill(base, name, description, body):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / 'SKILL.md').write_text(
        json.dumps({'name': name, 'description': description}) + '\n\n' + body
    )


def test_registry_global_library(home, workdir):
    write_skill(home / 'skills', 'tdd', 'Global tdd description', 'global body')
    write_skill(home / 'skills', 'debugging', 'Debug procedures', 'debug body')
    # Project-level skill dirs are ignored: the library is global by design.
    write_skill(workdir / '.codingdude' / 'skills', 'tdd', 'Project tdd description', 'project body')

    reg = SkillRegistry(home)
    index = reg.index()
    by_name = {s['name']: s for s in index}
    assert set(by_name) == {'tdd', 'debugging'}
    assert by_name['tdd']['description'] == 'Global tdd description'

    assert reg.load('tdd') == 'global body'
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


def test_matching_ranks_and_bounds(home):
    write_skill(home / 'skills', 'tdd', 'TDD', 'loop body ' * 10)
    d = home / 'skills' / 'diagnosing'
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_text(
        json.dumps({
            'name': 'diagnosing',
            'description': 'x',
            'triggers': ['flaky', 'regression'],
        }) + '\n\nlong body ' * 200
    )
    reg = SkillRegistry(home)

    hits = reg.matching('a flaky regression appeared')
    assert [s['name'] for s in hits] == ['diagnosing']  # longer trigger wins

    # all trigger words in any order match
    assert [s['name'] for s in reg.matching('regression that is flaky')] == ['diagnosing']
    # no match, no noise
    assert reg.matching('hello world') == []
    # limit caps the number of pre-loads
    assert len(reg.matching('flaky', limit=1)) == 1


async def test_engine_preloads_triggered_skill(home, workdir):
    d = home / 'skills' / 'sparkly'
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_text(
        json.dumps({
            'name': 'sparkly',
            'description': 'Shiny procedure',
            'triggers': ['zyzzx'],
        }) + '\n\nSPARKLE-PROCEDURE-CONTENT'
    )
    write_skill(home / 'skills', 'other', 'Unrelated', 'OTHER-CONTENT')

    def instruction_echo(messages, info):
        text = (getattr(info, 'instructions', '') or '')
        return ModelResponse(parts=[TextPart(content=text[-8000:])])

    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(
        prompt='please apply zyzzx to this', workdir=workdir, model=scripted(instruction_echo)
    )
    assert 'SPARKLE-PROCEDURE-CONTENT' in outcome.output  # auto-loaded, no tool call
    assert 'auto-triggered' in outcome.output
    assert 'OTHER-CONTENT' not in outcome.output  # non-matching skill not loaded


async def test_load_skill_tool_fetches_body(home, workdir):
    write_skill(home / 'skills', 'tdd', 'TDD playbook', 'RED-GREEN-REFACTOR loop')

    def skill_loader(messages, info):
        if not any(p.part_kind == 'tool-call' for m in messages for p in m.parts):
            from pydantic_ai.messages import ToolCallPart
            return ModelResponse(
                parts=[ToolCallPart(tool_name='load_skill', args={'name': 'tdd'})]
            )
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


def test_companion_files_load_and_traversal_blocked(home, workdir):
    d = home / 'skills' / 'tdd'
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_text(
        json.dumps({'name': 'tdd', 'description': 'x'}) + '\n\nloop body'
    )
    (d / 'tests.md').write_text('good tests live at seams')

    reg = SkillRegistry(home)
    assert reg.companions('tdd') == ['tests.md']
    assert reg.load('tdd', 'tests.md') == 'good tests live at seams'
    assert reg.load('tdd', 'missing.md') is None
    assert reg.load('tdd', '../../config.toml') is None
    assert reg.load('tdd', 'subdir/../../escape.txt') is None
    assert reg.companions('nope') == []


def test_crlf_skill_file_still_parses(home, workdir):
    d = home / 'skills' / 'tdd'
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_bytes(
        (json.dumps({'name': 'tdd', 'description': 'CRLF skill'}) + '\r\n\r\nbody\r\n').encode()
    )

    reg = SkillRegistry(home)
    assert reg.index()[0]['description'] == 'CRLF skill'
    assert reg.load('tdd') == 'body'


async def test_load_skill_appends_companion_listing(home, workdir):
    from codingdude.skills import SkillRegistry, build_skills_toolset

    write_skill(home / 'skills', 'tdd', 'TDD playbook', 'loop body')
    (home / 'skills' / 'tdd' / 'tests.md').write_text('seam examples')
    toolset = build_skills_toolset(SkillRegistry(home))
    load = toolset.tools['load_skill'].function

    body = load('tdd')
    assert 'loop body' in body
    assert 'tests.md' in body
    assert 'Skill directory:' in body  # lets skills locate sibling scripts
    assert load('tdd', file='tests.md') == 'seam examples'
