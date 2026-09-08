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
    assert 'say the thing' in texts
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
