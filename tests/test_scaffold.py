"""R19 #31: default project scaffold — fresh workdirs get the base
infrastructure (reference/, ROADMAP.md, CONTEXT.md) without the agent
having to guess or recreate it."""

from pathlib import Path

from codingdude.scaffold import ensure_project_scaffold


def test_creates_missing_pieces_in_empty_workdir(tmp_path: Path) -> None:
    out = ensure_project_scaffold(tmp_path)
    assert (tmp_path / 'reference').is_dir()
    assert (tmp_path / 'ROADMAP.md').exists()
    assert (tmp_path / 'CONTEXT.md').exists()
    assert set(out['created']) == {'reference', 'ROADMAP.md', 'CONTEXT.md'}
    assert out['created']  # something happened


def test_idempotent_when_everything_exists(tmp_path: Path) -> None:
    (tmp_path / 'reference').mkdir()
    (tmp_path / 'ROADMAP.md').write_text('# Roadmap\n\n## R1 — Existing\n', encoding='utf-8')
    (tmp_path / 'CONTEXT.md').write_text('# Context\n', encoding='utf-8')
    out = ensure_project_scaffold(tmp_path)
    assert out['created'] == []
    assert (tmp_path / 'ROADMAP.md').read_text(encoding='utf-8') == '# Roadmap\n\n## R1 — Existing\n'


def test_creates_only_the_missing_pieces(tmp_path: Path) -> None:
    (tmp_path / 'CONTEXT.md').write_text('# Context\n', encoding='utf-8')
    out = ensure_project_scaffold(tmp_path)
    assert set(out['created']) == {'reference', 'ROADMAP.md'}
    assert (tmp_path / 'CONTEXT.md').read_text(encoding='utf-8') == '# Context\n'


def test_roadmap_template_is_parseable() -> None:
    import tempfile

    from codingdude.roadmap import parse_roadmap_md

    with tempfile.TemporaryDirectory() as d:
        ensure_project_scaffold(Path(d))
        items = parse_roadmap_md(Path(d) / 'ROADMAP.md')
    assert items == []  # valid header, zero items


def test_never_raises_on_unwritable_workdir() -> None:
    out = ensure_project_scaffold(Path('Z:\\definitely\\not\\a\\dir'))
    assert out['created'] == []
    assert out['errors']  # failure reported, not raised
