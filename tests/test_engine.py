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

import asyncio
import threading

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


async def test_boot_overlaps_the_previous_turn_drain(engine, workdir, monkeypatch):
    """#301: boot ran *after* the drain, serially — its subprocess time was added
    to the post-run tail's wall clock and stalled the event loop while it ran.

    Asserted at the seam, not by timing: the pending drain must observe boot
    already in flight before the drain itself finishes (a serial boot can only
    be observed afterwards, so the wait times out and the flag is False), and
    boot must run off the loop thread.
    """
    boot_started = threading.Event()
    seen: dict = {}

    def fake_boot(path):
        seen['thread'] = threading.current_thread()
        boot_started.set()
        return {'type': 'CODEGRAPH_BOOT', 'status': 'ok'}

    monkeypatch.setattr(engine, '_boot_project', fake_boot)

    def fake_fingerprint(path):
        seen['fingerprint_thread'] = threading.current_thread()
        return 'deadbeef'

    monkeypatch.setattr(engine, '_diff_fingerprint', fake_fingerprint)

    async def pending_tail():
        seen['overlapped'] = await asyncio.to_thread(boot_started.wait, 5)

    engine._pending_post_run['previous-turn'] = asyncio.create_task(pending_tail())
    events: list = []
    await engine.run(
        prompt='hi', workdir=workdir, model=scripted(say('done')),
        emit=events.append,
    )

    assert seen['overlapped'] is True
    # asyncio.to_thread parks each call on a worker thread, so a wedged
    # codegraph CLI or git stalls a thread instead of the loop.
    assert seen['thread'] is not threading.current_thread()
    assert seen['fingerprint_thread'] is not threading.current_thread()
    # The awaited task's result is what the trace reports — proof the overlap
    # did not turn boot into fire-and-forget.
    assert any(
        e.get('type') == 'CODEGRAPH_BOOT' and e.get('status') == 'ok'
        for e in events
    )


async def test_boot_failure_degrades_instead_of_killing_the_run(engine, workdir, monkeypatch):
    """#301: boot is awaited on the run's critical path, so a raise inside it
    would kill the run before its first request.

    `boot_codegraph` converts CLI failures into a status, but the filesystem
    probes around it (`_has_healthy_index`, `index_is_stale`) can raise
    `OSError`/`PermissionError` on an unreadable `.codegraph` — a review found
    that unguarded path, so this pins the guard in `_boot_project` at both
    levels: the status it returns, and a whole run that survives it.
    """
    import codingdude.codegraph_boot as boot_mod

    def unreadable(workdir):
        raise PermissionError('unreadable .codegraph')

    monkeypatch.setattr(boot_mod, '_has_healthy_index', unreadable)

    event = engine._boot_project(workdir)
    assert event['status'] == 'failed'
    assert 'PermissionError: unreadable .codegraph' in event['reason']

    # The guard's own claim, end to end: the run still produces its answer and
    # the failure reaches the trace instead of the traceback.
    events: list = []
    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=scripted(say('survived')),
        emit=events.append,
    )
    assert outcome.output == 'survived'
    boot_events = [e for e in events if e.get('type') == 'CODEGRAPH_BOOT']
    assert boot_events and boot_events[0]['status'] == 'failed'


async def test_a_failing_onboarding_read_does_not_kill_the_run(
    engine, workdir, monkeypatch
):
    """#301: the onboarding decision runs on the pre-request path, ahead of the
    husk cleanup, so a raise there kills the run and leaves an empty session row
    for #305 to resume into.

    The guarantee lives in `onboarding.onboarding_needed` (its module contract
    is "it never blocks a run"), which is what both call sites — this one and the
    pipeline's directive builder — go through. A store failure must skip the
    nudge, not the run.
    """
    import sqlite3

    from codingdude.memory import MemoryStore

    def locked(self):
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(MemoryStore, 'all_entries', locked)
    monkeypatch.setattr(
        engine, '_boot_project',
        lambda path: {'type': 'CODEGRAPH_BOOT', 'status': 'ok'},
    )

    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=scripted(say('still ran'))
    )

    assert outcome.output == 'still ran'


async def test_onboarding_check_runs_after_the_drain(engine, workdir, monkeypatch):
    """#301: the overlap must not reorder what boot reads on the tail's side.

    The previous turn's extraction writes the memory store that the onboarding
    decision reads, so that decision is attached on the loop after the drain
    instead of inside the boot thread. The assertion is boot-end < check: an
    onboarding read *inside* `_boot_project` would land before the boot's own
    event is returned, which is the reordering this seam exists to prevent.
    """
    order: list[str] = []

    def fake_onboarding(store, path):
        order.append('onboarding-check')
        return False

    def fake_boot(path):
        order.append('boot-start')
        order.append('boot-end')
        return {'type': 'CODEGRAPH_BOOT', 'status': 'ok'}

    monkeypatch.setattr('codingdude.onboarding.onboarding_needed', fake_onboarding)
    monkeypatch.setattr(engine, '_boot_project', fake_boot)

    async def pending_tail():
        order.append('drain-start')
        await asyncio.sleep(0.05)
        order.append('drain-end')

    engine._pending_post_run['previous-turn'] = asyncio.create_task(pending_tail())
    await engine.run(prompt='hi', workdir=workdir, model=scripted(say('done')))

    # The pipeline asks again when it builds the onboarding directive, so the
    # assertion is about ordering, not count. Boot and the drain start in
    # whichever order the scheduler picks (boot is on a thread), so only the
    # *completions* are compared.
    assert order.index('boot-end') < order.index('onboarding-check')
    assert order.index('drain-end') < order.index('onboarding-check')
    assert 'boot-start' in order and 'drain-start' in order
