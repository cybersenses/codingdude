"""Engine seam: Budget Cap — optional hard stop on session spend."""

import pytest

from helpers import scripted

from codingdude.approvals import ApprovalPolicy
from codingdude.config import Config, ModelLineup, ShellConfig
from codingdude.db import Database
from codingdude.engine import Engine
from codingdude.exceptions import BudgetExceeded
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage


def costly(text: str, cost: float) -> FunctionModel:
    def fn(messages, info):
        return ModelResponse(
            parts=[TextPart(content=text)],
            usage=RunUsage(cost=cost, input_tokens=10, output_tokens=10, requests=1),
        )

    async def stream_fn(messages, info):
        yield text

    return FunctionModel(fn, stream_function=stream_fn, model_name='costly')


def make_engine(home, cap_usd):
    config = Config(
        models=ModelLineup(
            main='deepseek:deepseek-v4-pro',
            subagent='deepseek:deepseek-v4-flash',
            fallback='zai:glm-5.3',
        ),
        shell=ShellConfig(),
    )
    return Engine(config=config, db=Database.connect(home), budget_cap_usd=cap_usd)


async def test_no_cap_unchanged(home, workdir):
    engine = make_engine(home, cap_usd=None)
    outcome = await engine.run(prompt='x', workdir=workdir, model=scripted(scripted_say('ok')))
    assert outcome.output == 'ok'


def scripted_say(text):
    def fn(messages, info):
        return ModelResponse(parts=[TextPart(content=text)])

    return fn


async def test_cap_hard_stops_when_crossed(home, workdir):
    engine = make_engine(home, cap_usd=1.0)
    db = engine._db
    session_id = db.create_session(workdir, title='capped')
    db.record_usage(session_id, model='m', cost_usd=0.90)  # prior spend

    with pytest.raises(BudgetExceeded) as excinfo:
        await engine.run(
            prompt='more', workdir=workdir, session_id=session_id,
            model=costly('spending', cost=0.50),
        )
    assert excinfo.value.spent_usd == pytest.approx(1.40)
    # The run that crossed the cap still had its usage recorded (meter truth).
    assert db.session_usage(session_id)['cost_usd'] == pytest.approx(1.40)


async def test_pre_run_check_blocks_already_over_budget(home, workdir):
    engine = make_engine(home, cap_usd=1.0)
    db = engine._db
    session_id = db.create_session(workdir, title='over')
    db.record_usage(session_id, model='m', cost_usd=1.50)

    def must_not_run(messages, info):
        raise AssertionError('no model call may happen once over budget')

    with pytest.raises(BudgetExceeded):
        await engine.run(
            prompt='more', workdir=workdir, session_id=session_id,
            model=scripted(must_not_run),
        )


async def test_cap_survives_yolo(home, workdir):
    engine = make_engine(home, cap_usd=1.0)
    db = engine._db
    session_id = db.create_session(workdir, title='capped-yolo')
    db.record_usage(session_id, model='m', cost_usd=0.99)

    with pytest.raises(BudgetExceeded):
        await engine.run(
            prompt='more', workdir=workdir, session_id=session_id,
            model=costly('spending', cost=0.50),
            approvals=ApprovalPolicy(yolo=True),
        )
