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

    async def pending_tail():
        seen['overlapped'] = await asyncio.to_thread(boot_started.wait, 5)

    engine._pending_post_run['previous-turn'] = asyncio.create_task(pending_tail())
    events: list = []
    await engine.run(
        prompt='hi', workdir=workdir, model=scripted(say('done')),
        emit=events.append,
    )

    assert seen['overlapped'] is True
    # asyncio.to_thread parks the call on a worker thread, so a wedged
    # codegraph CLI stalls that worker instead of the loop.
    assert seen['thread'] is not threading.current_thread()
    # The awaited task's result is what the trace reports — proof the overlap
    # did not turn boot into fire-and-forget.
    assert any(
        e.get('type') == 'CODEGRAPH_BOOT' and e.get('status') == 'ok'
        for e in events
    )


async def test_onboarding_check_runs_after_the_drain(engine, workdir, monkeypatch):
    """#301: the overlap must not reorder what boot reads on the tail's side.

    The previous turn's extraction writes the memory store that the onboarding
    decision reads, so that decision is attached on the loop after the drain
    instead of inside the boot thread. This pins the order, which is the whole
    reason the check left `_boot_project`.
    """
    order: list[str] = []

    def fake_onboarding(store, path):
        order.append('onboarding-check')
        return False

    monkeypatch.setattr('codingdude.onboarding.onboarding_needed', fake_onboarding)
    monkeypatch.setattr(
        engine, '_boot_project',
        lambda path: {'type': 'CODEGRAPH_BOOT', 'status': 'ok'},
    )

    async def pending_tail():
        order.append('drain-start')
        await asyncio.sleep(0.05)
        order.append('drain-end')

    engine._pending_post_run['previous-turn'] = asyncio.create_task(pending_tail())
    await engine.run(prompt='hi', workdir=workdir, model=scripted(say('done')))

    # The pipeline asks again when it builds the onboarding directive, so the
    # assertion is about ordering, not count: no check may run before the drain
    # closes, because a check inside the boot thread is exactly the reordering
    # this seam exists to prevent.
    assert order[:2] == ['drain-start', 'drain-end']
    assert 'onboarding-check' in order[2:]
