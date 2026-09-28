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
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from codingdude.messages import encode_messages

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
    assert sum(len(p) for p in stored) < 5 * 1000


async def test_compaction_triggers_on_token_limit_from_config(home, workdir):
    """R3: with compaction_threshold disabled, the ContextManager's token
    estimate against the configured context_limit triggers compaction."""
    import dataclasses

    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    config = load_config()
    config = dataclasses.replace(
        config, models=dataclasses.replace(config.models, context_limit=1000)
    )
    db = Database.connect(home)
    engine = Engine(config=config, db=db, compaction_threshold=None)
    session_id = db.create_session(workdir, title='token session')

    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from codingdude.messages import encode_messages

    # 5 x 1000 chars = 1250 estimated tokens >= 80% of the 1000-token window.
    for i in range(5):
        db.append_messages(
            session_id,
            encode_messages([ModelRequest(parts=[UserPromptPart(content=f'{i} {"x" * 1000}')])]),
        )

    def echo_count(messages, info):
        return ModelResponse(parts=[TextPart(content=f'history={len(messages)}')])

    await engine.run(
        prompt='continue', workdir=workdir, session_id=session_id,
        model=scripted(echo_count),
    )
    # Without token-based compaction the 5 big messages survive in storage;
    # a compaction summarizes them, retaining only the most recent verbatim
    # (plan_compaction keep-recent). Assert that property directly rather
    # than a raw char-count proxy — persisted rows embed the run's
    # instructions (pydantic-ai), so unrelated instruction text shifts the
    # byte total and crossed the old 5000-char threshold spuriously.
    stored = db.load_messages(session_id)
    joined = '\n'.join(stored)
    assert joined.count('x' * 600) == 1, 'expected only the recent message kept verbatim'
    assert 'Earlier conversation, compacted' in joined
