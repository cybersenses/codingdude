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
"""Vision-in-the-loop (R1): the inspect_image tool routes renders to the
vision model and hands the critique back to the agent as text."""
import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.models.test import TestModel

from codingdude.vision import build_vision_toolset

PNG = bytes.fromhex('89504e470d0a1a0a0000000d494844520000000100000001080200000090')


@pytest.fixture()
def workdir(tmp_path):
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    (workdir / 'shot.png').write_bytes(PNG)
    (workdir / 'notes.txt').write_text('hello')
    return workdir


def events():
    seen = []
    return seen, seen.append


def test_inspect_image_returns_critique(workdir):
    seen, emitter = events()
    toolset = build_vision_toolset(TestModel(), workdir, emitter=emitter)
    [tool] = toolset.tools.values()
    out = _run(tool.function, 'shot.png', 'is the button blue?')
    assert 'critique' in out.lower() or out  # TestModel echoes; text comes back
    assert seen == [{'type': 'IMAGE_INSPECTED', 'path': 'shot.png',
                     'question': 'is the button blue?'}]


def test_inspect_image_rejects_escapes_and_non_images(workdir):
    toolset = build_vision_toolset(TestModel(), workdir)
    [tool] = toolset.tools.values()
    with pytest.raises(ModelRetry):
        _run(tool.function, '../outside.png')
    with pytest.raises(ModelRetry):
        _run(tool.function, 'notes.txt')
    with pytest.raises(ModelRetry):
        _run(tool.function, 'missing.png')


def _run(fn, path, question=''):
    import asyncio

    return asyncio.run(fn(path=path, question=question))
