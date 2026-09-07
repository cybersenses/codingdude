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
