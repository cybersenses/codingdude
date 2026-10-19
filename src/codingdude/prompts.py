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
"""Versioned prompt loading: prompts live in src/codingdude/prompts/*.md so
they can be diffed, evaluated (bench), and improved without touching code."""

from functools import cache
from importlib import resources


@cache
def load_prompt(name: str) -> str:
    """Load a bundled prompt template by name from the prompts directory."""
    return (
        resources.files('codingdude').joinpath(f'prompts/{name}.md').read_text(encoding='utf-8')
    )
