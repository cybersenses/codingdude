"""Shared fixtures: an isolated CodingDude home and a temp Workdir."""

from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated config/data directory, via the CODEDUDE_HOME override."""
    h = tmp_path / 'codingdude-home'
    monkeypatch.setenv('CODEDUDE_HOME', str(h))
    return h


@pytest.fixture
def workdir(tmp_path) -> Path:
    w = tmp_path / 'project'
    w.mkdir()
    (w / 'README.md').write_text('# demo\nhello world\n')
    (w / 'src').mkdir()
    (w / 'src' / 'app.py').write_text('def greet():\n    return "hi"\n')
    return w
