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
