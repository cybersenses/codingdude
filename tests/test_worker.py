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
