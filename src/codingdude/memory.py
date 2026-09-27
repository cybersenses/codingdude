"""Cross-session Memory: a durable fact bank scoped globally or per Workdir.

No hidden state: entries live in the `memory` table, are keyword+recency
retrieved at Session start, and are inspectable/deletable (UI panel reads
list/delete directly).
"""

import re

from pydantic_ai.toolsets import FunctionToolset

from .db import utc_now_iso as _now

_DUPLICATE_JACCARD = 0.8


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r'[a-z0-9]+', text.lower()))


def _similar(a: frozenset[str], b: frozenset[str]) -> bool:
    """Near-duplicate detection: paraphrases of the same fact share most tokens."""
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a & b) / len(a | b) >= _DUPLICATE_JACCARD


class MemoryStore:
    """SQLite-backed persistent memory (global and per-workdir scopes)."""
    def __init__(self, db):
        self._db = db

    def duplicate_ids(self, content: str) -> list[int]:
        """Ids of existing entries that duplicate `content` (paraphrase-tolerant)."""
        tokens = _tokens(content)
        return [r['id'] for r in self.all_entries() if _similar(tokens, _tokens(r['content']))]

    def add(self, content: str, scope: str = 'global', workdir: str | None = None) -> int:
        cur = self._db._conn.execute(
            'INSERT INTO memory (scope, workdir, content, created_at) VALUES (?, ?, ?, ?)',
            (scope, workdir if scope == 'workdir' else None, content.strip(), _now()),
        )
        self._db._conn.commit()
        return cur.lastrowid

    def delete_substring(self, substring: str) -> int:
        cur = self._db._conn.execute(
            'DELETE FROM memory WHERE content LIKE ?', (f'%{substring}%',)
        )
        self._db._conn.commit()
        return cur.rowcount

    def delete_id(self, entry_id: int) -> int:
        cur = self._db._conn.execute('DELETE FROM memory WHERE id = ?', (entry_id,))
        self._db._conn.commit()
        return cur.rowcount

    def all_entries(self) -> list[dict]:
        rows = self._db._conn.execute(
            'SELECT id, scope, workdir, content, created_at FROM memory ORDER BY created_at DESC'
        ).fetchall()
        return [dict(r) for r in rows]

    def retrieve(self, workdir: str | None, query: str, top_n: int = 10) -> list[dict]:
        """Top-N by keyword hits, recency as tiebreaker; scope = global + this Workdir."""
        rows = self._db._conn.execute(
            'SELECT id, scope, workdir, content, created_at FROM memory'
            " WHERE scope = 'global' OR workdir = ?",
            (workdir,),
        ).fetchall()
        terms = [t.lower() for t in query.split() if len(t) > 2]

        def score(row) -> tuple[int, str]:
            content = row['content'].lower()
            hits = sum(1 for t in terms if t in content)
            return (hits, row['created_at'])

        ranked = sorted(rows, key=score, reverse=True)
        best_hits = score(ranked[0])[0] if ranked else 0
        if best_hits > 0:
            ranked = [row for row in ranked if score(row)[0] > 0]
        return ranked[:top_n]

    def retrieve_semantic(self, embedder, workdir: str | None, query: str, top_n: int = 10) -> list[tuple[str, float]]:
        """Entries ranked by embedding similarity (scope = global + this Workdir)."""
        from .semantic import cosine

        rows = self._db._conn.execute(
            'SELECT content FROM memory'
            " WHERE scope = 'global' OR workdir = ?",
            (workdir,),
        ).fetchall()
        qv = embedder.embed(query)
        scored = [(r['content'], cosine(qv, embedder.embed(r['content']))) for r in rows]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]


def build_memory_toolset(store: MemoryStore, workdir: str) -> FunctionToolset:
    """remember/forget tools — deliberate Memory banking by the agent."""

    def remember(content: str, scope: str = 'workdir') -> str:
        if scope not in ('global', 'workdir'):
            return "scope must be 'global' or 'workdir'"
        store.add(content, scope=scope, workdir=workdir)
        return f'remembered ({scope}): {content}'

    def forget(content_substring: str) -> str:
        deleted = store.delete_substring(content_substring)
        return f'forgot {deleted} entr{"y" if deleted == 1 else "ies"}'

    return FunctionToolset([remember, forget])
