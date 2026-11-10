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
"""Post-run claims pipeline: bounded retry round, real logging, parallel tail.

Covers #23 (unbounded claims-retry agent round was the 8000s stall tail)
and #24 (extraction + claims audit run concurrently).
"""

import asyncio

from helpers import scripted
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

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
    await engine.drain_post_run()
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
    await engine.drain_post_run()
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
    await engine.drain_post_run()
    types = [e['type'] for e in events]
    for expected in ('MEMORY_EXTRACTING', 'MEMORY_EXTRACTED',
                     'CLAIMS_CHECKING', 'CLAIMS_RETRY', 'CLAIMS_ADDRESSED'):
        assert expected in types


async def test_run_returns_before_extraction_finishes(tmp_path, db, home):
    """The post-run tail must not hold the run hostage: engine.run returns
    while a slow extraction is still in flight, and the extraction still
    lands (events emitted) afterwards."""
    proj = tmp_path / 'proj'
    proj.mkdir()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_extract(messages, info):
        started.set()
        await release.wait()
        return ModelResponse(parts=[TextPart(content='nothing worth remembering')])

    engine = Engine(config=load_config(), db=db, extraction_model=FunctionModel(slow_extract))
    events: list[dict] = []
    outcome = await engine.run(
        prompt='do the thing',
        workdir=proj,
        model=run_model('ok'),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    for _ in range(500):  # let the scheduled background tail take its first slice
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()  # extraction began...
    # ...but the run did NOT wait for it.
    assert 'MEMORY_EXTRACTED' not in [e['type'] for e in events]
    release.set()
    await engine.drain_post_run()
    assert 'MEMORY_EXTRACTED' in [e['type'] for e in events]


async def test_drain_cut_retry_still_reports_unverified(tmp_path, db, home):
    """#308: the worker drain bound can cut the claims-retry mid-flight
    (live: run mY5V_HxeMdk, 2026-11-09 — the retry re-ran gates for ~96s,
    then the drain expired and the worker exited with NO claims verdict at
    all, because CancelledError bypassed the 'report unverified either way'
    fall-through). A cut retry must still emit CLAIMS_UNVERIFIED, and the
    drain must cancel the tail (not abandon it pending)."""
    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))

    retry_running = asyncio.Event()
    release_retry = asyncio.Event()

    async def run_then_block(messages, info):
        """Call 1: the run itself. Later calls: the retry round — block
        until the test has fired the drain bound (the live race shape)."""
        if retry_running.is_set():
            await release_retry.wait()
            return ModelResponse(parts=[TextPart(content='corrected')])
        retry_running.set()
        return ModelResponse(parts=[TextPart(content='Done. Tests pass.')])

    async def stream_run_then_block(messages, info):
        response = await run_then_block(messages, info)
        yield response.parts[0].content

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_with_diff(tmp_path),
        model=FunctionModel(run_then_block, stream_function=stream_run_then_block),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    for _ in range(500):
        if retry_running.is_set():
            break
        await asyncio.sleep(0.01)
    assert retry_running.is_set()  # the retry round is in flight...
    try:
        # ...and the drain bound fires while it runs (worker drain expiry).
        await engine.drain_post_run(timeout=0.1)
        types = [e['type'] for e in events]
        assert 'CLAIMS_ADDRESSED' not in types  # the retry never completed
        unverified = [e for e in events if e['type'] == 'CLAIMS_UNVERIFIED']
        assert unverified, 'a cut retry must still report its claims unverified'
        assert unverified[0].get('reason') == 'cancelled'
        assert any(_UNSUPPORTED in c for c in unverified[0]['claims'])
        # The tail must END on the drain bound — not linger pending until
        # the process exit kills it mid-flight.
        assert not engine._pending_post_run or all(
            t.done() for t in engine._pending_post_run.values()
        )
    finally:
        release_retry.set()
        await engine.drain_post_run()


async def test_post_run_events_carry_phase_markers(tmp_path, db, home):
    """#309: post-RUN_FINISHED activity must be attributable in the trace.
    The tail stamps phase='post-run' on every event it emits and brackets
    itself with POST_RUN_BEGIN / POST_RUN_END — so the retry agent's raw
    tool events between the markers can never read as live run activity."""
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
    await engine.drain_post_run()
    types = [e['type'] for e in events]
    for expected in ('POST_RUN_BEGIN', 'POST_RUN_END'):
        assert expected in types
    begin, end = types.index('POST_RUN_BEGIN'), types.index('POST_RUN_END')
    for marker in ('MEMORY_EXTRACTING', 'CLAIMS_CHECKING', 'CLAIMS_RETRY'):
        assert begin < types.index(marker) < end, (
            f'{marker} must sit inside the POST_RUN bracket'
        )
    stamped = {e['type'] for e in events if e.get('phase') == 'post-run'}
    assert {'POST_RUN_BEGIN', 'POST_RUN_END', 'MEMORY_EXTRACTED',
            'CLAIMS_UNVERIFIED'} <= stamped


async def test_next_run_waits_for_pending_extraction(tmp_path, db, home):
    """A follow-up turn must not start before the previous turn's memory
    extraction has landed (the extraction result feeds memory recall)."""
    proj = tmp_path / 'proj'
    proj.mkdir()
    order: list[str] = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_extract(messages, info):
        started.set()
        await release.wait()
        order.append('extracted')
        return ModelResponse(parts=[TextPart(content='nothing worth remembering')])

    def turn_model(messages, info):
        order.append('turn')
        return ModelResponse(parts=[TextPart(content='ok')])

    engine = Engine(config=load_config(), db=db, extraction_model=FunctionModel(slow_extract))
    first = await engine.run(prompt='one', workdir=proj, model=scripted(turn_model))
    assert first.status == 'complete'
    for _ in range(500):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()

    order.clear()  # only the relative order of run 2 matters
    release.set()
    second = await engine.run(prompt='two', workdir=proj, model=scripted(turn_model))
    assert second.status == 'complete'
    assert order == ['extracted', 'turn']
    await engine.drain_post_run()
