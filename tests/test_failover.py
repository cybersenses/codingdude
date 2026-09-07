"""Failover: a dead primary model transparently falls back."""

from helpers import say, scripted

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine
from pydantic_ai.exceptions import ModelAPIError


def dead(messages, info):
    raise ModelAPIError(model_name='dead-primary', message='unavailable')


async def test_dead_primary_falls_back(home, workdir):
    config = load_config()
    db = Database.connect(home)
    engine = Engine(config=config, db=db)

    outcome = await engine.run(
        prompt='hi',
        workdir=workdir,
        model=engine.build_model(main=scripted(dead), fallback=scripted(say('from fallback'))),
    )
    assert outcome.output == 'from fallback'


async def test_healthy_primary_never_touches_fallback(home, workdir):
    config = load_config()
    db = Database.connect(home)
    engine = Engine(config=config, db=db)

    def must_not_run(messages, info):
        raise AssertionError('fallback model must not be called when primary is healthy')

    outcome = await engine.run(
        prompt='hi',
        workdir=workdir,
        model=engine.build_model(
            main=scripted(say('from primary')), fallback=scripted(must_not_run)
        ),
    )
    assert outcome.output == 'from primary'
