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
"""Tests for the atomic trace-append helper (#79).

BADLINEs were observed in session traces because two writers (engine tracer
in the worker, trace_terminal) appended to the same JSONL with plain
open()+write(): concurrent writes interleave mid-line. The helper must make
each line an atomic append, even under concurrent writers.
"""

import json
import os
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


def test_append_recovers_from_stale_cached_fd(trace_file):
    """A cached fd closed behind our back (external rotation/close) must be
    detected and rebuilt: the append lands instead of raising EBADF, and no
    event is lost."""
    append_trace_line(trace_file, {'type': 'A'})
    from codingdude import traces

    os.close(traces._fds[trace_file])  # external close → cache holds a stale fd
    append_trace_line(trace_file, {'type': 'B'})
    lines = trace_file.read_text(encoding='utf-8').splitlines()
    assert [json.loads(line)['type'] for line in lines] == ['A', 'B']


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


# --- R79 #291: DeltaCoalescer — bounded-loss delta coalescing -------------
#
# Contract (ROADMAP R79): compact trace mode coalesces adjacent same-type
# delta events into fewer lines; concatenating the deltas still reconstructs
# the model's text EXACTLY (crash-reconstruction requirement, user-confirmed);
# live SSE stays per-token (engine's emit path is separate).

def test_coalesced_deltas_reconstruct_text_exactly(trace_file):
    """100 token deltas coalesce into fewer lines; concatenation is exact."""
    from codingdude.traces import DeltaCoalescer

    clock = [0.0]
    coalescer = DeltaCoalescer(
        trace_file, flush_bytes=4096, flush_ms=250, now=lambda: clock[0],
    )
    tokens = [f'token-{i} ' for i in range(100)]
    for t in tokens:
        clock[0] += 0.005  # 5ms per token: under the 250ms age bound
        coalescer.append({'type': 'TEXT_MESSAGE_CONTENT', 'delta': t})
    coalescer.append({'type': 'RUN_FINISHED'})  # pass-through flushes
    coalescer.close()

    events = [json.loads(line) for line in trace_file.read_text(encoding='utf-8').splitlines()]
    text = ''.join(
        e['delta'] for e in events if e['type'] == 'TEXT_MESSAGE_CONTENT'
    )
    assert text == ''.join(tokens)
    # Coalescing actually happened: far fewer delta lines than tokens.
    delta_lines = [e for e in events if e['type'] == 'TEXT_MESSAGE_CONTENT']
    assert len(delta_lines) < 10
    assert any(e.get('coalesced', 1) > 1 for e in delta_lines)


def test_non_delta_event_flushes_pending_deltas_first(trace_file):
    """Order is preserved: buffered deltas hit the file before the event
    that triggered the flush (tour/waterfall START/END pairing reads this)."""
    from codingdude.traces import DeltaCoalescer

    coalescer = DeltaCoalescer(
        trace_file, flush_bytes=1 << 20, flush_ms=1e9, now=lambda: 0.0,
    )
    coalescer.append({'type': 'TEXT_MESSAGE_CONTENT', 'delta': 'a'})
    coalescer.append({'type': 'TEXT_MESSAGE_CONTENT', 'delta': 'b'})
    coalescer.append({'type': 'TOOL_CALL_START', 'tool_name': 'edit_file'})
    coalescer.append({'type': 'TEXT_MESSAGE_CONTENT', 'delta': 'c'})
    coalescer.close()

    events = [json.loads(line) for line in trace_file.read_text(encoding='utf-8').splitlines()]
    types = [e['type'] for e in events]
    assert types == [
        'TEXT_MESSAGE_CONTENT', 'TOOL_CALL_START', 'TEXT_MESSAGE_CONTENT',
    ]
    assert events[0]['delta'] == 'ab'
    assert events[2]['delta'] == 'c'


def test_size_bound_flushes_without_non_delta_event(trace_file):
    """A delta pushing the buffer past flush_bytes flushes immediately."""
    from codingdude.traces import DeltaCoalescer

    coalescer = DeltaCoalescer(
        trace_file, flush_bytes=8, flush_ms=1e9, now=lambda: 0.0,
    )
    coalescer.append({'type': 'TEXT_MESSAGE_CONTENT', 'delta': '12345'})
    coalescer.append({'type': 'TEXT_MESSAGE_CONTENT', 'delta': '67890'})
    coalescer.close()

    events = [json.loads(line) for line in trace_file.read_text(encoding='utf-8').splitlines()]
    deltas = [e['delta'] for e in events if e['type'] == 'TEXT_MESSAGE_CONTENT']
    assert deltas == ['12345', '67890']


def test_age_bound_flushes_at_append_time(trace_file):
    """Age is checked when the next delta arrives — no timer task needed;
    a gap over flush_ms closes the current line."""
    from codingdude.traces import DeltaCoalescer

    clock = [0.0]
    coalescer = DeltaCoalescer(
        trace_file, flush_bytes=1 << 20, flush_ms=250, now=lambda: clock[0],
    )
    coalescer.append({'type': 'TEXT_MESSAGE_CONTENT', 'delta': 'a'})
    clock[0] += 0.3  # 300ms later — past the 250ms bound
    coalescer.append({'type': 'TEXT_MESSAGE_CONTENT', 'delta': 'b'})
    coalescer.close()

    events = [json.loads(line) for line in trace_file.read_text(encoding='utf-8').splitlines()]
    deltas = [e['delta'] for e in events if e['type'] == 'TEXT_MESSAGE_CONTENT']
    assert deltas == ['a', 'b']
