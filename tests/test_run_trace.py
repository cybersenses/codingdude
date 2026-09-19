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
