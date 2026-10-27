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
"""Executed kickoff prompts (R71 #263): a session's first turn is prefixed
with an orientation block, so the development pipeline is re-anchored by
action instead of living only in passive instructions.

Two modes: 'existing' (takeover of a codebase — read the continuity
surfaces, re-anchor the contract) and 'new' (greenfield — interview the
user via ask_user before scaffolding). Mode comes from a bounded workdir
scan; text comes from the project's .codingdude.toml [kickoff] override or
the bundled versioned prompt. Best-effort: a failure warns and skips the
kickoff for that run — orientation must never block work (scaffold
contract).
"""
from __future__ import annotations

import logging
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

# Workdir entries that mean "a project already lives here" (R71 #263).
_PROJECT_MARKERS = (
    '.git', 'pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod',
    'requirements.txt', 'setup.py', 'setup.cfg', 'pom.xml', 'build.gradle',
    'build.gradle.kts', 'Gemfile', 'composer.json', 'mix.exs', 'pubspec.yaml',
)
_SOURCE_SUFFIXES = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.go', '.rs',
    '.java', '.cs', '.php', '.rb', '.kt', '.swift', '.c', '.cpp', '.cc',
    '.h', '.hpp', '.vue', '.svelte',
}


def kickoff_mode(workdir: Path) -> str:
    """'new' while the workdir shows no project markers or source files.

    The scan covers the top two levels: a greenfield dir is empty (or holds
    just the codingdude scaffold, which produces none of these), while any
    real project has a marker file or source at its root or inside one
    top-level package dir. Deterministic and cheap — it runs on every
    session's first turn.
    """
    workdir = Path(workdir)
    try:
        for entry in workdir.iterdir():
            if entry.name in _PROJECT_MARKERS:
                return 'existing'
            if entry.is_file() and entry.suffix.lower() in _SOURCE_SUFFIXES:
                return 'existing'
            if entry.is_dir() and entry.name != 'reference':
                for sub in entry.iterdir():
                    if sub.is_file() and sub.suffix.lower() in _SOURCE_SUFFIXES:
                        return 'existing'
    except OSError as exc:
        # Unreadable workdir: assume takeover, not a blank slate — an
        # interview kickoff on an existing project is noise; the reverse
        # (orientation skipped) would silently lose the contract re-anchor.
        logger.warning('kickoff mode scan failed: %s', exc)
        return 'existing'
    return 'new'


def kickoff_block(workdir: Path) -> tuple[str, str]:
    """(mode, kickoff text) for this workdir's first turn; ('', '') to skip.

    Text resolution: the .codingdude.toml `[kickoff]` existing/new override
    wins over the bundled versioned prompt. Best-effort: any failure warns
    and returns ('', '') so the run proceeds without the block.
    """
    try:
        mode = kickoff_mode(workdir)
        from .config import load_project_config
        from .prompts import load_prompt

        override = load_project_config(workdir).get('kickoff', {}).get(mode)
        if isinstance(override, str) and override.strip():
            return mode, override.strip()
        return mode, load_prompt(f'kickoff-{mode}')
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning('kickoff unavailable (%s); skipping it for this run', exc)
        return '', ''


def compose_first_prompt(prompt: str, kickoff: str) -> str:
    """The first-turn prompt: kickoff first, separator, then the user's
    own words verbatim (composed before build_run_prompt so image
    attachment is unaffected)."""
    return kickoff + KICKOFF_SEPARATOR + prompt


KICKOFF_SEPARATOR = '\n\n---\n\n'
_KICKOFF_HEADER = '## Kickoff ('


def split_kickoff(text: str) -> str:
    """The user's own words from a composed first-turn prompt; unchanged
    when the text carries no kickoff.

    The UI boundary uses this (GET /sessions/{id}/messages) so a refreshed
    chat shows what the user actually typed, while stored history stays
    faithful to what the model saw. Guard: only a real kickoff header
    followed by the separator is stripped — a user message that merely
    contains '---' passes through untouched.
    """
    if not text.startswith(_KICKOFF_HEADER):
        return text
    _head, sep, rest = text.partition(KICKOFF_SEPARATOR)
    return rest if sep else text
