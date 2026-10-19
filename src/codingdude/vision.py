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
"""Vision-in-the-loop (R1): route rendered screenshots through the vision model.

The agent can *produce* images (pixel gates, UI shots) but cannot see them
through its normal tool channel. `inspect_image` closes that loop: it loads an
image from the Workdir, sends it to the configured vision model, and hands the
model's critique back to the agent as text — so a visual gate can be *judged*,
not just rendered.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset

MEDIA_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
}

INSPECT_INSTRUCTIONS = (
    'You are a meticulous visual reviewer. Describe what the image actually '
    'shows, then judge it against the question asked. Call out layout bugs, '
    'broken styling, contrast problems, and anything visually wrong. Be '
    'concrete and terse.'
)

DEFAULT_QUESTION = (
    'Critique this screenshot: does it look correct and polished? '
    'List any visual defects you can actually see.'
)


def build_run_prompt(prompt: str, image_path: Path | None) -> str | list:
    """The run prompt with an optional attached image (#82 R1 vision half).

    No image → the plain string. An image → `[text, BinaryContent]`, the
    multi-part form pydantic-ai passes to vision-capable models. Fail fast on
    missing files and non-image suffixes — a silent text-only run would look
    like a model misunderstanding instead of a broken attachment.
    """
    if image_path is None:
        return prompt
    media = MEDIA_TYPES.get(image_path.suffix.lower())
    if media is None:
        raise ValueError(
            f'{image_path.name!r} is not an image (expected one of: '
            + ', '.join(sorted(MEDIA_TYPES)) + ').'
        )
    from pydantic_ai.messages import BinaryContent

    return [prompt, BinaryContent(data=image_path.read_bytes(), media_type=media)]


def build_vision_toolset(
    vision_model: Model,
    workdir: Path,
    emitter: Callable[[dict], None] | None = None,
) -> FunctionToolset:
    """The `inspect_image` tool, bound to the Workdir via closure.

    `emitter` (the run's trace emitter) records IMAGE_INSPECTED events so the
    UI/trace shows the pixel gate was actually judged, not assumed.
    """

    def resolve(path: str) -> Path:
        target = (workdir / path).resolve()
        if not target.is_relative_to(workdir.resolve()):
            raise ValueError(f'path escapes the Workdir: {path}')
        return target

    async def inspect_image(path: str, question: str = '') -> str:
        """Look at an image with the vision model and report what you see.

        Use this after producing a screenshot or render — a visual gate may
        only be called 'verified' after inspect_image has passed on it.
        """
        try:
            target = resolve(path)
        except ValueError as exc:
            from pydantic_ai import ModelRetry

            raise ModelRetry(str(exc)) from None
        if not target.is_file():
            from pydantic_ai import ModelRetry

            raise ModelRetry(
                f'{path!r} is not a file (list_dir first to find the render).'
            )
        media = MEDIA_TYPES.get(target.suffix.lower())
        if media is None:
            from pydantic_ai import ModelRetry

            raise ModelRetry(
                f'{path!r} is not an image (expected one of: '
                + ', '.join(sorted(MEDIA_TYPES))
                + ').'
            )
        from pydantic_ai.messages import BinaryContent

        agent: Agent = Agent(model=vision_model, instructions=INSPECT_INSTRUCTIONS)
        result = await agent.run([
            question.strip() or DEFAULT_QUESTION,
            BinaryContent(data=target.read_bytes(), media_type=media),
        ])
        if emitter is not None:
            emitter({'type': 'IMAGE_INSPECTED', 'path': path, 'question': question})
        return str(result.output)

    return FunctionToolset([inspect_image])
