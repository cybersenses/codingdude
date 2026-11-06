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
"""

import json
import os
import threading
from collections import OrderedDict
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
