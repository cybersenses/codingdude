"""Cross-session Memory: a durable fact bank scoped globally or per Workdir.

No hidden state: entries live in the `memory` table, are keyword+recency
retrieved at Session start, and are inspectable/deletable (UI panel reads
list/delete directly).
"""

from datetime import UTC, datetime

from pydantic_ai.toolsets import FunctionToolset


class MemoryStore:
    def __init__(self, db):
        self._db = db

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
        return ranked[:top_n]


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
