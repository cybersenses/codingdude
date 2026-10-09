"""Tests for first-boot config-home seeding (`.codingdude-seed`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codingdude.seed import seed_config_home


@pytest.fixture()
def seed_src(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    src = tmp_path / 'seed'
    (src / 'skills' / 'tdd').mkdir(parents=True)
    (src / 'skills' / 'tdd' / 'SKILL.md').write_text('# tdd\n', encoding='utf-8')
    (src / 'tools').mkdir()
    (src / 'tools' / 'native_debug.py').write_text('# tool\n', encoding='utf-8')
    (src / 'DIRECTIVES.md').write_text('# directives\n', encoding='utf-8')
    monkeypatch.setenv('CODINGDUDE_SEED', str(src))
    return src


def test_seeds_fresh_home(seed_src: Path, tmp_path: Path) -> None:
    home = tmp_path / 'fresh-home'
    seeded = seed_config_home(home)
    assert set(seeded) == {'skills', 'DIRECTIVES.md', 'tools'}
    assert (home / 'skills' / 'tdd' / 'SKILL.md').read_text(encoding='utf-8') == '# tdd\n'
    assert (home / 'DIRECTIVES.md').read_text(encoding='utf-8') == '# directives\n'


def test_never_overwrites_existing(seed_src: Path, tmp_path: Path) -> None:
    home = tmp_path / 'owned-home'
    (home / 'skills').mkdir(parents=True)
    (home / 'skills' / 'tdd' / 'SKILL.md').parent.mkdir(parents=True)
    (home / 'skills' / 'tdd' / 'SKILL.md').write_text('# mine\n', encoding='utf-8')
    (home / 'DIRECTIVES.md').write_text('# mine\n', encoding='utf-8')
    (home / 'tools').mkdir()
    (home / 'tools' / 'native_debug.py').write_text('# mine\n', encoding='utf-8')
    assert seed_config_home(home) == {}
    assert (home / 'skills' / 'tdd' / 'SKILL.md').read_text(encoding='utf-8') == '# mine\n'


def test_partial_seed_backfills_missing_items(seed_src: Path, tmp_path: Path) -> None:
    """Skills already owned but DIRECTIVES.md missing: only the missing one is copied."""
    home = tmp_path / 'partial-home'
    (home / 'skills' / 'tdd').mkdir(parents=True)
    (home / 'skills' / 'tdd' / 'SKILL.md').write_text('# mine\n', encoding='utf-8')
    seeded = seed_config_home(home)
    assert set(seeded) == {'DIRECTIVES.md'}
    assert (home / 'skills' / 'tdd' / 'SKILL.md').read_text(encoding='utf-8') == '# mine\n'
    assert (home / 'DIRECTIVES.md').read_text(encoding='utf-8') == '# directives\n'


def test_noop_without_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CODINGDUDE_SEED', str(tmp_path / 'missing'))
    assert seed_config_home(tmp_path / 'home') == {}


def test_real_seed_bundle() -> None:
    """The distro's bundled seed has 40+ skills, tools, and DIRECTIVES.md."""
    seed = Path(__file__).resolve().parents[1] / '.codingdude-seed'
    if not seed.is_dir():
        pytest.skip('seed bundle not present')
    assert (seed / 'DIRECTIVES.md').is_file()
    assert (seed / 'tools' / 'native_debug.py').is_file()
    assert len(list((seed / 'skills').iterdir())) >= 40
