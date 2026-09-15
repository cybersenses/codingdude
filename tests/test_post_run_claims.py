"""Post-run claims pipeline: bounded retry round, real logging, parallel tail.

Covers #23 (unbounded claims-retry agent round was the 8000s stall tail)
and #24 (extraction + claims audit run concurrently).
"""

from helpers import scripted
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart

from codingdude.config import load_config
from codingdude.engine import Engine

_UNSUPPORTED = 'the reviewer could not verify that the tests pass'


def git_workdir_with_diff(tmp_path) -> object:
    """A git repo whose working tree differs from HEAD (claims path active)."""
    import subprocess

    w = tmp_path / 'gitproj'
    w.mkdir()
    def git(*args):
        subprocess.run(['git', *args], cwd=w, check=True, capture_output=True)
    git('init')
    git('config', 'user.email', 't@t')
    git('config', 'user.name', 't')
    (w / 'a.txt').write_text('one\n')
    git('add', '.')
    git('commit', '-m', 'init')
    (w / 'a.txt').write_text('one\ntwo\n')
    return w


def run_model(text: str):
    def fn(messages: list[ModelMessage], info):
        return ModelResponse(parts=[TextPart(content=text)])
    return scripted(fn)


def flaky_run_model(text: str, raise_on_call: int):
    """Run model that answers normally, then explodes on a later call
    (simulating the claims-retry round crashing)."""
    calls = {'n': 0}
    def fn(messages: list[ModelMessage], info):
        calls['n'] += 1
        if calls['n'] >= raise_on_call:
            raise RuntimeError('provider exploded')
        return ModelResponse(parts=[TextPart(content=text)])
    return scripted(fn)


async def test_claims_retry_is_evented_and_addressed(tmp_path, db, home):
    """The one retry round emits CLAIMS_RETRY before it runs (#23)."""
    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_with_diff(tmp_path),
        model=run_model('Done. Tests pass.'),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    types = [e['type'] for e in events]
    assert 'CLAIMS_CHECKING' in types
    assert 'CLAIMS_RETRY' in types
    assert types.index('CLAIMS_RETRY') > types.index('CLAIMS_CHECKING')
    assert 'CLAIMS_ADDRESSED' in types


async def test_claims_retry_failure_is_logged_not_silent(tmp_path, db, home, caplog):
    """A crash inside the retry round must not be swallowed: it logs with
    context and the run still finishes with CLAIMS_UNVERIFIED (#23)."""
    import logging

    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    with caplog.at_level(logging.WARNING, logger='codingdude.run_pipeline'):
        outcome = await engine.run(
            prompt='do the thing',
            workdir=git_workdir_with_diff(tmp_path),
            model=flaky_run_model('Done.', raise_on_call=2),
            emit=events.append,
        )
    assert outcome.status == 'complete'
    types = [e['type'] for e in events]
    assert 'CLAIMS_RETRY' in types
    assert 'CLAIMS_ADDRESSED' not in types
    assert 'CLAIMS_UNVERIFIED' in types
    assert any('claims-retry' in r.message.lower() or 'claims' in r.message.lower()
               for r in caplog.records)


async def test_extraction_and_claims_run_concurrently(tmp_path, db, home):
    """Both post-run passes complete when run together (#24); each still
    emits its phase events."""
    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED + '\na durable fact')]))

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_with_diff(tmp_path),
        model=run_model('Done. Tests pass.'),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    types = [e['type'] for e in events]
    for expected in ('MEMORY_EXTRACTING', 'MEMORY_EXTRACTED',
                     'CLAIMS_CHECKING', 'CLAIMS_RETRY', 'CLAIMS_ADDRESSED'):
        assert expected in types
