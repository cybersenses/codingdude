"""Repo map: tree + signatures within budget, engine injection."""

from helpers import scripted
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.repo_map import build_repo_map


def make_project(workdir):
    src = workdir / 'src'
    src.mkdir(exist_ok=True)
    (src / 'engine.py').write_text(
        'class Engine:\n'
        '    def start(self):\n        pass\n'
    )
    (src / 'util.py').write_text(
        'def helper(value):\n    return value\n'
    )


def test_map_includes_tree_and_signatures(workdir):
    make_project(workdir)
    m = build_repo_map(workdir)
    assert 'engine.py' in m
    assert 'class Engine' in m
    assert 'def start' in m
    assert 'def helper' in m


def test_budget_truncates_map(workdir):
    make_project(workdir)
    tiny = build_repo_map(workdir, budget=60)
    assert len(tiny) <= 62
    assert 'truncated' in tiny or tiny


async def test_repo_map_reaches_model_instructions(home, workdir):
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    make_project(workdir)
    engine = Engine(config=load_config(), db=Database.connect(home))

    def instruction_echo(messages, info):
        text = getattr(info, 'instructions', '') or ''
        return ModelResponse(parts=[TextPart(content=text[-6000:])])

    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=scripted(instruction_echo)
    )
    assert 'class Engine' in outcome.output
