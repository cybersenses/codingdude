"""Tests for the atomic trace-append helper (#79).

BADLINEs were observed in session traces because two writers (engine tracer
in the worker, trace_terminal) appended to the same JSONL with plain
open()+write(): concurrent writes interleave mid-line. The helper must make
each line an atomic append, even under concurrent writers.
"""

import json
import threading

import pytest

from codingdude.traces import append_trace_line


@pytest.fixture()
def trace_file(tmp_path):
    return tmp_path / 'traces' / 's1.jsonl'


def test_appends_one_json_line(trace_file):
    append_trace_line(trace_file, {'type': 'RUN_STARTED', 'n': 1})
    lines = trace_file.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])['type'] == 'RUN_STARTED'


def test_appends_create_parent_dirs(trace_file):
    append_trace_line(trace_file, {'type': 'X'})
    assert trace_file.exists()


def test_concurrent_writers_produce_only_intact_lines(trace_file):
    """Threaded stress: every written line must parse as JSON (#79 BADLINE)."""
    n_threads, per_thread = 8, 50

    def worker(tag):
        for i in range(per_thread):
            append_trace_line(trace_file, {'type': 'EV', 'tag': tag, 'i': i, 'pad': 'x' * 400})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = trace_file.read_text(encoding='utf-8').splitlines()
    assert len(lines) == n_threads * per_thread
    for line in lines:
        event = json.loads(line)  # raises on a BADLINE (interleaved write)
        assert event['type'] == 'EV'
