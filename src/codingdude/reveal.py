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
"""R69 #261: the `reveal_code` tool — point the user's editor at code.

The agent answers "where is X done?" with file:line citations in prose, but
prose makes the user go find the file. This tool makes the answer visible:
the tool-call event already carries its args to the browser (TOOL_CALL_START
includes tool_name + args), and the frontend reacts by opening the editor
panel, loading the file, scrolling to and highlighting the cited lines.

Nothing is read, written, or executed for side effects here — the tool is
pure UI signalling. The one thing the server must do is validate: a bogus
path should fail fast as a ModelRetry instead of arriving in the UI as a
dead click.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from .tools import resolve_workdir_path


def build_reveal_toolset(workdir: Path) -> FunctionToolset:
    """The `reveal_code` tool: load a file into the user's editor at a line
    range (UI-only; no read/write side effects beyond validation)."""

    def reveal_code(path: str, start_line: int, end_line: int | None = None) -> str:
        """Open a file in the user's editor, scrolled to and highlighting the
        cited lines. Call when the user asks to SEE where something happens
        ("show me where X is done" / "where is Y handled") — one call per
        location; multiple files mean multiple calls. Lines are 1-based;
        end_line defaults to start_line.

        Args:
            path: Workdir-relative file path (forward slashes).
            start_line: First line to reveal (1-based).
            end_line: Last line to reveal; defaults to start_line.
        """
        target, err = resolve_workdir_path(workdir, path)
        if target is None or err is not None:
            raise ModelRetry(f'reveal_code: {err or "unresolvable path"}')
        if not target.is_file():
            raise ModelRetry(f'reveal_code: {path!r} is not a file in the Workdir')

        start = max(1, start_line)
        if end_line is None:
            end = start
        else:
            # A reversed range is a typo, not a meaningful request — swap it
            # so the reveal lands on the lines either way.
            end = max(1, end_line)
            if end < start:
                start, end = end, start
        rel = target.resolve().relative_to(Path(workdir).resolve())
        return f'revealed {rel.as_posix()}:{start}-{end} in the editor'

    return FunctionToolset([reveal_code])
