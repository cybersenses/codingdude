"""R11 tracer: per-project reference knowledgebase — store, tools, staleness."""

from pathlib import Path

import pytest

from codingdude.db import Database
from codingdude.references import ReferenceStore, build_references_toolset


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / 'home'


@pytest.fixture
def db(home: Path) -> Database:
    return Database.connect(home)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    wd = tmp_path / 'proj'
    (wd / 'reference' / 'pydantic-ai-main').mkdir(parents=True)
    (wd / 'reference' / 'pydantic-ai-main' / 'agent.md').write_text(
        '# Agent\nIntro paragraph.\n\n## Running an agent\nCall agent.run_sync().\n'
        'It returns the final output.\n\n## Streaming\nUse iter for streaming.\n',
        encoding='utf-8',
    )
    (wd / 'reference' / 'pydantic-notes.md').write_text(
        '<!-- codingdude: version=2.10 -->\n# Pydantic notes\nModels validate on assignment.\n',
        encoding='utf-8',
    )
    return wd


def test_reindex_and_search_find_sections(db, workdir):
    store = ReferenceStore(db, workdir)
    store.reindex()
    hits = store.search('streaming')
    assert hits, 'expected the Streaming section to match'
    assert 'agent.md' in hits[0]
    assert 'Streaming' in hits[0]

    hits = store.search('run_sync')
    assert hits and 'Running an agent' in hits[0]


def test_search_scoped_to_workdir(db, workdir, tmp_path):
    other = tmp_path / 'other'
    (other / 'reference').mkdir(parents=True)
    (other / 'reference' / 'x.md').write_text('# X\nstreaming stuff\n', encoding='utf-8')
    ReferenceStore(db, other).reindex()

    store = ReferenceStore(db, workdir)
    store.reindex()
    assert all('other' not in str(h) for h in store.search('streaming'))


def test_read_reference_section_and_errors(db, workdir):
    store = ReferenceStore(db, workdir)
    store.reindex()
    section = store.read('reference/pydantic-ai-main/agent.md', 'Streaming')
    assert 'iter for streaming' in section

    full = store.read('reference/pydantic-ai-main/agent.md')
    assert 'Running an agent' in full

    with pytest.raises(ValueError, match='not in the reference index'):
        store.read('reference/missing.md')
    with pytest.raises(ValueError, match='no section'):
        store.read('reference/pydantic-ai-main/agent.md', 'Nope')


def test_reindex_is_incremental(db, workdir):
    store = ReferenceStore(db, workdir)
    store.reindex()
    touched = store.reindex()  # nothing changed
    assert touched == 0

    target = workdir / 'reference' / 'pydantic-notes.md'
    target.write_text(
        '<!-- codingdude: version=2.10 -->\n# Pydantic notes\nNow mentions defer.\n',
        encoding='utf-8',
    )
    import os

    os.utime(target, (1_000_000_000, 1_000_000_000))
    assert store.reindex() == 1
    assert 'defer' in store.search('defer')[0]


def test_staleness_against_pyproject_pin(db, workdir):
    (workdir / 'pyproject.toml').write_text(
        '[project]\ndependencies = ["pydantic>=2.11", "httpx>=0.27"]\n',
        encoding='utf-8',
    )
    store = ReferenceStore(db, workdir)
    store.reindex()

    # notes.md declares version=2.10 → stale against pin 2.11
    # agent.md has no version → unknown
    report = store.staleness()
    assert any('pydantic-notes.md' in line and '2.10' in line and 'stale' in line for line in report)
    assert any('agent.md' in line and 'version unknown' in line for line in report)

    store.set_version('reference/pydantic-notes.md', '2.11')
    report = store.staleness()
    assert not any('pydantic-notes.md' in line and 'stale' in line for line in report)


def test_toolset_end_to_end(db, workdir):
    toolset = build_references_toolset(db, workdir)
    tools = toolset.tools
    assert {'search_references', 'read_reference', 'set_reference_version'} <= set(tools)

    # Tool.function is the raw (sync) implementation — call it directly.
    out = tools['search_references'].function('streaming')
    assert 'Streaming' in out
    out = tools['read_reference'].function('reference/pydantic-notes.md')
    assert 'validate on assignment' in out
    out = tools['set_reference_version'].function('reference/pydantic-notes.md', '2.11')
    assert '2.11' in out
