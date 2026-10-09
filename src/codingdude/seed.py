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


def seed_config_home(home: Path) -> dict[str, str]:
    """Copy missing seed items into `home`. Returns what was seeded.

    Existing files/dirs are left untouched (never overwrite user-owned data).
    """
    seed = _seed_dir()
    if seed is None:
        return {}
    seeded: dict[str, str] = {}
    skills_src = seed / 'skills'
    if skills_src.is_dir() and not (home / 'skills').exists():
        home.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skills_src, home / 'skills')
        seeded['skills'] = str(home / 'skills')
    directives_src = seed / 'DIRECTIVES.md'
    if directives_src.is_file() and not (home / 'DIRECTIVES.md').exists():
        home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(directives_src, home / 'DIRECTIVES.md')
        seeded['DIRECTIVES.md'] = str(home / 'DIRECTIVES.md')
    tools_src = seed / 'tools'
    if tools_src.is_dir() and not (home / 'tools').exists():
        home.mkdir(parents=True, exist_ok=True)
        shutil.copytree(tools_src, home / 'tools')
        seeded['tools'] = str(home / 'tools')
    if seeded:
        logger.info('seeded config home from %s: %s', seed, sorted(seeded))
    return seeded
