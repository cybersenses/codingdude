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
"""Seed registry integrity: shipped skills must not reference absent skills.

The #319/#322 bug class: a shipped SKILL.md tells the agent to load a skill
that the seed never ships (a dangling reference the agent can only discover
at load time). These tests keep the seed's internal reference graph closed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[1] / '.codingdude-seed'

_SS_TOKEN = re.compile(r'`+(ss-[a-z0-9]+(?:-[a-z0-9]+)*)`+')
_MD_LINK = re.compile(r'\]\(([^)\s]+\.md)(#[^)\s]*)?\)')

# Recipe-generated CSS helper classes, not skills. They share the ss- prefix
# with the skill family; a new legitimate helper class goes here with a note.
HELPER_CLASSES = frozenset({
    'ss-pattern-surface',  # card/pattern containment surface (recipes.css)
    'ss-pattern-inset',  # inner padding helper (recipes.css)
    'ss-pattern-control',  # control radius helper (recipes.css)
    'ss-pattern-icon',  # icon radius helper (recipes.css)
    'ss-pattern-stack',  # pattern vertical rhythm helper (recipes.css)
    'ss-page-gutter',  # page gutter helper (recipes.css)
    'ss-page-padding',  # page padding helper (recipes.css)
})

# Skills the registry deliberately does not ship. They must stay nameable in
# routing prose ("not installed — route elsewhere"), so the token is allowed
# to dangle by design; each entry documents why.
DELIBERATE_ABSENCES = frozenset({
    'ss-learn',  # upstream separately-installed learning-capture skill; styleseed router reports absence and routes elsewhere
})


def _skill_dirs() -> dict[str, Path]:
    root = SEED / 'skills'
    if not root.is_dir():
        pytest.skip('seed bundle not present')
    return {p.parent.name: p.parent for p in root.glob('*/SKILL.md')}


def test_ss_skill_references_resolve() -> None:
    """Every backticked ss-* name in a shipped SKILL.md is a shipped skill."""
    dirs = _skill_dirs()
    dangling: list[str] = []
    for name, skill_dir in sorted(dirs.items()):
        body = (skill_dir / 'SKILL.md').read_text(encoding='utf-8')
        for token in _SS_TOKEN.findall(body):
            if token not in dirs and token not in HELPER_CLASSES and token not in DELIBERATE_ABSENCES:
                dangling.append(f'{name}: {token}')
    assert not dangling, f'ss-* references with no shipped skill dir: {dangling}'


def test_relative_markdown_links_resolve() -> None:
    """Every relative .md link in a shipped SKILL.md resolves to a real file."""
    dirs = _skill_dirs()
    broken: list[str] = []
    for name, skill_dir in sorted(dirs.items()):
        body = (skill_dir / 'SKILL.md').read_text(encoding='utf-8')
        for match in _MD_LINK.finditer(body):
            link = match.group(1)
            if '://' in link or link.startswith('/'):
                continue
            if not (skill_dir / link).is_file():
                broken.append(f'{name}: {link}')
    assert not broken, f'relative links with no target file: {broken}'
