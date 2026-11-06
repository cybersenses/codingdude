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
"""Atomic append for trace JSONL files (#79).

Trace writers historically used plain `open(path, 'a') + write()`, so two
concurrent writers (the worker's engine tracer and `trace_terminal`, or two
runs sharing a session) could interleave mid-line and leave BADLINEs in the
trace. `append_trace_line` makes each line a single atomic append:
`os.O_APPEND` keeps the file offset at EOF for every write, and one
`os.write` call per line means the OS never splits it. An in-process lock
additionally preserves line ordering between threads of one process.

R79 #291 adds `DeltaCoalescer` for compact trace mode: streaming-delta
events (TEXT_MESSAGE_CONTENT / TOOL_CALL_ARGS) are buffered and written as
one coalesced line per flush window. Concatenating a message's deltas still
reconstructs the text exactly — at chunk-level, not token-level, timing
granularity. Crash loss is bounded to one flush window. The live UI emit
path (engine._make_tracer) is separate and stays per-token in every mode.
"""

import json
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_lock = threading.Lock()
# One persistent fd per trace file (R78 #289): a trace line is written for
# every streamed token, and the previous open/write/close per line measured
# 316µs — ~20x the write itself. O_APPEND keeps every write a single record
# at EOF, and the global lock still serializes writers, so lines never
# interleave; only the syscall overhead goes away.
_fds: OrderedDict[Path, int] = OrderedDict()
_FD_CACHE_MAX = 128


def _drop_fd(trace_file: Path) -> int | None:
    """Close and forget the cached fd for a trace file (returns the old fd)."""
    fd = _fds.pop(trace_file, None)
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass  # already closed/replaced underneath us — nothing to do
    return fd


def _open_trace_fd(trace_file: Path) -> int:
    """Reuse the cached O_APPEND fd for a trace file, opening it if needed."""
    cached = _fds.get(trace_file)
    if cached is not None:
        _fds.move_to_end(trace_file)
        return cached
    trace_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(trace_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    _fds[trace_file] = fd
    while len(_fds) > _FD_CACHE_MAX:
        _drop_fd(next(iter(_fds)))
    return fd


class DeltaCoalescer:
    """Buffer streaming-delta trace events and write them coalesced (R79 #291).

    Compact trace mode: one line per token-chunk costs ~110 bytes of JSON
    overhead per ~15-byte token. Adjacent same-type delta events are
    concatenated into a single line; concatenating the deltas still
    reconstructs the text exactly, at chunk-level timing granularity. All
    writes go through append_trace_line, so #79/#289 atomicity is preserved
    and the first buffered event's keys (run_id, ...) are kept.

    Flush triggers: any non-delta event (passed through after flushing),
    the size or age bound (checked at append time — no timer task), and
    close(). Crash loss is bounded: at most one flush window of tokens.
    """

    _DELTA_TYPES = frozenset({'TEXT_MESSAGE_CONTENT', 'TOOL_CALL_ARGS'})

    def __init__(
        self, trace_file: Path, *, flush_bytes: int, flush_ms: float,
        now: Callable[[], float],
    ):
        self._trace_file = Path(trace_file)
        self._flush_bytes = flush_bytes
        self._flush_ms = flush_ms
        self._now = now
        self._type: str | None = None
        self._head: dict = {}
        self._chunks: list[str] = []
        self._bytes = 0
        self._first_ts: float | None = None

    def append(self, event: dict) -> None:
        """Buffer one delta event, or flush + pass a non-delta event through."""
        if event.get('type') not in self._DELTA_TYPES:
            self.flush()
            append_trace_line(self._trace_file, event)
            return
        if self._type is not None and event['type'] != self._type:
            self.flush()
        if (
            self._type is not None
            and self._first_ts is not None
            and (self._bytes + len(event['delta']) > self._flush_bytes
                 or (self._now() - self._first_ts) * 1000 >= self._flush_ms)
        ):
            # Adding this chunk would cross a bound: close the current line
            # first so every line stays <= flush_bytes and stale buffers
            # never outlive flush_ms.
            self.flush()
        if self._type is None:
            self._type = event['type']
            self._head = {k: v for k, v in event.items() if k != 'delta'}
            self._first_ts = self._now()
        self._chunks.append(event['delta'])
        self._bytes += len(event['delta'])

    def flush(self) -> None:
        """Write buffered deltas as one line; no-op when nothing is buffered."""
        if self._type is None:
            return
        append_trace_line(self._trace_file, {
            **self._head,
            'type': self._type,
            'delta': ''.join(self._chunks),
            'coalesced': len(self._chunks),
        })
        self._type = None
        self._head = {}
        self._chunks = []
        self._bytes = 0
        self._first_ts = None

    def close(self) -> None:
        """Flush any buffered deltas (engine shutdown / coalescer teardown)."""
        self.flush()


def append_trace_line(trace_file: Path, event: dict) -> None:
    """Append one event as a single atomic, self-contained JSON line."""
    trace_file = Path(trace_file)
    payload = json.dumps({'ts': datetime.now(UTC).isoformat(), **event}) + '\n'
    data = payload.encode('utf-8')
    with _lock:
        try:
            fd = _open_trace_fd(trace_file)
            os.write(fd, data)
        except OSError:
            # The cached fd went stale (file deleted/replaced underneath it,
            # handle closed externally): rebuild once and retry the append.
            _drop_fd(trace_file)
            fd = _open_trace_fd(trace_file)
            os.write(fd, data)
