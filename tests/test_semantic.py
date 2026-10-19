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
"""Engine seam: embeddings — semantic memory retrieval and semantic code search.

The embedder is injectable: tests use a deterministic fake so no provider or
model download is needed.
"""


import pytest
from helpers import scripted
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine
from codingdude.memory import MemoryStore
from codingdude.semantic import FakeEmbedder, SemanticIndex


@pytest.fixture
def engine_ready(home):
    """Engine with the offline FakeEmbedder wired in."""
    engine = make_engine(home, FakeEmbedder(dimension=64))
    return engine, MemoryStore(engine._db)


def make_engine(home, embedder=None):
    return Engine(
        config=load_config(), db=Database.connect(home), embedder=embedder
    )


def test_fake_embedder_is_deterministic():
    e = FakeEmbedder(dimension=8)
    v1 = e.embed('banana apple')
    v2 = e.embed('banana apple')
    v3 = e.embed('zebra')
    assert v1 == v2
    assert v1 != v3


async def test_semantic_memory_retrieval_finds_synonyms(engine_ready, workdir):
    engine, store = engine_ready
    store.add('the project refuses to use tabs; indentation is spaces only', scope='workdir', workdir=str(workdir))
    store.add('user likes coffee', scope='global')

    hits = store.retrieve_semantic(engine.embedder, str(workdir), query='whitespace policy for indentation', top_n=2)
    contents = [c for c, _ in hits]
    assert 'spaces only' in contents[0]


def test_reference_dir_is_excluded_from_code_index(engine_ready, workdir):
    """Scaffold-seeded checklists must not crowd code out of semantic results."""
    engine, _ = engine_ready
    (workdir / 'reference' / 'checklists').mkdir(parents=True)
    (workdir / 'reference' / 'checklists' / 'backend.md').write_text(
        'retry with backoff delays after a failed operation, retries, backoff\n' * 200
    )
    (workdir / 'retry.py').write_text(
        'def backoff_after_failure(attempt):\n    return min(2 ** attempt, 60)\n'
    )

    index = SemanticIndex(engine.embedder, engine._db)
    index.index_workdir(workdir)
    hits = index.search('delays after a failed operation', workdir)
    paths = [p for p, _ in hits]
    assert paths, 'code files should still be indexed'
    assert all(not p.startswith('reference/') for p in paths)
    assert 'retry.py' in paths, f'code crowded out of semantic results: {paths}'


async def test_semantic_code_search_tool_finds_concept(engine_ready, workdir):
    engine, _ = engine_ready
    (workdir / 'retry.py').write_text(
        'def backoff_after_failure(attempt):\n    return min(2 ** attempt, 60)\n'
    )
    (workdir / 'greet.py').write_text('def greet(name):\n    return f"hi {name}"\n')

    def searcher(messages, info):
        if not any(
            p.part_kind == 'tool-call' for m in messages for p in m.parts
        ):
            from pydantic_ai.messages import ToolCallPart

            return ModelResponse(
                parts=[ToolCallPart(
                    tool_name='semantic_search',
                    args={'query': 'delays after a failed operation'},
                )]
            )
        from pydantic_ai.messages import ToolReturnPart

        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        return ModelResponse(
            parts=[TextPart(content='found:' + ('retry.py' if any('retry.py' in r for r in returns) else 'nothing'))]
        )

    outcome = await engine.run(
        prompt='semantic lookup', workdir=workdir, model=scripted(searcher)
    )
    assert outcome.output == 'found:retry.py'


async def test_index_is_cached_by_content_hash(engine_ready, workdir):
    engine, _ = engine_ready
    index = SemanticIndex(engine.embedder, engine._db)
    (workdir / 'a.py').write_text('x = 1\n')
    index.index_workdir(workdir)
    first = engine._db._conn.execute('SELECT COUNT(*) c FROM embeddings').fetchone()['c']
    # Re-index with no changes: row count unchanged (cache hit).
    index.index_workdir(workdir)
    second = engine._db._conn.execute('SELECT COUNT(*) c FROM embeddings').fetchone()['c']
    assert second == first

    # Changed content updates in place rather than duplicating.
    (workdir / 'a.py').write_text('x = 2\n')
    index.index_workdir(workdir)
    third = engine._db._conn.execute('SELECT COUNT(*) c FROM embeddings').fetchone()['c']
    assert third == first
    row = engine._db._conn.execute(
        "SELECT content_hash FROM embeddings WHERE path = 'a.py'"
    ).fetchone()
    import hashlib

    expected = hashlib.sha256(b'x = 2\n').hexdigest()
    assert row['content_hash'] == expected
