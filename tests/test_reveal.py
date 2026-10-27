# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""R69 #261: the reveal_code tool — validation only (the UI does the work)."""
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelRetry

from codingdude.reveal import build_reveal_toolset


@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'app.py').write_text('print("hi")\n')
    return tmp_path


@pytest.fixture()
def reveal(workdir: Path):
    return build_reveal_toolset(workdir).tools['reveal_code'].function


def test_reveal_returns_confirmation(reveal, workdir: Path):
    out = reveal('src/app.py', 3)
    assert out == 'revealed src/app.py:3-3 in the editor'


def test_reveal_range_and_default_end(reveal):
    assert reveal('src/app.py', 3, 8).endswith('src/app.py:3-8 in the editor')


def test_reveal_clamps_start_to_one_and_swaps(reveal):
    assert reveal('src/app.py', -2).endswith('src/app.py:1-1 in the editor')
    assert reveal('src/app.py', 8, 3).endswith('src/app.py:3-8 in the editor')


def test_reveal_missing_file_is_model_retry(reveal):
    with pytest.raises(ModelRetry, match='is not a file'):
        reveal('src/nope.py', 1)


def test_reveal_escape_is_model_retry(reveal):
    with pytest.raises(ModelRetry, match='escapes'):
        reveal('../outside.py', 1)


def test_reveal_forward_slash_path_on_windows(reveal, workdir: Path):
    # Agents cite forward-slash paths even on Windows; the UI API expects
    # them too, so the tool must accept and echo them as-is.
    assert reveal('src/app.py', 1) == 'revealed src/app.py:1-1 in the editor'
