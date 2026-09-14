"""R15: research pipeline — save_research tool feeding reference/research/."""

from pathlib import Path

import pytest

from codingdude.db import Database
from codingdude.references import ReferenceStore
from codingdude.research import build_research_toolset

DOC = """# Best practices: asyncio task groups

As of: 2025-06-01

## Use TaskGroup for structured concurrency
Prefer asyncio.TaskGroup over gather without return_exceptions.

Sources:
- https://docs.python.org/3/library/asyncio-task.html
"""


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database.connect(tmp_path / 'home')


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    wd = tmp_path / 'proj'
    (wd / 'reference').mkdir(parents=True)
    return wd


def save_fn(workdir: Path):
    toolset = build_research_toolset(workdir)
    (t,) = list(toolset.tools.values())
    return t.function


def test_save_research_writes_reference_research(db, workdir):
    fn = save_fn(workdir)
    result = fn('asyncio task groups', DOC)
    path = workdir / 'reference' / 'research' / 'asyncio-task-groups.md'
    assert path.exists()
    assert 'As of: 2025-06-01' in path.read_text(encoding='utf-8')
    assert 'reference/research/asyncio-task-groups.md' in result


def test_saved_doc_is_searchable(db, workdir):
    fn = save_fn(workdir)
    fn('asyncio task groups', DOC)
    store = ReferenceStore(db, workdir)
    store.reindex()
    hits = store.search('TaskGroup')
    assert hits and 'asyncio-task-groups.md' in hits[0]


@pytest.mark.parametrize('bad', [
    DOC.replace('As of: 2025-06-01\n', ''),
    DOC.replace('- https://docs.python.org/3/library/asyncio-task.html\n', ''),
])
def test_save_research_requires_stamp_and_sources(db, workdir, bad):
    fn = save_fn(workdir)
    with pytest.raises(ValueError, match='As of|source'):
        fn('asyncio task groups', bad)
    assert not (workdir / 'reference' / 'research').exists() or not any(
        (workdir / 'reference' / 'research').iterdir()
    )


def test_save_research_slugifies_topic(db, workdir):
    fn = save_fn(workdir)
    fn('Best Practices: RAG / Retrieval (v2)?', DOC)
    path = workdir / 'reference' / 'research' / 'best-practices-rag-retrieval-v2.md'
    assert path.exists()


def test_save_research_refuses_clobber(db, workdir):
    fn = save_fn(workdir)
    fn('asyncio task groups', DOC)
    with pytest.raises(ValueError, match='exists'):
        fn('asyncio task groups', DOC + '\nextra\n')


def test_save_research_replace_overwrites(db, workdir):
    fn = save_fn(workdir)
    fn('asyncio task groups', DOC)
    fn('asyncio task groups', DOC + '\n## Updated section\nNew guidance.\n', replace=True)
    text = (workdir / 'reference' / 'research' / 'asyncio-task-groups.md').read_text(
        encoding='utf-8'
    )
    assert 'Updated section' in text
