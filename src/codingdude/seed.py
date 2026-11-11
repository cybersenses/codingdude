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
"""Seed a fresh CodingDude config home from the bundled `.codingdude-seed`.

DIST-README promises that first setup installs skills and DIRECTIVES.md into
`~/.codingdude`. The seed template ships with the distro (repo root /
`.codingdude-seed`); seeding only fills gaps — it never overwrites an
existing file or directory, since the config home is user-owned.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def _seed_dir() -> Path | None:
    """Locate the bundled seed template (env override, then repo root)."""
    override = os.environ.get('CODINGDUDE_SEED')
    if override:
        path = Path(override)
        return path if path.is_dir() else None
    # src/codingdude/seed.py -> repo root
    path = Path(__file__).resolve().parents[2] / '.codingdude-seed'
    return path if path.is_dir() else None


def _backfill_children(src: Path, dst: Path) -> bool:
    """Copy each missing top-level child of `src` into `dst`.

    Per-item granularity: a user-owned `home/skills` still gains seed skills
    it lacks, while skills the user already has (possibly edited) are never
    overwritten. Children that already exist gain files they are missing
    (per-file add-missing), so new companions shipped inside an existing
    skill still reach the user. Returns True when anything was copied.
    """
    copied = False
    for child in sorted(src.iterdir()):
        target = dst / child.name
        if target.exists():
            if child.is_dir() and target.is_dir() and _backfill_files(child, target):
                copied = True
            continue
        dst.mkdir(parents=True, exist_ok=True)
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
        copied = True
    return copied


def _backfill_files(src: Path, dst: Path) -> bool:
    """Copy files present under `src` but missing in `dst`, recursively.

    Add-missing only: a file the user already has (possibly edited) is never
    overwritten; a file/dir the user lacks is created from the seed.
    """
    copied = False
    for child in sorted(src.iterdir()):
        target = dst / child.name
        if child.is_dir():
            if _backfill_files(child, target):
                copied = True
            continue
        if target.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)
        copied = True
    return copied


def seed_config_home(home: Path) -> dict[str, str]:
    """Copy missing seed items into `home`. Returns what was seeded.

    Existing files/dirs are left untouched (never overwrite user-owned data).
    Skills and tools are backfilled per item, so entries added to the seed
    after a user's first setup still reach existing config homes.
    """
    seed = _seed_dir()
    if seed is None:
        return {}
    seeded: dict[str, str] = {}
    skills_src = seed / 'skills'
    if skills_src.is_dir() and _backfill_children(skills_src, home / 'skills'):
        seeded['skills'] = str(home / 'skills')
    directives_src = seed / 'DIRECTIVES.md'
    if directives_src.is_file() and not (home / 'DIRECTIVES.md').exists():
        home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(directives_src, home / 'DIRECTIVES.md')
        seeded['DIRECTIVES.md'] = str(home / 'DIRECTIVES.md')
    tools_src = seed / 'tools'
    if tools_src.is_dir() and _backfill_children(tools_src, home / 'tools'):
        seeded['tools'] = str(home / 'tools')
    if seeded:
        logger.info('seeded config home from %s: %s', seed, sorted(seeded))
    return seeded
