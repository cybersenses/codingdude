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
