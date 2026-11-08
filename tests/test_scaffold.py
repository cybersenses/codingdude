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
"""R19 #31: default project scaffold — fresh workdirs get the base
infrastructure (reference/, ROADMAP.md, CONTEXT.md) without the agent
having to guess or recreate it."""

from pathlib import Path

from codingdude.scaffold import ensure_project_scaffold


def test_creates_missing_pieces_in_empty_workdir(tmp_path: Path) -> None:
    out = ensure_project_scaffold(tmp_path)
    assert (tmp_path / 'reference').is_dir()
    assert (tmp_path / 'reference' / 'research').is_dir()
    assert (tmp_path / 'ROADMAP.md').exists()
    assert (tmp_path / 'CONTEXT.md').exists()
    assert (tmp_path / 'HANDOFF.md').exists()
    checklist_creates = [c for c in out['created'] if c.startswith('reference/checklists/')]
    assert set(out['created']) - set(checklist_creates) == {
        'reference', 'reference/research', 'ROADMAP.md', 'CONTEXT.md', 'HANDOFF.md'}
    assert out['created']  # something happened


def test_idempotent_when_everything_exists(tmp_path: Path) -> None:
    (tmp_path / 'reference').mkdir()
    (tmp_path / 'reference' / 'research').mkdir()
    (tmp_path / 'ROADMAP.md').write_text('# Roadmap\n\n## R1 — Existing\n', encoding='utf-8')
    (tmp_path / 'CONTEXT.md').write_text('# Context\n', encoding='utf-8')
    (tmp_path / 'HANDOFF.md').write_text('# Handoff\n', encoding='utf-8')
    out = ensure_project_scaffold(tmp_path)
    # base pieces skipped; only checklists may be seeded
    assert [c for c in out['created'] if not c.startswith('reference/checklists/')] == []
    assert (tmp_path / 'ROADMAP.md').read_text(encoding='utf-8') == '# Roadmap\n\n## R1 — Existing\n'


def test_creates_only_the_missing_pieces(tmp_path: Path) -> None:
    (tmp_path / 'CONTEXT.md').write_text('# Context\n', encoding='utf-8')
    out = ensure_project_scaffold(tmp_path)
    base = [c for c in out['created'] if not c.startswith('reference/checklists/')]
    assert set(base) == {'reference', 'reference/research', 'ROADMAP.md', 'HANDOFF.md'}
    assert (tmp_path / 'CONTEXT.md').read_text(encoding='utf-8') == '# Context\n'
    assert (tmp_path / 'reference' / 'checklists' / 'qa-testing.md').exists()  # checklists still seeded


def test_roadmap_template_is_parseable() -> None:
    import tempfile

    from codingdude.roadmap import parse_roadmap_md

    with tempfile.TemporaryDirectory() as d:
        ensure_project_scaffold(Path(d))
        items = parse_roadmap_md(Path(d) / 'ROADMAP.md')
    assert items == []  # valid header, zero items


def test_never_raises_on_unwritable_workdir(tmp_path: Path) -> None:
    # a FILE used as a parent dir: mkdir can never succeed here
    blocked = tmp_path / 'blocker'
    blocked.write_text('x', encoding='utf-8')
    out = ensure_project_scaffold(blocked / 'sub')
    assert out['created'] == []
    assert out['errors']  # failure reported, not raised


def test_seeds_checklists_into_new_project(tmp_path: Path) -> None:
    out = ensure_project_scaffold(tmp_path)
    ck = tmp_path / 'reference' / 'checklists'
    seeded = sorted(p.name for p in ck.glob('*.md'))
    assert len(seeded) >= 20  # the full distilled set
    assert 'api-design.md' in seeded
    assert all(f'reference/checklists/{n}' in out['created'] for n in seeded)


def test_checklist_seed_never_clobbers_existing(tmp_path: Path) -> None:
    ck = tmp_path / 'reference' / 'checklists'
    ck.mkdir(parents=True)
    (ck / 'api-design.md').write_text('# my custom checklist\n', encoding='utf-8')
    ensure_project_scaffold(tmp_path)
    assert (ck / 'api-design.md').read_text(encoding='utf-8') == '# my custom checklist\n'


# --- #295 (DE-5): operator files (AGENT_STOP / STEER.md) are gitignored.

def _git(workdir, *args):
    import shutil
    import subprocess  # nosec B404 - test fixture spawns git only, argv list

    git = shutil.which('git') or 'git'
    return subprocess.run(
        [git, *args], cwd=workdir, capture_output=True, text=True,
    )  # nosec B603 - test fixture, fixed argv list, no shell


def test_operator_files_gitignored_in_git_repo(tmp_path: Path) -> None:
    """A repo workdir gets the entries in .git/info/exclude — never touching
    tracked files, so both operator names are untracked-ignored."""
    _git(tmp_path, 'init', '-q')
    (tmp_path / 'AGENT_STOP').write_text('', encoding='utf-8')
    (tmp_path / 'STEER.md').write_text('steer', encoding='utf-8')
    ensure_project_scaffold(tmp_path)
    for name in ('AGENT_STOP', 'STEER.md'):
        probe = _git(tmp_path, 'check-ignore', '-q', name)
        assert probe.returncode == 0, f'{name} not gitignored'


def test_operator_files_gitignored_without_git(tmp_path: Path) -> None:
    """A non-repo workdir gets a fresh .gitignore carrying both names."""
    ensure_project_scaffold(tmp_path)
    text = (tmp_path / '.gitignore').read_text(encoding='utf-8')
    assert 'AGENT_STOP' in text and 'STEER.md' in text


def test_existing_gitignore_is_never_modified(tmp_path: Path) -> None:
    """Scaffold never touches existing files: a pre-existing .gitignore is
    left byte-for-byte alone (the operator can add the names themselves)."""
    original = 'node_modules/\ndist/\n'
    (tmp_path / '.gitignore').write_text(original, encoding='utf-8')
    ensure_project_scaffold(tmp_path)
    assert (tmp_path / '.gitignore').read_text(encoding='utf-8') == original

