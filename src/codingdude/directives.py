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
"""Directives: the always-on rule layers injected into every run.

Two sources, later layers win on conflict:
1. Global: `~/.codingdude/DIRECTIVES.md` — user-level taste (languages,
   test policy, style rules).
2. Project: `<workdir>/AGENT.md` — already the Project Context; included here
   as the project directive layer.
3. Built-in: standing process rules shipped with the engine (tracked-item
   obligation) — always present; user files only add to it.

Budget-capped: the global layer truncates first so project rules always
survive. Truncation is always marked, never silent.
"""

from pathlib import Path

DIRECTIVES_FILENAME = 'DIRECTIVES.md'
DIRECTIVES_BUDGET = 4000
_GLOBAL_BUDGET = 3000

_BUILTIN_PROCESS = """\
- Before non-trivial work, open (or confirm) the tracked item for it in the
  surface this project declares for tracking — see the project's convention
  record in Memory; default: a ROADMAP.md ticket — and log completion
  against it when the work is done."""


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace').strip() if path.exists() else ''


def build_directive_layers(home: Path, workdir: Path) -> str:
    """Compose the directive text for a run (empty string when none exist)."""
    parts: list[str] = []

    global_text = _read(home / DIRECTIVES_FILENAME)
    if global_text:
        if len(global_text) > _GLOBAL_BUDGET:
            global_text = global_text[:_GLOBAL_BUDGET]
        parts.append(f'## Global directives (user-level rules)\n\n{global_text}')

    # Built-in sits between global and project: later layers win on conflict,
    # so user-level and project rules always outrank engine defaults.
    parts.append(f'## Built-in process rules\n\n{_BUILTIN_PROCESS}')

    project_text = _read(workdir / 'AGENT.md')
    if project_text:
        parts.append(f'## Project directives\n\n{project_text}')

    if not parts:
        return ''
    text = '\n\n'.join(parts)
    if len(text) > DIRECTIVES_BUDGET:
        text = text[:DIRECTIVES_BUDGET] + '\n[directives truncated]'
    return text


def project_directives_guard(path: str) -> bool:
    """True when the path is a directives file (gated like AGENT.md)."""
    return Path(path).name.upper() in ('AGENT.MD', DIRECTIVES_FILENAME.upper())
