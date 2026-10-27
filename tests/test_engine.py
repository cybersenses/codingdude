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
"""Engine seam: scripted FunctionModel runs persist messages and usage."""

from helpers import say, scripted
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.messages import decode_messages


async def test_scripted_run_persists_session(engine, db, workdir):
    outcome = await engine.run(
        prompt='say the thing', workdir=workdir, model=scripted(say('Hello from model'))
    )

    assert outcome.output == 'Hello from model'
    stored = decode_messages(db.load_messages(outcome.session_id))
    texts = [p.content for m in stored for p in m.parts if hasattr(p, 'content')]
    # Turn one stores the composed kickoff + prompt (R71 #263); the user's
    # words ride at the end of the first user part.
    user_texts = [
        p.content for m in stored for p in m.parts
        if getattr(p, 'part_kind', '') == 'user-prompt'
    ]
    assert user_texts[0].endswith('say the thing')
    assert 'Hello from model' in texts
    usage = db.session_usage(outcome.session_id)
    assert usage['requests'] >= 1


async def test_second_run_on_session_sees_history(engine, workdir):
    first = await engine.run(
        prompt='first', workdir=workdir, model=scripted(say('first-answer'))
    )

    def check(messages, info):
        texts = [
            p.content for m in messages for p in m.parts if hasattr(p, 'content')
        ]
        return ModelResponse(
            parts=[
                TextPart(
                    content='saw-history' if 'first-answer' in texts else 'no-history'
                )
            ]
        )

    second = await engine.run(
        prompt='second', workdir=workdir, session_id=first.session_id,
        model=scripted(check),
    )
    assert second.output == 'saw-history'
