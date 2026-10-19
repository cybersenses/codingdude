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
