"""Headless Run: exit codes distinguish success from failure."""


from helpers import say, scripted

import codingdude.cli as cli


def test_headless_success_exits_zero(engine, workdir, capsys):
    code = cli.run_headless(
        engine, workdir, 'greet me', model=scripted(say('done'))
    )
    out = capsys.readouterr().out
    assert code == 0
    assert 'done' in out


def test_headless_model_failure_exits_nonzero(engine, workdir):
    from pydantic_ai.exceptions import ModelAPIError

    def dead(messages, info):
        raise ModelAPIError(model_name='m', message='boom')

    code = cli.run_headless(engine, workdir, 'greet me', model=scripted(dead))
    assert code != 0
