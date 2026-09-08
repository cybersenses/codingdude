"""Engine seam: planning — propose/approve/deny, step tracking, auto review."""


from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from codingdude.approvals import ApprovalPolicy
from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine
from codingdude.planning import PlanStore

STEPS = ['write the module', 'write the test', 'run the test']


def planner_flow(answers: list[str]):
    """Scripted model: propose → then per answer: 'approve' marks a step done,
    'deny' ends the run with a revision note. Answers exhausted → final text."""
    state = {'call': 0}

    def fn(messages: list[ModelMessage], info):
        i = state['call']
        state['call'] += 1
        if i == 0:
            return ModelResponse(
                parts=[ToolCallPart(
                    tool_name='propose_plan',
                    args={'goal': 'add feature', 'steps': STEPS,
                          'files_to_touch': ['feat.py'], 'risks': 'low'},
                )]
            )
        if i - 1 < len(answers):
            answer = answers[i - 1]
            if answer == 'deny':
                return ModelResponse(parts=[TextPart(content='will revise')])
            return ModelResponse(
                parts=[ToolCallPart(
                    tool_name='update_step',
                    args={'index': i - 1, 'status': 'done'},
                )]
            )
        texts = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, (ToolReturnPart, RetryPromptPart))
        ]
        return ModelResponse(parts=[TextPart(content='FINAL:' + ' | '.join(texts))])

    return scripted(fn)


def make_engine(home, ask=None, review_model=None):
    policy = ApprovalPolicy()
    policy.ask = ask
    return Engine(
        config=load_config(), db=Database.connect(home),
        extraction_model=review_model,
    ), policy


async def test_plan_propose_approve_and_steps(home, workdir):
    engine, policy = make_engine(home, ask=_approve(None))
    events = []
    outcome = await engine.run(
        prompt='add feature', workdir=workdir,
        approvals=policy, model=planner_flow(['approve'] * 4),
        emit=events.append,
    )
    types = [e['type'] for e in events]
    assert 'PLAN_PROPOSED' in types
    assert 'PLAN_APPROVED' in types
    plan = PlanStore(engine._db).latest(outcome.session_id)
    assert plan['status'] == 'done'
    assert all(s['status'] == 'done' for s in plan['steps'])


def _approve(cmd):
    async def ask(command):
        return 'approve'
    return ask


async def test_plan_rejection_returns_refusal(home, workdir):
    async def ask(command):
        return 'deny'

    engine, policy = make_engine(home, ask=ask)
    outcome = await engine.run(
        prompt='add feature', workdir=workdir, approvals=policy,
        model=planner_flow(['deny']),
    )
    assert outcome.status == 'complete'
    plan = PlanStore(engine._db).latest(outcome.session_id)
    assert plan['status'] == 'rejected'


async def test_headless_plan_aborts_with_plan_report(home, workdir):
    engine, policy = make_engine(home, ask=None)
    outcome = await engine.run(
        prompt='add feature', workdir=workdir, approvals=policy,
        model=planner_flow([]),
    )
    assert outcome.status == 'gate_aborted'
    assert 'plan' in outcome.gate.command


async def test_completing_all_steps_triggers_review(home, workdir):
    def reviewer(messages, info):
        return ModelResponse(
            parts=[TextPart(content='- missing docstring\n- no edge-case test')]
        )

    engine, policy = make_engine(home, ask=_approve(None))
    engine._extraction_model = scripted(reviewer)

    events = []
    outcome = await engine.run(
        prompt='add feature', workdir=workdir, approvals=policy,
        model=planner_flow(['approve'] * 4),
        emit=events.append,
    )
    findings_events = [e for e in events if e['type'] == 'REVIEW_FINDINGS']
    assert findings_events
    assert 'docstring' in findings_events[0]['findings']
    assert 'Address these findings' in outcome.output
