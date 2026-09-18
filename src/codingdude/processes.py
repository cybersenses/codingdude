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

import logging
import os
import signal
import subprocess
import threading
import time as _time
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
        self._sessions: dict[int, ShellSession] = {}

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
        logging.getLogger('codingdude.processes').info(
            'PROCESS_SPAWN pid=%s cmd=%s', pid, command[:160])
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
        logging.getLogger('codingdude.processes').info(
            'PROCESS_END pid=%s status=%s code=%s cmd=%s',
            pid, status, exit_code, record['command'][:160])
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
        logging.getLogger('codingdude.processes').info(
            'PROCESS_KILL pid=%s cmd=%s', pid, record['command'][:160])
        if record['status'] == 'running':
            self.finish(pid, status='killed')
        return f'killed pid {pid} ({record["command"]})'

    def start_session(
        self, command: str | list[str], cwd: str | os.PathLike[str] = '.',
        shell_bin: str | None = None,
    ) -> ShellSession:
        """Spawn a persistent shell session and register it.

        `command` is a shell string (run via `shell_bin` or the platform
        default shell) or a ready argv list run directly. The session's
        stdin stays open so the agent can drive interactive commands across
        multiple tool calls; output streams as PROCESS_OUTPUT events.
        """
        if isinstance(command, list):
            argv: list[str] = command
        elif shell_bin:
            argv = [shell_bin, '-c', command]
        elif os.name == 'nt':
            argv = [os.environ.get('COMSPEC', 'cmd.exe'), '/c', command]
        else:
            argv = ['/bin/sh', '-c', command]
        session = ShellSession(argv, cwd, self)
        self.register(session.pid, str(command))
        self._sessions[session.pid] = session
        return session

    def write(self, pid: int, text: str) -> str:
        """Write `text` to a session's stdin. Ownership: registered
        sessions only."""
        session = self._sessions.get(pid)
        if session is None:
            return (
                f'pid {pid} is not an interactive session of this agent — '
                'refusing to write to processes it does not own.'
            )
        return session.write(text)

    def _session_finished(self, pid: int, status: str) -> None:
        self._sessions.pop(pid, None)
        record = next(
            (r for r in reversed(self._records) if r['pid'] == pid), None
        )
        if record is not None and record['status'] == 'running':
            self.finish(pid, status=status)

    @property
    def sessions(self) -> dict[int, ShellSession]:
        """Live interactive sessions by pid (read-only view)."""
        return dict(self._sessions)

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


class ShellSession:
    """A persistent shell process with an open stdin pipe.

    A reader thread drains stdout into an internal buffer and emits each
    chunk as a PROCESS_OUTPUT trace event, so HITL sees session output live
    over SSE. `read_new()` returns only output produced since the last read.
    """

    def __init__(
        self, argv: list[str], cwd: str | os.PathLike[str],
        registry: ProcessRegistry,
    ):
        self._registry = registry
        self._lock = threading.Lock()
        self._buffer: list[str] = []
        self._proc = subprocess.Popen(
            argv, cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        self.pid = self._proc.pid
        self._reader = threading.Thread(
            target=self._drain, name=f'shell-session-{self.pid}', daemon=True
        )
        self._reader.start()

    def write(self, text: str) -> str:
        stdin = self._proc.stdin
        if stdin is None or self._proc.poll() is not None:
            return f'pid {self.pid} session is no longer accepting input.'
        try:
            stdin.write(text)
            stdin.flush()
        except (OSError, ValueError) as exc:
            return f'failed writing to session {self.pid}: {exc}'
        return f'wrote {len(text)} chars to session {self.pid}'

    def read_new(self) -> str:
        """Output produced since the last read_new() call."""
        with self._lock:
            out = ''.join(self._buffer)
            self._buffer.clear()
        return out

    def terminate(self) -> None:
        self._registry.kill(self.pid)

    def _drain(self) -> None:
        status = 'killed'
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                with self._lock:
                    self._buffer.append(line)
                self._registry._emit({
                    'type': 'PROCESS_OUTPUT',
                    'pid': self.pid,
                    'data': line,
                })
        except (OSError, ValueError):
            return  # process died under us; finish below still applies
        finally:
            code = self._proc.poll()
            if code is None:
                # A kill raced the reader: give the OS a beat, then mark.
                for _ in range(20):
                    _time.sleep(0.05)
                    code = self._proc.poll()
                    if code is not None:
                        break
            else:
                status = 'exited'
            self._registry._session_finished(self.pid, status)
