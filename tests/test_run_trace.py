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
"""R31: run_id provenance on trace events.

Every trace event carries the run that produced it, so post-hoc forensics
can attribute events to runs even across server bounces (the run-6Iyu
mystery: a run completed but its events were unattributable).
"""

import json

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine


def _engine(home):
    return Engine(config=load_config(), db=Database.connect(home))


def test_tracer_stamps_run_id(home, workdir):
    engine = _engine(home)
    sid = engine._db.create_session(workdir)
    traced = engine._make_tracer(sid, workdir, trace=True, emit=None, run_id='runX')
    traced({'type': 'TEXT_MESSAGE_START'})
    line = (home / 'traces' / f'{sid}.jsonl').read_text(encoding='utf-8').strip()
    event = json.loads(line)
    assert event['run_id'] == 'runX'


def test_tracer_without_run_id_leaves_event_untouched(home, workdir):
    engine = _engine(home)
    sid = engine._db.create_session(workdir)
    traced = engine._make_tracer(sid, workdir, trace=True, emit=None, run_id=None)
    traced({'type': 'TEXT_MESSAGE_START'})
    line = (home / 'traces' / f'{sid}.jsonl').read_text(encoding='utf-8').strip()
    event = json.loads(line)
    assert 'run_id' not in event


# --- R79 #291: tracer split-sink — compact trace, raw UI emit --------------

def test_tracer_default_compact_coalesces_trace_but_emit_stays_raw(home, workdir):
    """Compact (the default): the trace file holds coalesced delta lines,
    while every UI emit receives the raw per-token event (SSE smoothness
    is a UI contract, independent of the trace mode)."""
    engine = _engine(home)
    sid = engine._db.create_session(workdir)
    seen: list[dict] = []
    traced = engine._make_tracer(
        sid, workdir, trace=True, emit=seen.append, run_id='runX',
    )
    for i in range(50):
        traced({'type': 'TEXT_MESSAGE_CONTENT', 'delta': f'w{i} '})
    traced({'type': 'RUN_FINISHED'})

    # UI path: all 50 raw events, per-token.
    assert len(seen) == 51
    assert all(e['run_id'] == 'runX' for e in seen)
    # Trace path: coalesced — far fewer delta lines, exact concatenation.
    events = [
        json.loads(line)
        for line in (home / 'traces' / f'{sid}.jsonl')
        .read_text(encoding='utf-8').splitlines()
    ]
    deltas = [e for e in events if e['type'] == 'TEXT_MESSAGE_CONTENT']
    assert len(deltas) < 10
    assert ''.join(e['delta'] for e in deltas) == ''.join(f'w{i} ' for i in range(50))
    assert all(e['run_id'] == 'runX' for e in deltas)


def test_tracer_full_mode_appends_every_delta_line(home, workdir):
    """[trace] deltas = "full": one trace line per delta — byte-identical
    to pre-R79 traces (old replay tooling keeps working)."""
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text(
        '[trace]\ndeltas = "full"\n', encoding='utf-8',
    )
    engine = _engine(home)
    assert engine._config.trace.deltas == 'full'
    sid = engine._db.create_session(workdir)
    traced = engine._make_tracer(sid, workdir, trace=True, emit=None, run_id='runX')
    for i in range(5):
        traced({'type': 'TEXT_MESSAGE_CONTENT', 'delta': f'w{i} '})
    traced({'type': 'RUN_FINISHED'})

    events = [
        json.loads(line)
        for line in (home / 'traces' / f'{sid}.jsonl')
        .read_text(encoding='utf-8').splitlines()
    ]
    assert [e['type'] for e in events] == ['TEXT_MESSAGE_CONTENT'] * 5 + ['RUN_FINISHED']
    assert [e['delta'] for e in events[:5]] == [f'w{i} ' for i in range(5)]
    assert all('coalesced' not in e for e in events)
