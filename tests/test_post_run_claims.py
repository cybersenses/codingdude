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

Covers #23 (unbounded claims-retry agent round was the 8000s stall tail),
#24 (extraction + claims audit run concurrently), #308/#309 (verdict at the
drain bound + post-run phase markers), and #310 (run-scoped audit gating).
"""

import asyncio

from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import FunctionModel

from codingdude.config import load_config
from codingdude.engine import Engine

_UNSUPPORTED = 'the reviewer could not verify that the tests pass'


def _git_repo(tmp_path) -> object:
    """A git repo with one tracked file."""
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
    return w


def git_workdir_with_diff(tmp_path) -> object:
    """A git repo whose working tree differs from HEAD before the run starts
    (standing dirty file — the diff-gate #310 replaces)."""
    w = _git_repo(tmp_path)
    (w / 'a.txt').write_text('one\ntwo\n')
    return w


def git_workdir_clean(tmp_path) -> object:
    """A git repo with a clean tree: only the run's own changes can arm
    the audit gate."""
    return _git_repo(tmp_path)


def run_model(text: str):
    def fn(messages: list[ModelMessage], info):
        return ModelResponse(parts=[TextPart(content=text)])
    return scripted(fn)


def tool_run_model(tool_name: str, tool_args: dict, final_text: str = 'Done. Tests pass.'):
    """Call 1 issues the tool call; later calls answer with final_text."""
    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=tool_args)])
        return ModelResponse(parts=[TextPart(content=final_text)])
    return scripted(fn)


def flaky_run_model(tool_name: str, tool_args: dict, final_text: str,
                    raise_on_post_tool_call: int):
    """Tool-call turn, then a normal answer, then explode on a later call
    (simulating the claims-retry round crashing)."""
    post = {'n': 0}
    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=tool_args)])
        post['n'] += 1
        if post['n'] >= raise_on_post_tool_call:
            raise RuntimeError('provider exploded')
        return ModelResponse(parts=[TextPart(content=final_text)])
    return scripted(fn)


async def test_claims_retry_is_evented_and_addressed(tmp_path, db, home):
    """The one retry round emits CLAIMS_RETRY before it runs (#23)."""
    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_clean(tmp_path),
        model=tool_run_model('write_file', {'path': 'made.txt', 'content': 'x\n'}),
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
            workdir=git_workdir_clean(tmp_path),
            model=flaky_run_model(
                'write_file', {'path': 'made.txt', 'content': 'x\n'},
                'Done.', raise_on_post_tool_call=2),
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


async def test_audit_failure_still_reports_unverified(tmp_path, db, home, caplog):
    """A crash inside the audit half (before any retry) must not be silent
    either: CLAIMS_CHECKING fired, so a terminal verdict must close it.
    Review finding on b3817ad: the audit half swallowed every failure with
    a bare return — CLAIMS_CHECKING left with no closing event, no log."""
    import logging

    def exploding_extractor(messages, info):
        raise RuntimeError('audit exploded')

    extractor = scripted(exploding_extractor)

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    with caplog.at_level(logging.WARNING, logger='codingdude.run_pipeline'):
        outcome = await engine.run(
            prompt='do the thing',
            workdir=git_workdir_clean(tmp_path),
            model=tool_run_model('write_file', {'path': 'made.txt', 'content': 'x\n'}),
            emit=events.append,
        )
    assert outcome.status == 'complete'
    await engine.drain_post_run()
    types = [e['type'] for e in events]
    assert 'CLAIMS_CHECKING' in types
    assert 'CLAIMS_RETRY' not in types  # the audit died before any retry
    unverified = [e for e in events if e['type'] == 'CLAIMS_UNVERIFIED']
    assert unverified and unverified[0].get('reason') == 'audit_failed'
    assert caplog.records  # the failure is logged with context, not swallowed


async def test_extraction_and_claims_run_concurrently(tmp_path, db, home):
    """Both post-run passes complete when run together (#24); each still
    emits its phase events."""
    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED + '\na durable fact')]))

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_clean(tmp_path),
        model=tool_run_model('write_file', {'path': 'made.txt', 'content': 'x\n'}),
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
        """Call 1 edits a file (arms the gate). Later calls: the retry
        round — block until the test has fired the drain bound (the live
        race shape)."""
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(
                tool_name='write_file',
                args={'path': 'made.txt', 'content': 'x\n'})])
        if retry_running.is_set():
            await release_retry.wait()
            return ModelResponse(parts=[TextPart(content='corrected')])
        retry_running.set()
        return ModelResponse(parts=[TextPart(content='Done. Tests pass.')])

    async def stream_run_then_block(messages, info):
        response = await run_then_block(messages, info)
        for i, part in enumerate(response.parts):
            if hasattr(part, 'tool_name'):
                from pydantic_ai.models.function import DeltaToolCall

                args = part.args
                if not isinstance(args, str):
                    import json

                    args = json.dumps(args)
                yield {i: DeltaToolCall(name=part.tool_name, json_args=args)}
            elif hasattr(part, 'content') and isinstance(part.content, str):
                yield part.content

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_clean(tmp_path),
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
        workdir=git_workdir_clean(tmp_path),
        model=tool_run_model('write_file', {'path': 'made.txt', 'content': 'x\n'}),
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


async def test_dirty_workdir_without_run_changes_skips_audit(tmp_path, db, home):
    """#310: the audit gate is run-scoped, not workdir-scoped. A standing
    dirty file (this repo's own ROADMAP.md-by-convention) must not fire the
    claims audit on every turn: a turn that changed nothing gets
    CLAIMS_SKIPPED and no audit; memory extraction still runs."""
    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='what does this repo do',
        workdir=git_workdir_with_diff(tmp_path),
        model=run_model('It is a coding agent.'),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    await engine.drain_post_run()
    types = [e['type'] for e in events]
    assert 'CLAIMS_CHECKING' not in types
    skipped = [e for e in events if e['type'] == 'CLAIMS_SKIPPED']
    assert skipped and skipped[0].get('reason') == 'no_run_changes'
    assert 'MEMORY_EXTRACTED' in types


async def test_run_edit_arms_audit_in_clean_workdir(tmp_path, db, home):
    """#310: a run that edits a file gets audited even from a clean tree —
    which also covers commitless/scratch workdirs, where `git diff HEAD`
    has nothing to compare against at all."""
    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_clean(tmp_path),
        model=tool_run_model('write_file', {'path': 'made.txt', 'content': 'x\n'}),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    await engine.drain_post_run()
    assert 'CLAIMS_CHECKING' in [e['type'] for e in events]


async def test_commitless_workdir_edit_arms_audit(tmp_path, db, home):
    """#310: a commitless workdir (no git repo at all) must arm the audit
    via edit events — `git diff HEAD` has nothing to compare against there,
    so without the edit signal the gate could never fire. (Review finding
    on b3817ad: the test claiming this coverage used a repo WITH a
    commit.)"""
    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))

    scratch = tmp_path / 'scratch'
    scratch.mkdir()

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=scratch,
        model=tool_run_model('write_file', {'path': 'made.txt', 'content': 'x\n'}),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    await engine.drain_post_run()
    types = [e['type'] for e in events]
    assert 'CLAIMS_CHECKING' in types
    assert 'CLAIMS_SKIPPED' not in types


async def test_run_shell_change_arms_audit(tmp_path, db, home):
    """#310: shell-mediated tracked-file changes arm the gate too — the
    diff fingerprint moved during the run even though no edit-tool event
    fired."""
    from codingdude.approvals import ApprovalPolicy

    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_clean(tmp_path),
        model=tool_run_model('shell', {'command': 'echo three >> a.txt'}),
        approvals=ApprovalPolicy(yolo=True),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    await engine.drain_post_run()
    assert 'CLAIMS_CHECKING' in [e['type'] for e in events]


async def test_verifier_toolset_is_narrowed(tmp_path, db, home):
    """#311: the claims-retry verifier runs post-terminal with a narrowed
    toolset — read-only file tools plus the shell (it must be able to
    re-run claimed verifications like `uv run pytest`). It never carries
    the run's full surface: no edit tools, no delegation, no ask cards,
    no sandbox exec."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.run_pipeline import build_verifier_toolsets

    toolsets = build_verifier_toolsets(
        tmp_path, ApprovalPolicy(yolo=True), shell_bin='powershell')
    names: set[str] = set()
    for ts in toolsets:
        names |= set(ts.tools)
    assert {'list_dir', 'read_file', 'grep', 'glob', 'shell'} <= names
    for forbidden in ('edit_file', 'write_file', 'edit_symbol', 'delegate',
                      'ask_user', 'exec_in_sandbox', 'run_coverage'):
        assert forbidden not in names


async def test_fix_loop_edit_arms_audit(tmp_path, db, home):
    """#310 (evaluator finding): the gate is evaluated AFTER the fix loop —
    a run whose only change is a fix-loop retry edit still gets audited,
    not silently skipped. RED evidence: before the ordering fix this test
    failed with CLAIMS_SKIPPED/no_run_changes (7 failed suite run)."""
    from codingdude.approvals import ApprovalPolicy

    extractor = scripted(lambda m, i: ModelResponse(
        parts=[TextPart(content=_UNSUPPORTED)]))
    turn = {'n': 0}

    def fix_loop_model(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            turn['n'] += 1
            if turn['n'] == 1:
                # Main turn: answers without touching anything.
                return ModelResponse(parts=[TextPart(content='Done.')])
            # Fix-loop retry round: the edit happens here.
            return ModelResponse(parts=[ToolCallPart(
                tool_name='write_file',
                args={'path': 'made.txt', 'content': 'x\n'})])
        return ModelResponse(parts=[TextPart(content='Fixed.')])

    events: list[dict] = []
    engine = Engine(config=load_config(), db=db, extraction_model=extractor)
    outcome = await engine.run(
        prompt='do the thing',
        workdir=git_workdir_clean(tmp_path),
        model=scripted(fix_loop_model),
        fix_loop=True,
        test_command='exit 1',  # the suite "fails" once, forcing a retry round
        approvals=ApprovalPolicy(yolo=True),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    await engine.drain_post_run()
    types = [e['type'] for e in events]
    assert 'CLAIMS_SKIPPED' not in types
    assert 'CLAIMS_CHECKING' in types


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
