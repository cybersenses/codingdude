"""R28 Phase 1: ProcessRegistry — visibility-only tracking of shell processes.

Every shell command the agent spawns is recorded here (pid, command,
lifecycle) and surfaced two ways: as PROCESS_STARTED/PROCESS_EXITED trace
events, and as rows in the `processes` DB table so the HITL frontend can
list them via GET /sessions/{id}/processes.

Phase 1 deliberately changes no behavior: processes that outlive their
parent are registered as orphans (`background=True`), never killed. Phase 2
adds kill/poll tools over this same registry.
"""
from __future__ import annotations

import os
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


def _pid_alive(pid: int) -> bool:
    """True if an OS process with `pid` currently exists and runs.

    POSIX: signal 0 probe. Windows: os.kill(pid, 0) would TERMINATE the
    process (TerminateProcess), so poll via OpenProcess/WaitForSingleObject
    instead — a terminated-but-still-referenced process reports dead.
    """
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    import ctypes
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


class ProcessRegistry:
    """In-memory process bookkeeping with optional DB persistence + events."""

    def __init__(
        self,
        on_event: Callable[[dict], None] | None = None,
        db: Any = None,
        session_id: str = '',
    ):
        self._on_event = on_event
        self._db = db
        self._session_id = session_id
        self._records: list[dict] = []

    def register(self, pid: int, command: str) -> None:
        record = {
            'pid': pid,
            'command': command,
            'started_at': datetime.now(UTC).isoformat(),
            'status': 'running',
            'exit_code': None,
            'background': False,
        }
        self._records.append(record)
        self._emit({
            'type': 'PROCESS_STARTED',
            'pid': pid,
            'command': command,
        })
        self._persist(record)

    def finish(
        self,
        pid: int,
        *,
        status: str,
        exit_code: int | None = None,
        background: bool = False,
    ) -> None:
        record = next(
            (r for r in reversed(self._records) if r['pid'] == pid), None
        )
        if record is None:
            return
        record['status'] = status
        record['exit_code'] = exit_code
        record['background'] = background
        self._emit({
            'type': 'PROCESS_EXITED',
            'pid': pid,
            'command': record['command'],
            'status': status,
            'exit_code': exit_code,
            'background': background,
        })
        self._persist(record, update=True)

    def poll(self, pid: int) -> dict | None:
        """Registry record for `pid` with live liveness status, or None."""
        record = next(
            (r for r in reversed(self._records) if r['pid'] == pid), None
        )
        if record is None:
            return None
        if record['status'] == 'running':
            record['status'] = (
                'running' if _pid_alive(pid) else 'exited (no capture)')
        return dict(record)

    def kill(self, pid: int) -> str:
        """Terminate a registered process. Ownership: only PIDs this
        session registered may be killed."""
        record = next(
            (r for r in reversed(self._records) if r['pid'] == pid), None
        )
        if record is None:
            return (
                f'pid {pid} was not registered by this session — refusing '
                'to kill processes the agent does not own.'
            )
        try:
            # Windows: no SIGKILL; os.kill with any signal terminates the
            # process (TerminateProcess). POSIX: SIGKILL is correct.
            os.kill(pid, getattr(signal, 'SIGKILL', signal.SIGTERM))
        except ProcessLookupError:
            pass
        except OSError as exc:
            return f'failed to kill pid {pid}: {exc}'
        if record['status'] == 'running':
            self.finish(pid, status='killed')
        return f'killed pid {pid} ({record["command"]})'

    def snapshot(self) -> list[dict]:
        """Recorded processes, newest first."""
        return [
            {k: v for k, v in r.items() if k != 'row_id'}
            for r in reversed(self._records)
        ]

    def _emit(self, event: dict) -> None:
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001 — visibility must never fail a run
                pass

    def _persist(self, record: dict, *, update: bool = False) -> None:
        if self._db is None or not self._session_id:
            return
        try:
            if update and record.get('row_id') is not None:
                self._db.update_process(
                    record['row_id'],
                    status=record['status'],
                    exit_code=record['exit_code'],
                    background=record['background'],
                )
            else:
                row_id = self._db.record_process(
                    self._session_id,
                    pid=record['pid'],
                    command=record['command'],
                    started_at=record['started_at'],
                    status=record['status'],
                    exit_code=record['exit_code'],
                    background=record['background'],
                )
                record['row_id'] = row_id
        except Exception:  # noqa: BLE001 — visibility must never fail a run
            pass
