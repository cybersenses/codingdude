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
"""Review seam: the server never runs an agent in its own process (ADR-0002).

Covers the two contract fixes from the architecture review:
- Engine.review() is a public entry point — callers never poke _extraction_model.
- POST /sessions/{id}/review delegates to a worker subprocess (--review mode).
"""

import asyncio
import json
import subprocess
import sys

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from codingdude.config import load_config
from codingdude.engine import Engine


def _scripted(reply: str) -> FunctionModel:
    return FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart(content=reply)]))


def test_review_returns_model_findings(db, workdir):
    session_id = db.create_session(workdir, title='t')
    engine = Engine(config=load_config(), db=db, extraction_model=_scripted('found a bug'))
    assert asyncio.run(engine.review(session_id)) == 'found a bug'


def test_review_clean_reply_defaults_to_clean_verdict(db, workdir):
    session_id = db.create_session(workdir, title='t')
    engine = Engine(config=load_config(), db=db, extraction_model=_scripted('CLEAN'))
    assert asyncio.run(engine.review(session_id)) == 'CLEAN — no findings'


def test_extraction_model_setter_is_public(db, workdir):
    """The worker sets the extraction model through the public seam."""
    engine = Engine(config=load_config(), db=db)
    engine.extraction_model = _scripted('x')
    assert engine.extraction_model is not None


def test_worker_review_mode_runs_out_of_process(home, db, workdir):
    """python -m codingdude.worker --review prints findings JSON on stdout."""
    (home / 'config.toml').write_text(
        '[models]\nsubagent = "codingdude-test:echo"\n', encoding='utf-8'
    )
    session_id = db.create_session(workdir, title='t')
    proc = subprocess.run(
        [sys.executable, '-m', 'codingdude.worker', '--review', session_id],
        capture_output=True, text=True, timeout=120, env=None, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert 'worker-echo-ok' in json.loads(proc.stdout)['findings']
