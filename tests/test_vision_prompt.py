"""#82 R1 vision half: engine-side image attachment at the message-build seam."""
from pathlib import Path

import pytest


def test_build_run_prompt_without_image_is_plain_string():
    from codingdude.vision import build_run_prompt

    assert build_run_prompt('do the thing', None) == 'do the thing'


def test_build_run_prompt_with_image_wraps_binary_content(tmp_path: Path):
    from pydantic_ai.messages import BinaryContent

    from codingdude.vision import build_run_prompt

    image = tmp_path / 'shot.png'
    image.write_bytes(b'\x89PNG fake')
    prompt = build_run_prompt('what is wrong here', image)
    assert isinstance(prompt, list)
    assert prompt[0] == 'what is wrong here'
    (part,) = [p for p in prompt if isinstance(p, BinaryContent)]
    assert part.media_type == 'image/png'
    assert part.data == b'\x89PNG fake'


def test_build_run_prompt_rejects_missing_image(tmp_path: Path):
    from codingdude.vision import build_run_prompt

    with pytest.raises(FileNotFoundError):
        build_run_prompt('look', tmp_path / 'nope.png')


def test_build_run_prompt_rejects_non_image(tmp_path: Path):
    from codingdude.vision import build_run_prompt

    text = tmp_path / 'notes.txt'
    text.write_text('hello')
    with pytest.raises(ValueError):
        build_run_prompt('look', text)
