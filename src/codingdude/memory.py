"""Cross-session Memory: durable facts plus referential solutions (R49),
scoped globally or per Workdir.

No hidden state: entries live in the `memory` table with a `kind` of 'fact'
or 'solution'; facts are keyword+recency retrieved at Session start,
solutions are force-recalled (top 25) and strictly look-upable. Entries are
inspectable/deletable (UI panel reads list/delete directly).
"""

import re

from pydantic_ai.toolsets import FunctionToolset

from .db import utc_now_iso as _now

_DUPLICATE_JACCARD = 0.8


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r'[a-z0-9]+', text.lower()))


def _similar(a: frozenset[str], b: frozenset[str]) -> bool:
    """Near-duplicate detection: paraphrases share most tokens."""
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a & b) / len(a | b) >= _DUPLICATE_JACCARD


class MemoryStore:
    """SQLite-backed persistent memory (global and per-workdir scopes)."""
    def __init__(self, db):
        self._db = db

    def duplicate_ids(self, content: str, kind: str = 'fact',
                      workdir: str | None = None) -> list[int]:
        """Ids of existing entries of `kind` that duplicate `content`
        (paraphrase-tolerant). Scope-aware: only global entries or entries
        in `workdir` can be duplicates. For solutions only the problem
        section is compared — the Solution half is expected to differ (R49)."""
        tokens = _tokens(content)
        out = []
        for r in self.all_entries():
            if r['kind'] != kind:
                continue
            if r['scope'] != 'global' and r['workdir'] != workdir:
                continue
            text = r['content']
            if kind == 'solution':
                if not text.startswith('Problem: '):
                    continue
                text = text.split('\nSolution:', 1)[0].removeprefix('Problem: ')
            if _similar(tokens, _tokens(text)):
                out.append(r['id'])
        return out

    _KINDS = ('fact', 'solution')

    def add(self, content: str, scope: str = 'global', workdir: str | None = None,
            kind: str = 'fact') -> int:
        if kind not in self._KINDS:
            raise ValueError(f"kind must be one of {self._KINDS}, got {kind!r}")
        cur = self._db._conn.execute(
            'INSERT INTO memory (scope, workdir, content, kind, created_at)'
            ' VALUES (?, ?, ?, ?, ?)',
            (scope, workdir if scope == 'workdir' else None, content.strip(),
             kind, _now()),
        )
        self._db._conn.commit()
        return cur.lastrowid

    def update_content(self, entry_id: int, content: str) -> None:
        """Overwrite one entry's content (solution refinement, R49)."""
        self._db._conn.execute(
            'UPDATE memory SET content = ? WHERE id = ?', (content.strip(), entry_id)
        )
        self._db._conn.commit()

    def solutions(self, workdir: str | None, limit: int = 25) -> list[dict]:
        """kind='solution' entries, global + this Workdir, newest first
        (R49 referential solutions — force-recalled at session start)."""
        rows = self._db._conn.execute(
            'SELECT id, scope, workdir, content, kind, created_at FROM memory'
            " WHERE kind = 'solution' AND (scope = 'global' OR workdir = ?)"
            ' ORDER BY created_at DESC LIMIT ?',
            (workdir, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_substring(self, substring: str, kind: str | None = None) -> int:
        sql = 'DELETE FROM memory WHERE content LIKE ?'
        args: list = [f'%{substring}%']
        if kind is not None:
            sql += ' AND kind = ?'
            args.append(kind)
        cur = self._db._conn.execute(sql, args)
        self._db._conn.commit()
        return cur.rowcount

    def delete_id(self, entry_id: int) -> int:
        cur = self._db._conn.execute('DELETE FROM memory WHERE id = ?', (entry_id,))
        self._db._conn.commit()
        return cur.rowcount

    def all_entries(self) -> list[dict]:
        rows = self._db._conn.execute(
            'SELECT id, scope, workdir, content, kind, created_at FROM memory'
            ' ORDER BY created_at DESC'
        ).fetchall()
        return [dict(r) for r in rows]

    def retrieve(self, workdir: str | None, query: str, top_n: int = 10,
                 kind: str | None = None, require_hit: bool = False) -> list[dict]:
        """Top-N by keyword hits, recency as tiebreaker; scope = global + this
        Workdir. kind=None means all kinds; else filter (R49).

        require_hit=False (session-start recall) surfaces recent entries even
        with zero keyword hits; require_hit=True (lookup_solutions) is strict.
        """
        rows = self._db._conn.execute(
            'SELECT id, scope, workdir, content, kind, created_at FROM memory'
            " WHERE scope = 'global' OR workdir = ?",
            (workdir,),
        ).fetchall()
        if kind is not None:
            rows = [r for r in rows if r['kind'] == kind]
        terms = [t.lower() for t in query.split() if len(t) > 2]
        if not terms and query.strip():
            # All tokens were short (e.g. 'uv pip') — match the raw query so
            # strict lookups don't falsely report no matches (R49 review).
            terms = [query.strip().lower()]

        def score(row) -> tuple[int, str]:
            content = row['content'].lower()
            hits = sum(1 for t in terms if t in content)
            return (hits, row['created_at'])

        ranked = sorted(rows, key=score, reverse=True)
        best_hits = score(ranked[0])[0] if ranked else 0
        if best_hits == 0 and require_hit:
            return []
        if best_hits > 0:
            ranked = [row for row in ranked if score(row)[0] > 0]
        return ranked[:top_n]

    def retrieve_semantic(self, embedder, workdir: str | None, query: str, top_n: int = 10,
                          kind: str | None = None) -> list[tuple[str, float]]:
        """Entries ranked by embedding similarity (scope = global + this Workdir)."""
        from .semantic import cosine

        rows = self._db._conn.execute(
            'SELECT content, kind FROM memory'
            " WHERE scope = 'global' OR workdir = ?",
            (workdir,),
        ).fetchall()
        if kind is not None:
            rows = [r for r in rows if r['kind'] == kind]
        qv = embedder.embed(query)
        scored = [(r['content'], cosine(qv, embedder.embed(r['content']))) for r in rows]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]


def build_memory_toolset(store: MemoryStore, workdir: str) -> FunctionToolset:
    """remember/forget + solutions tools — deliberate Memory banking by the agent."""

    def remember(content: str, scope: str = 'workdir') -> str:
        if scope not in ('global', 'workdir'):
            return "scope must be 'global' or 'workdir'"
        store.add(content, scope=scope, workdir=workdir)
        return f'remembered ({scope}): {content}'

    def forget(content_substring: str) -> str:
        deleted = store.delete_substring(content_substring)
        return f'forgot {deleted} entr{"y" if deleted == 1 else "ies"}'

    def record_solution(problem: str, solution: str, scope: str = 'workdir') -> str:
        """Bank a solved problem (R49): paraphrase-duplicates update in place."""
        if scope not in ('global', 'workdir'):
            return "scope must be 'global' or 'workdir'"
        if not problem.strip() or not solution.strip():
            return 'both problem and solution are required'
        content = f'Problem: {problem.strip()}\nSolution: {solution.strip()}'
        dupes = store.duplicate_ids(problem, kind='solution', workdir=workdir)
        if dupes:
            store.update_content(dupes[0], content)
            return f'updated solution #{dupes[0]}: {content}'
        entry_id = store.add(content, scope=scope,
                             workdir=workdir if scope == 'workdir' else None,
                             kind='solution')
        return f'recorded solution #{entry_id}: {content}'

    def lookup_solutions(query: str) -> str:
        """Look up previously solved problems (R49 referential memory)."""
        hits = store.retrieve(workdir, query=query, kind='solution', top_n=5,
                              require_hit=True)
        if not hits:
            return 'no matching solutions recorded'
        return '\n'.join(f'- #{h["id"]} {h["content"]}' for h in hits)

    return FunctionToolset([remember, forget, record_solution, lookup_solutions])
