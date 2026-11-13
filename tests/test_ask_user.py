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
"""Tests for the ask_user tool (interactive questions) and its engine wiring."""
import json

import pytest
from helpers import scripted
from pydantic_ai import ModelRetry
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
)

from codingdude.approvals import ApprovalPolicy
from codingdude.tools import build_ask_user_toolset


def _fn(toolset):
    return toolset.tools['ask_user'].function


# ---- tool unit tests --------------------------------------------------------

async def test_ask_user_returns_answers():
    async def asker(questions):
        return [{'question': q['question'], 'answer': 'sqlite'} for q in questions]

    policy = ApprovalPolicy()
    policy.ask_user = asker
    result = await _fn(build_ask_user_toolset(policy))(json.dumps([
        {'question': 'Which database?', 'options': ['postgres', 'sqlite'], 'multi': False},
    ]))
    assert 'sqlite' in result


async def test_ask_user_headless_raises_model_retry():
    policy = ApprovalPolicy()  # no ask_user set -> headless
    with pytest.raises(ModelRetry, match='interactive UI'):
        await _fn(build_ask_user_toolset(policy))('[{"question": "Why?"}]')


# ---- boundary validation (R90 #336) -----------------------------------------
# The payload is one opaque JSON string, so pydantic cannot check its shape.
# A malformed ask (options as {"multi": false} objects) reached the UI verbatim
# and killed the app with React #31; the trace-proven payloads live verbatim in
# frontend/src/askUser.test.ts.

async def test_ask_user_rejects_object_options():
    """Trace payload 2a: option labels missing, each option is {multi: false}."""
    policy = ApprovalPolicy()

    async def asker(questions):
        return []

    policy.ask_user = asker
    payload = json.dumps([
        {'question': 'What should I do with the steampunk + dino theme?',
         'options': [{'multi': False}, {'multi': False}, {'multi': False}]},
    ])
    with pytest.raises(ModelRetry, match='plain string labels'):
        await _fn(build_ask_user_toolset(policy))(payload)


async def test_ask_user_rejects_empty_question_text():
    policy = ApprovalPolicy()

    async def asker(questions):
        return []

    policy.ask_user = asker
    with pytest.raises(ModelRetry, match=r'questions\[0\]\.question'):
        await _fn(build_ask_user_toolset(policy))(json.dumps([{'options': ['a']}]))

    with pytest.raises(ModelRetry, match=r'questions\[0\] must be an object'):
        await _fn(build_ask_user_toolset(policy))(json.dumps(['just a string']))


async def test_ask_user_rejects_non_array_payload():
    policy = ApprovalPolicy()

    async def asker(questions):
        return []

    policy.ask_user = asker
    with pytest.raises(ModelRetry, match='JSON array'):
        await _fn(build_ask_user_toolset(policy))(json.dumps({'question': 'Q?'}))


async def test_ask_user_rejects_non_bool_multi():
    policy = ApprovalPolicy()

    async def asker(questions):
        return []

    policy.ask_user = asker
    with pytest.raises(ModelRetry, match=r'questions\[0\]\.multi'):
        await _fn(build_ask_user_toolset(policy))(
            json.dumps([{'question': 'Q?', 'multi': 'yes'}]))


async def test_ask_user_normalizes_defaults_before_asking():
    """The asker and the QA recorder see normalized questions, not raw model JSON."""
    captured = {}

    async def asker(questions):
        captured['questions'] = questions
        return [{'question': 'Q?', 'answer': 'yes'}]

    policy = ApprovalPolicy()
    policy.ask_user = asker
    await _fn(build_ask_user_toolset(policy))(json.dumps([{'question': 'Q?'}]))
    assert captured['questions'] == [{'question': 'Q?', 'options': [], 'multi': False}]


# ---- engine integration ------------------------------------------------------

async def test_ask_user_engine_integration(home, workdir):
    """The model calls ask_user; the user answers; the model sees the answers."""
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    def model_fn(messages, info):
        if not any(
            getattr(p, 'part_kind', '') == 'tool-call'
            for m in messages for p in m.parts
        ):
            return ModelResponse(parts=[ToolCallPart(
                tool_name='ask_user',
                args={'questions': json.dumps([
                    {'question': 'Deploy now?', 'options': ['yes', 'no'], 'multi': False},
                ])},
            )])
        returns = [
            str(p.content)
            for m in messages for p in m.parts
            if getattr(p, 'part_kind', '') == 'tool-return'
        ]
        return ModelResponse(parts=[TextPart(content='|'.join(returns))])

    engine = Engine(config=load_config(), db=Database.connect(home))
    policy = ApprovalPolicy()

    async def asker(questions):
        return [{'question': q.get('question', ''), 'answer': 'yes'} for q in questions]

    policy.ask_user = asker
    outcome = await engine.run(
        prompt='deploy?', workdir=workdir,
        model=scripted(model_fn), approvals=policy,
    )
    assert 'yes' in outcome.output


async def test_ask_user_records_qa_artifact(home, workdir):
    """ask_user auto-captures the Q&A into the session's artifact history."""
    from codingdude.tools import build_ask_user_toolset

    captured = []

    def recorder(questions, answers):
        captured.append((questions, answers))

    policy = ApprovalPolicy()

    async def asker(questions):
        return [{'question': q['question'], 'answer': 'yes'} for q in questions]

    policy.ask_user = asker
    toolset = build_ask_user_toolset(policy, recorder=recorder)
    await _fn(toolset)(json.dumps([
        {'question': 'Deploy now?', 'options': ['yes', 'no'], 'multi': False},
    ]))
    assert captured and captured[0][1][0]['answer'] == 'yes'
