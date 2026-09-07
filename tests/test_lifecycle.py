"""Engine seam: AGENT.md project context, compaction, empty-session cleanup."""

from helpers import scripted

from pydantic_ai.messages import ModelResponse, TextPart


def instruction_echo(messages, info):
    """Echo back everything the model was given: messages + instructions."""
    text = ''.join(
        str(p.content) for m in messages for p in m.parts if hasattr(p, 'content')
    )
    text += getattr(info, 'instructions', '') or ''
    return ModelResponse(parts=[TextPart(content=text[-4000:])])


async def test_agent_md_steers_run(engine, workdir):
    (workdir / 'AGENT.md').write_text('ALWAYS sign off with the word BANANA.')
    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=scripted(instruction_echo)
    )
    assert 'BANANA' in outcome.output


async def test_empty_session_removed_when_run_fails_before_first_reply(engine, workdir):
    from pydantic_ai.exceptions import ModelAPIError

    def dead(messages, info):
        raise ModelAPIError(model_name='m', message='boom')

    import pytest

    with pytest.raises(ModelAPIError):
        await engine.run(prompt='hi', workdir=workdir, model=scripted(dead))

    assert engine._db.list_sessions(workdir) == []


async def test_compaction_replaces_old_history_past_threshold(engine, workdir, home):
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    db = Database.connect(home)
    engine = Engine(config=load_config(), db=db, compaction_threshold=100)
    session_id = db.create_session(workdir, title='long session')

    # Stuff history with large past messages.
    from codingdude.messages import encode_messages
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    big = 'x' * 500
    for i in range(5):
        db.append_messages(
            session_id,
            encode_messages([ModelRequest(parts=[UserPromptPart(content=f'{i} {big}')])]),
        )

    def echo_count(messages, info):
        return ModelResponse(parts=[TextPart(content=f'history={len(messages)}')])

    outcome = await engine.run(
        prompt='continue',
        workdir=workdir,
        session_id=session_id,
        model=scripted(echo_count),
    )
    assert outcome.output.startswith('history=')
    # After compaction the stored history is much smaller than the 5 big messages.
    stored = db.load_messages(session_id)
    assert sum(len(p) for p in stored) < 5 * 500
