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
"""#148: a worker that never connects its WebSocket must still be noticed.

Live symptom: a worker process died before executing any code (silent spawn
failure right after a server bounce). Because `_reap_worker` was armed only
in the worker-ws endpoint's `finally`, nothing ever reaped the run — the
channel lived forever, the runs row stayed 'running', and the UI waited on a
dead run indefinitely.
"""

import asyncio

from codingdude.db import Database
from codingdude.server import RunChannel, _reap_worker, _run_janitor


class FakeWorker:
    def __init__(self, poll_result: int | None):
        self._poll = poll_result
        self.pid = 4242
        self.returncode = poll_result
        self.terminated = False

    def poll(self) -> int | None:
        return self._poll

    def terminate(self) -> None:
        self.terminated = True
        self._poll = 1  # terminating kills it
        self.returncode = 1


def make_channel(worker: FakeWorker, tmp_path) -> tuple[RunChannel, Database]:
    db = Database.connect(tmp_path)
    db.record_run_start('runX', 'sess1', pid=4242)
    ch = RunChannel('runX', 'sess1', {})
    ch.worker = worker  # type: ignore[assignment]
    return ch, db


async def test_reap_worker_marks_failed_row_and_pushes_error(tmp_path):
    worker = FakeWorker(poll_result=1)
    ch, db = make_channel(worker, tmp_path)
    await _reap_worker(ch, db)
    types = [e['type'] for e in ch.history]
    assert 'RUN_ERROR' in types, types
    row = db.get_run('runX')
    assert row is not None and row['status'] == 'failed'
    assert row['exit_code'] == 1


async def test_reap_worker_records_completed_when_terminal_seen(tmp_path, monkeypatch):
    import codingdude.server as srv
    monkeypatch.setattr(srv, '_TERMINAL_REPLAY_GRACE_S', 0.01)  # else 300s
    worker = FakeWorker(poll_result=0)
    ch, db = make_channel(worker, tmp_path)
    ch.push({'type': 'RUN_FINISHED'})
    await _reap_worker(ch, db)
    assert db.get_run('runX')['status'] == 'completed'
    assert not any(e['type'] == 'RUN_ERROR' for e in ch.history)


async def test_reap_worker_idempotent(tmp_path):
    worker = FakeWorker(poll_result=1)
    ch, db = make_channel(worker, tmp_path)
    await _reap_worker(ch, db)
    await _reap_worker(ch, db)
    errors = [e for e in ch.history if e['type'] == 'RUN_ERROR']
    assert len(errors) == 1, errors


async def test_janitor_reaps_exited_worker(tmp_path, monkeypatch):
    import codingdude.server as srv
    monkeypatch.setattr(srv, '_JANITOR_INTERVAL_S', 0.02)
    worker = FakeWorker(poll_result=1)
    ch, db = make_channel(worker, tmp_path)
    channels = {ch.run_id: ch}
    task = asyncio.create_task(_run_janitor(channels, db))
    for _ in range(200):
        await asyncio.sleep(0.02)
        if db.get_run('runX')['status'] == 'failed':
            break
    task.cancel()
    assert db.get_run('runX')['status'] == 'failed'
    assert any(e['type'] == 'RUN_ERROR' for e in ch.history)


async def test_janitor_terminates_never_booted_worker(tmp_path, monkeypatch):
    import codingdude.server as srv
    monkeypatch.setattr(srv, '_JANITOR_INTERVAL_S', 0.02)
    monkeypatch.setattr(srv, '_BOOT_TIMEOUT_S', 0.05)
    worker = FakeWorker(poll_result=None)  # "running"
    ch, db = make_channel(worker, tmp_path)
    channels = {ch.run_id: ch}
    task = asyncio.create_task(_run_janitor(channels, db))
    for _ in range(200):
        await asyncio.sleep(0.02)
        if worker.terminated:
            break
    assert worker.terminated, 'never-booted worker was not terminated'
    # termination makes poll() non-None → reaper path settles the run
    # (janitor must stay alive to arm it — cancel only once settled)
    for _ in range(400):
        await asyncio.sleep(0.02)
        if db.get_run('runX')['status'] == 'failed':
            break
    task.cancel()
    assert db.get_run('runX')['status'] == 'failed'
    assert any(
        e.get('code') == 'worker_died' for e in ch.history if e['type'] == 'RUN_ERROR'
    )


async def test_janitor_checkpoints_idle_wal(tmp_path, monkeypatch):
    """#238: every janitor sweep also tries to bound the WAL via
    db.checkpoint_idle, so a busy production DB still gets periodic
    TRUNCATE attempts."""
    import codingdude.server as srv
    monkeypatch.setattr(srv, '_JANITOR_INTERVAL_S', 0.02)
    calls = []
    monkeypatch.setattr(Database, 'checkpoint_idle', lambda self, **kw: calls.append(kw))
    worker = FakeWorker(poll_result=None)
    ch, db = make_channel(worker, tmp_path)
    ch.boot_seen = True
    channels = {ch.run_id: ch}
    task = asyncio.create_task(_run_janitor(channels, db))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if calls:
            break
    task.cancel()
    assert calls, 'janitor never attempted an idle WAL checkpoint'


async def test_janitor_spares_healthy_booted_worker(tmp_path, monkeypatch):
    import codingdude.server as srv
    monkeypatch.setattr(srv, '_JANITOR_INTERVAL_S', 0.02)
    monkeypatch.setattr(srv, '_BOOT_TIMEOUT_S', 0.05)
    worker = FakeWorker(poll_result=None)
    ch, db = make_channel(worker, tmp_path)
    ch.boot_seen = True
    channels = {ch.run_id: ch}
    task = asyncio.create_task(_run_janitor(channels, db))
    await asyncio.sleep(0.15)
    task.cancel()
    assert not worker.terminated
    assert db.get_run('runX')['status'] == 'running'
