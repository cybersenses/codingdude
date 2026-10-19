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
"""R19 #31: default project scaffold. Fresh workdirs get the base
infrastructure (reference/, ROADMAP.md, CONTEXT.md) so a new project
starts with the guidance surfaces the process depends on.

Idempotent: existing files are never touched. Best-effort: failures are
reported in the result, never raised — scaffolding must not block a run.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ROADMAP_TEMPLATE = """\
# Roadmap

Planning umbrellas (R<n>). Tickets are units of work under an umbrella;
a ticket may not exist without a roadmap item.
"""

_CONTEXT_TEMPLATE = """\
# Context

Domain vocabulary and architecture notes for this project. Update as
the codebase evolves — the agent reads this before every run.
"""

_HANDOFF_TEMPLATE = """\
# HANDOFF.md

Continuity notes between agent sessions on this project. At each handoff,
replace stale content with the current state: what shipped (commit), what
is in progress, environment facts, and next steps. Keep it concise and
free of personal data (no user paths, keys, or private hostnames).
"""


def _bundled_checklists() -> list[tuple[str, str]]:
    """(filename, content) for the distilled checklists shipped with the package."""
    import importlib.resources

    root = importlib.resources.files('codingdude') / 'data' / 'checklists'
    out: list[tuple[str, str]] = []
    try:
        for res in sorted(root.iterdir(), key=lambda r: r.name):
            if res.name.endswith('.md'):
                out.append((res.name, res.read_text(encoding='utf-8')))
    except OSError as exc:
        # The contract is "scaffold never raises" — a missing wheel payload
        # must surface as an error entry, not break project creation.
        logger.warning('bundled checklists unavailable: %s', exc)
    return out


def ensure_project_scaffold(workdir: Path) -> dict:
    """Create any missing base infrastructure in `workdir`.

    Includes seeding `reference/checklists/` with the distilled checklists
    (per-file idempotent: existing files are never overwritten).

    Returns {'created': [names], 'errors': [messages]}.
    """
    created: list[str] = []
    errors: list[str] = []
    workdir = Path(workdir)

    def _want(name: str, write) -> None:
        target = workdir / name
        try:
            if target.exists():
                return
            write(target)
            created.append(name)
        except OSError as exc:
            errors.append(f'{name}: {exc}')
            logger.warning('scaffold could not create %s: %s', target, exc)

    _want('reference', lambda p: p.mkdir(parents=True))
    _want('reference/research', lambda p: p.mkdir(parents=True))
    _want('ROADMAP.md', lambda p: p.write_text(_ROADMAP_TEMPLATE, encoding='utf-8'))
    _want('CONTEXT.md', lambda p: p.write_text(_CONTEXT_TEMPLATE, encoding='utf-8'))
    _want('HANDOFF.md', lambda p: p.write_text(_HANDOFF_TEMPLATE, encoding='utf-8'))

    for name, content in _bundled_checklists():
        _want(
            f'reference/checklists/{name}',
            lambda p, _c=content: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(_c, encoding='utf-8')),
        )
    return {'created': created, 'errors': errors}
