"""Embeddings: semantic memory retrieval and semantic code search.

The embedder is injectable (anything with `.embed(text) -> list[float]`).
`FakeEmbedder` (deterministic, offline) is for tests; production uses a
provider-backed embedder when one is configured. Vectors live in the
`embeddings` table, cached by content hash so unchanged files re-embed never.
"""

import hashlib
import json
import math
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .tools import SKIP_DIRS

EMBED_EXTENSIONS = {'.py', '.md', '.txt', '.toml', '.json', '.js', '.ts', '.jsx', '.tsx'}
MAX_FILE_CHARS = 20_000


class FakeEmbedder:
    """Deterministic offline embedder: character-trigram hashing.

    Similar texts share trigrams, so cosine similarity clusters them — good
    enough to prove the retrieval pipeline without a model download.
    """

    def __init__(self, dimension: int = 64):
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        text = text.lower()
        for i in range(len(text) - 2):
            gram = text[i:i + 3]
            h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
            vec[h % self.dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False))


class SemanticIndex:
    """Content-hash-cached vector index over Workdir files, in SQLite."""

    def __init__(self, embedder, db):
        self.embedder = embedder
        self.db = db

    def index_workdir(self, workdir: Path) -> int:
        """Embed new/changed files; returns number of indexed files."""
        count = 0
        for f in sorted(workdir.rglob('*')):
            if not f.is_file() or f.suffix not in EMBED_EXTENSIONS:
                continue
            if any(part in SKIP_DIRS for part in f.relative_to(workdir).parts):
                continue
            content = f.read_text(encoding='utf-8', errors='replace')[:MAX_FILE_CHARS]
            digest = hashlib.sha256(content.encode()).hexdigest()
            rel = str(f.relative_to(workdir)).replace('\\', '/')
            row = self.db._conn.execute(
                'SELECT content_hash FROM embeddings WHERE path = ?', (rel,)
            ).fetchone()
            if row and row['content_hash'] == digest:
                continue
            vector = json.dumps(self.embedder.embed(content))
            self.db._conn.execute(
                'INSERT INTO embeddings (path, content_hash, vector) VALUES (?, ?, ?)'
                ' ON CONFLICT(path) DO UPDATE SET content_hash=excluded.content_hash,'
                ' vector=excluded.vector',
                (rel, digest, vector),
            )
            count += 1
        self.db._conn.commit()
        return count

    def search(self, query: str, workdir: Path, top_n: int = 5) -> list[tuple[str, float]]:
        qv = self.embedder.embed(query)
        rows = self.db._conn.execute('SELECT path, vector FROM embeddings').fetchall()
        scored = [
            (r['path'], cosine(qv, json.loads(r['vector'])))
            for r in rows
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]


def build_semantic_toolset(workdir: Path, index: SemanticIndex) -> FunctionToolset:
    """The `semantic_search` tool: concept-level lookup that grep can't do."""

    def semantic_search(query: str) -> str:
        index.index_workdir(workdir)
        hits = index.search(query, workdir)
        if not hits:
            return '(nothing indexed yet)'
        return '\n'.join(f'{path} (score {score:.2f})' for path, score in hits)

    return FunctionToolset([semantic_search])
