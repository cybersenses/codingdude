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
from datetime import UTC, datetime
from pathlib import Path

_lock = threading.Lock()


def append_trace_line(trace_file: Path, event: dict) -> None:
    """Append one event as a single atomic, self-contained JSON line."""
    trace_file = Path(trace_file)
    payload = json.dumps({'ts': datetime.now(UTC).isoformat(), **event}) + '\n'
    data = payload.encode('utf-8')
    trace_file.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        fd = os.open(trace_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
