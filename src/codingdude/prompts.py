"""Versioned prompt loading: prompts live in src/codingdude/prompts/*.md so
they can be diffed, evaluated (bench), and improved without touching code."""

from functools import cache
from importlib import resources


@cache
def load_prompt(name: str) -> str:
    return (
        resources.files('codingdude').joinpath(f'prompts/{name}.md').read_text(encoding='utf-8')
    )
