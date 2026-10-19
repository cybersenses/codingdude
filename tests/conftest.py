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
"""Shared fixtures: an isolated CodingDude home, a temp Workdir, and an engine."""

from pathlib import Path

import pytest

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated config/data directory, via the CODEDUDE_HOME override."""
    h = tmp_path / 'codingdude-home'
    monkeypatch.setenv('CODEDUDE_HOME', str(h))
    return h


@pytest.fixture
def db(home) -> Database:
    return Database.connect(home)


@pytest.fixture
def engine(db) -> Engine:
    return Engine(config=load_config(), db=db)


@pytest.fixture
def workdir(tmp_path) -> Path:
    w = tmp_path / 'project'
    w.mkdir()
    (w / 'README.md').write_text('# demo\nhello world\n')
    (w / 'src').mkdir()
    (w / 'src' / 'app.py').write_text('def greet():\n    return "hi"\n')
    return w
