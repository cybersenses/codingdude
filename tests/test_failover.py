"""Failover: a dead primary model transparently falls back."""

from helpers import say, scripted
from pydantic_ai.exceptions import ModelAPIError


def dead(messages, info):
    raise ModelAPIError(model_name='dead-primary', message='unavailable')


async def test_dead_primary_falls_back(engine, workdir):
    outcome = await engine.run(
        prompt='hi',
        workdir=workdir,
        model=engine.build_model(
            main=scripted(dead), fallback=scripted(say('from fallback'))
        ),
    )
    assert outcome.output == 'from fallback'


async def test_healthy_primary_never_touches_fallback(engine, workdir):
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


async def test_fallback_without_credentials_is_dropped(engine, workdir, monkeypatch):
    """No ZAI key configured → the run still works, just without the safety net."""
    monkeypatch.delenv('ZAI_API_KEY', raising=False)

    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=engine.build_model(main=scripted(say('solo')))
    )
    assert outcome.output == 'solo'


async def test_fallback_base_url_builds_fallback_model(engine, workdir, monkeypatch):
    """A custom fallback endpoint (e.g. GLM coding plan) is honored."""
    from codingdude.config import Config, ModelLineup, ShellConfig
    from codingdude.engine import Engine

    monkeypatch.setenv('ZAI_API_KEY', 'dummy-key')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'dummy-key')
    config = Config(
        models=ModelLineup(
            main='deepseek:deepseek-v4-pro',
            subagent='deepseek:deepseek-v4-flash',
            fallback='zai:glm-5.3',
            fallback_base_url='https://api.z.ai/api/coding/paas/v4',
        ),
        shell=ShellConfig(),
    )
    fallback_engine = Engine(config=config, db=engine._db)
    model = fallback_engine.build_model()
    assert type(model).__name__ == 'FallbackModel'
    fallback = model.models[-1]
    assert 'coding/paas/v4' in str(fallback.client.base_url)
