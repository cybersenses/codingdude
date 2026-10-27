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
"""Worker: CLI → engine.run argument wiring.

Seam: `worker.engine_run_kwargs` is the single place the worker maps its parsed
arguments onto `Engine.run`. Testing it here catches the class of bug where a
flag is parsed but never forwarded (self-review H2: `--fix-loop`).
"""

import argparse
from pathlib import Path


def _args(**over) -> argparse.Namespace:
    base = dict(
        prompt='do a thing',
        workdir=str(Path.cwd()),
        session='sess1',
        fix_loop=False,
        image=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_engine_run_kwargs_forwards_fix_loop():
    from codingdude import worker

    kwargs = worker.engine_run_kwargs(_args(fix_loop=True), model='m')
    assert kwargs['fix_loop'] is True
    assert kwargs['prompt'] == 'do a thing'
    assert kwargs['session_id'] == 'sess1'
    assert kwargs['model'] == 'm'
    assert kwargs['image_path'] is None


async def test_worker_slots_route_through_fallback_base_url(monkeypatch):
    """R72 #265: the worker's config-driven slots (extraction, vision) must
    resolve through _model_from_name WITH config.models.fallback_base_url —
    the same seam engine._build_subagent_model uses. Live symptom of the
    omission: memory extraction 400'd on every run end because a
    coding-plan-only key hit the standard Z.ai endpoint."""
    from types import SimpleNamespace

    import codingdude.engine as engine_mod
    from codingdude import worker

    calls = []
    sentinel = object()

    def fake_from_name(name, base_url, providers):
        calls.append((name, base_url))
        return sentinel

    monkeypatch.setattr(engine_mod, '_model_from_name', fake_from_name)
    config = SimpleNamespace(
        models=SimpleNamespace(
            subagent='zai:cheap',
            vision='zai:vision',
            fallback_base_url='https://api.z.ai/api/coding/paas/v4',
        ),
        providers={},
    )
    extraction, vision = await worker._resolve_worker_slots(config)
    assert extraction is sentinel and vision is sentinel
    assert calls == [
        ('zai:cheap', 'https://api.z.ai/api/coding/paas/v4'),
        ('zai:vision', 'https://api.z.ai/api/coding/paas/v4'),
    ]


async def test_worker_slots_tolerate_unresolvable_extraction(monkeypatch):
    """Extraction stays best-effort: an unresolvable slot disables it (None)
    instead of failing the run — same contract as before the helper."""
    from types import SimpleNamespace

    import codingdude.engine as engine_mod
    from codingdude import worker

    def boom(name, base_url, providers):
        raise RuntimeError('no credentials')

    monkeypatch.setattr(engine_mod, '_model_from_name', boom)
    config = SimpleNamespace(
        models=SimpleNamespace(
            subagent='zai:cheap', vision=None, fallback_base_url='https://x/v4',
        ),
        providers={},
    )
    extraction, vision = await worker._resolve_worker_slots(config)
    assert extraction is None
    assert vision is None


def test_engine_run_kwargs_defaults_fix_loop_off_and_resolves_workdir(tmp_path):
    from codingdude import worker

    kwargs = worker.engine_run_kwargs(_args(workdir=str(tmp_path)), model=None)
    assert kwargs['fix_loop'] is False
    assert kwargs['workdir'] == tmp_path.resolve()


def test_engine_run_kwargs_resolves_image_path(tmp_path):
    from codingdude import worker

    img = tmp_path / 'shot.png'
    img.write_bytes(b'x')
    kwargs = worker.engine_run_kwargs(_args(image=str(img)), model=None)
    assert kwargs['image_path'] == img.resolve()


def test_prompt_file_loaded_and_deleted(tmp_path):
    """A long prompt can't ride on argv (Windows 32k limit, WinError 206):
    --prompt-file supplies it, and the file is removed after read."""
    from codingdude import worker

    pf = tmp_path / 'abc.prompt'
    pf.write_text('a very long prompt', encoding='utf-8')
    args = worker.load_prompt_file(_args(prompt=None, prompt_file=str(pf)))
    assert args.prompt == 'a very long prompt'
    assert not pf.exists()


def test_prompt_file_absent_leaves_prompt_alone():
    from codingdude import worker

    args = worker.load_prompt_file(_args(prompt='inline'))
    assert args.prompt == 'inline'


# --- _finish_run: terminal event FIRST (R30); the tail drains after the
# --- sender exits, in run(), so the UI never waits on extraction.

def test_finish_run_emits_terminal_without_draining(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    from codingdude import worker

    monkeypatch.setattr(worker, 'trace_terminal', lambda *a: None)
    events = []

    class FakeEngine:  # no drain_post_run at all: calling it would raise
        pass

    asyncio.run(worker._finish_run(
        FakeEngine(), _args(), events.append,
        outcome=SimpleNamespace(status='ok', output='done')))
    assert events[-1]['type'] == 'RUN_FINISHED'


def test_finish_run_emits_error_terminal_without_draining(monkeypatch):
    import asyncio

    from codingdude import worker

    monkeypatch.setattr(worker, 'trace_terminal', lambda *a: None)
    events = []

    class FakeEngine:
        pass

    asyncio.run(worker._finish_run(
        FakeEngine(), _args(), events.append, exc=RuntimeError('boom')))
    assert events[-1]['type'] == 'RUN_ERROR'
    assert 'boom' in events[-1]['message']


def test_drain_after_terminal_uses_bounded_timeout():
    """run() drains the pending tail after the sender exits (post-terminal),
    bounded by _DRAIN_BEFORE_TERMINAL_S, before the process tears down."""
    import asyncio

    from codingdude import worker

    calls = []

    class FakeEngine:
        async def drain_post_run(self, timeout=None):
            calls.append(timeout)

    asyncio.run(worker.drain_after_terminal(FakeEngine()))
    assert calls == [worker._DRAIN_BEFORE_TERMINAL_S]


def test_arm_exit_watchdog_forces_exit_after_grace(monkeypatch):
    """#62: after the drain the worker arms a watchdog that hard-exits the
    process if interpreter teardown wedges (Windows Proactor close). The
    watchdog must fire os._exit, not raise, and use a daemon timer so it
    can never itself block shutdown."""
    from codingdude import worker

    fired = []
    created = []

    class FakeTimer:
        def __init__(self, interval, fn, daemon=None, args=None):
            created.append((interval, daemon))
            self.fn = fn
            self.args = args or ()

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(worker.threading, 'Timer', FakeTimer)
    monkeypatch.setattr(worker.os, '_exit', lambda code: fired.append(code))
    worker.arm_exit_watchdog()
    assert created and created[0][0] == worker._EXIT_WATCHDOG_S
    assert worker._exit_watchdog.daemon is True
    worker._exit_watchdog.fn(*worker._exit_watchdog.args)  # wedged-teardown path
    assert fired == [0]


def test_arm_exit_watchdog_cancels_previous():
    """Re-arming replaces the previous timer (idempotent across calls)."""
    from codingdude import worker

    worker.arm_exit_watchdog()
    t1 = worker._exit_watchdog
    worker.arm_exit_watchdog()
    assert worker._exit_watchdog is not t1
    assert t1 is not None
    worker._exit_watchdog.cancel()
    worker._exit_watchdog = None


def test_sender_loop_survives_connection_closed():
    """#73: a ws drop mid-run must not kill the worker. The sender drops the
    event, keeps draining the queue, and returns on the terminal event."""
    import asyncio

    from websockets.exceptions import ConnectionClosedError

    from codingdude import worker

    sent: list[str] = []

    class DyingWS:
        def __init__(self):
            self.calls = 0

        async def send(self, msg):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionClosedError(None, None, None)
            sent.append(msg)

    async def main():
        ws = DyingWS()
        q: asyncio.Queue = asyncio.Queue()
        q.put_nowait({'type': 'TEXT_MESSAGE_START'})
        q.put_nowait({'type': 'TEXT_MESSAGE_END'})
        q.put_nowait({'type': 'RUN_FINISHED'})
        await worker._sender_loop(ws, q)

    asyncio.run(main())  # must not raise
    assert sent == []  # socket was dead; events dropped, not crashed on


def test_reader_loop_returns_on_connection_closed():
    """#73: the reader must not leak 'Task exception was never retrieved'."""
    import asyncio

    from websockets.exceptions import ConnectionClosedError

    from codingdude import worker

    class DyingWS:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ConnectionClosedError(None, None, None)

    async def main():
        await worker._reader_loop(DyingWS(), {}, {})

    asyncio.run(main())  # must not raise


def test_engine_run_kwargs_forwards_run_id():
    from codingdude import worker

    assert worker.engine_run_kwargs(_args(run_id='abc123'), model='m')['run_id'] == 'abc123'


def test_engine_run_kwargs_run_id_default_none():
    from codingdude import worker

    assert worker.engine_run_kwargs(_args(), model=None).get('run_id') is None


# --- #147: pending ask/gate interactions are persisted to the trace so a
# --- page refresh can restore the card while the run is still alive.

def test_ask_user_interaction_traces_request_and_resolution():
    import asyncio

    from codingdude import worker

    traced = []
    fut = None
    async def main():
        nonlocal fut
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        emitted = []
        task = asyncio.create_task(worker.ask_user_interaction(
            emitted.append, traced.append, 'run1', [{'question': 'q?'}], fut))
        await asyncio.sleep(0)
        assert emitted[0]['type'] == 'ASK_USER'
        fut.set_result({'q': 'a'})
        answers = await task
        assert answers == {'q': 'a'}
    asyncio.run(main())
    assert [e['type'] for e in traced] == ['ASK_USER', 'ASK_USER_RESOLVED']
    assert traced[0]['questions'] == [{'question': 'q?'}]


def test_ask_user_interaction_timeout_traces_resolution():
    import asyncio

    from codingdude import worker

    async def main():
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        traced = []
        answers = await worker.ask_user_interaction(
            lambda e: None, traced.append, 'run1', [], fut, timeout=0.01)
        assert answers == {'error': 'no answer (timed out)'}
        assert traced[-1]['type'] == 'ASK_USER_RESOLVED'
    asyncio.run(main())


def test_gate_interaction_traces_request_and_resolution():
    import asyncio

    from codingdude import worker

    async def main():
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        emitted, traced = [], []
        task = asyncio.create_task(worker.gate_interaction(
            emitted.append, traced.append, 'run1', 'pytest -q', fut))
        await asyncio.sleep(0)
        assert emitted[0] == {'type': 'GATE_REQUEST', 'command': 'pytest -q'}
        fut.set_result('approve')
        decision = await task
        assert decision == 'approve'
        assert [e['type'] for e in traced] == ['GATE_REQUEST', 'GATE_RESOLVED']
    asyncio.run(main())


def test_wire_interactions_ask_user_works_in_yolo_mode(monkeypatch):
    """Regression: trace_interaction was defined only under `if not yolo:`,
    so every ask_user call in yolo mode raised NameError (free variable).
    wire_interactions must attach a working ask_user regardless of yolo."""
    import asyncio
    from types import SimpleNamespace

    from codingdude import worker
    from codingdude.approvals import ApprovalPolicy

    monkeypatch.setattr(worker, 'trace_terminal', lambda *a: None)
    events = []
    policy = ApprovalPolicy(yolo=True)

    async def main():
        loop = asyncio.get_running_loop()
        pending_ask = {}
        worker.wire_interactions(
            policy, _args(run_id='r1'), SimpleNamespace(),
            loop, events.append, {}, pending_ask)
        assert policy.ask_user is not None  # attached even in yolo mode
        task = asyncio.create_task(policy.ask_user([{'question': 'q?'}]))
        await asyncio.sleep(0)
        assert events[0]['type'] == 'ASK_USER'
        pending_ask['fut'].set_result({'q?': 'yes'})
        answers = await task
        assert answers == {'q?': 'yes'}

    asyncio.run(main())
