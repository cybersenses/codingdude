"""Per-project reference knowledgebase (R11).

The project's `reference/` folder is the source of truth (human-editable,
git-versioned). This module maintains a rebuildable section-level index in
the workdir-scoped SQLite and exposes search/read/version-pin tools.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

_HEADING = re.compile(r'^(#{1,3}) (.+)$', re.MULTILINE)
_VERSION_COMMENT = re.compile(
    r'<!--\s*codingdude:\s*version=([^\s>]+)\s*-->', re.IGNORECASE
)
_PIN = re.compile(r'"?([A-Za-z0-9_.-]+)[><=~!^]+(\d+)\.(\d+)')


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ReferenceStore:
    def __init__(self, db, workdir: Path | str):
        self._db = db
        self._workdir = str(workdir)

    # -- indexing -----------------------------------------------------------

    def reindex(self) -> int:
        """Scan `reference/**/*.md`, index changed files. Returns files indexed."""
        root = Path(self._workdir) / 'reference'
        if not root.is_dir():
            return 0
        indexed = 0
        for path in sorted(root.rglob('*.md')):
            stat = path.stat()
            rel = path.relative_to(self._workdir).as_posix()
            meta = self._meta(rel)
            sig = f'{stat.st_mtime_ns}:{stat.st_size}'
            if meta is not None and meta['mtime'] == sig:
                continue
            self._index_file(rel, path, sig)
            indexed += 1
        return indexed

    def _index_file(self, rel: str, path: Path, sig: str) -> None:
        text = path.read_text(encoding='utf-8', errors='replace')
        conn = self._db._conn
        conn.execute(
            'DELETE FROM reference_sections WHERE workdir = ? AND path = ?',
            (self._workdir, rel),
        )
        version = self._declared_version(text) or (
            self._meta(rel) or {'version': None}
        )['version']
        for heading, content in _sections(text):
            conn.execute(
                'INSERT INTO reference_sections'
                ' (workdir, path, heading, content, indexed_at)'
                ' VALUES (?, ?, ?, ?, ?)',
                (self._workdir, rel, heading, content, _now()),
            )
        conn.execute(
            'INSERT INTO reference_meta (workdir, path, version, mtime, size)'
            ' VALUES (?, ?, ?, ?, ?)'
            ' ON CONFLICT(workdir, path) DO UPDATE SET'
            ' version=excluded.version, mtime=excluded.mtime, size=excluded.size',
            (self._workdir, rel, version, sig, path.stat().st_size),
        )
        conn.commit()

    def _declared_version(self, text: str) -> str | None:
        match = _VERSION_COMMENT.search(text)
        return match.group(1) if match else None

    # -- retrieval ----------------------------------------------------------

    def search(self, query: str, top_n: int = 8) -> list[str]:
        """Top sections by keyword hits, formatted as `path § heading — excerpt`."""
        terms = [t.lower() for t in query.split() if len(t) > 2]
        if not terms:
            return []
        rows = self._db._conn.execute(
            'SELECT path, heading, content FROM reference_sections WHERE workdir = ?',
            (self._workdir,),
        ).fetchall()

        def score(row) -> int:
            hay = (row['heading'] + ' ' + row['content']).lower()
            return sum(hay.count(t) for t in terms)

        ranked = sorted(rows, key=score, reverse=True)
        return [
            f"{r['path']} § {r['heading']} — {r['content'][:160].strip()}"
            for r in ranked[:top_n]
            if score(r) > 0
        ]

    def read(self, path: str, heading: str | None = None) -> str:
        """Full file or one section (joined) from the index."""
        rows = self._db._conn.execute(
            'SELECT heading, content FROM reference_sections'
            ' WHERE workdir = ? AND path = ? ORDER BY id',
            (self._workdir, path),
        ).fetchall()
        if not rows:
            raise ValueError(
                f'{path!r} is not in the reference index — is it under reference/ '
                'and reindexed?'
            )
        if heading is None:
            return '\n\n'.join(f"{r['heading']}\n{r['content']}" for r in rows)
        for row in rows:
            if row['heading'] == heading:
                return row['content']
        raise ValueError(
            f'no section {heading!r} in {path!r}; sections: '
            + ', '.join(r['heading'] for r in rows)
        )

    # -- freshness ----------------------------------------------------------

    def set_version(self, path: str, version: str) -> str:
        cur = self._db._conn.execute(
            'UPDATE reference_meta SET version = ? WHERE workdir = ? AND path = ?',
            (version, self._workdir, path),
        )
        self._db._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f'{path!r} is not indexed (run search_references first).')
        return f'{path}: documented version set to {version}'

    def staleness(self) -> list[str]:
        """One line per reference whose version diverges from / misses a pin."""
        versions = {
            r['path']: r['version']
            for r in self._db._conn.execute(
                'SELECT path, version FROM reference_meta WHERE workdir = ?',
                (self._workdir,),
            ).fetchall()
        }
        pins = _project_pins(Path(self._workdir))
        report = []
        for path, version in sorted(versions.items()):
            # a pin applies when any path component names the package
            # (pydantic matches pydantic-ai-main/, pydantic-notes.md, ...)
            matches = [(pkg, pin) for pkg, pin in pins.items()
                       if any(part.lower().startswith(pkg)
                              for part in Path(path).parts)]
            if not matches:
                continue
            for pkg, pin in matches:
                if version is None:
                    report.append(
                        f'⚠ {path}: version unknown — project pins {pkg} '
                        f'{pin}; pin it with set_reference_version'
                    )
                elif version != pin:
                    report.append(
                        f'⚠ {path}: stale — documents {version},'
                        f' project pins {pkg} {pin}'
                    )
        return report

    # -- helpers ------------------------------------------------------------

    def _meta(self, path: str) -> dict | None:
        row = self._db._conn.execute(
            'SELECT version, mtime, size FROM reference_meta'
            ' WHERE workdir = ? AND path = ?',
            (self._workdir, path),
        ).fetchone()
        return dict(row) if row else None


def _sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs; pre-heading text joins the first."""
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [('(untitled)', text.strip())] if text.strip() else []
    result = []
    if text[: matches[0].start()].strip():
        result.append(('(intro)', text[: matches[0].start()].strip()))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        result.append((match.group(2).strip(), text[match.end():end].strip()))
    return result


def _project_pins(workdir: Path) -> dict[str, str]:
    """Package → pinned major.minor, from pyproject.toml / package.json."""
    pins: dict[str, str] = {}
    pyproject = workdir / 'pyproject.toml'
    if pyproject.exists():
        for match in _PIN.finditer(pyproject.read_text(encoding='utf-8', errors='replace')):
            pins.setdefault(match.group(1).lower().replace('_', '-'),
                            f'{match.group(2)}.{match.group(3)}')
    package_json = workdir / 'package.json'
    if package_json.exists():
        import json as _json

        try:
            data = _json.loads(package_json.read_text(encoding='utf-8'))
        except _json.JSONDecodeError:
            return pins
        for section in ('dependencies', 'devDependencies'):
            for name, spec in (data.get(section) or {}).items():
                spec_match = re.match(r'^[\^~>=< ]*(\d+)\.(\d+)', str(spec))
                if spec_match:
                    pins.setdefault(
                        name.lower(), f'{spec_match.group(1)}.{spec_match.group(2)}'
                    )
    return pins


def build_references_toolset(db, workdir: Path | str) -> FunctionToolset:
    """search_references / read_reference / set_reference_version tools."""
    store = ReferenceStore(db, workdir)

    def search_references(query: str) -> str:
        """Search the project's reference/ manuals (section-level index).

        Refreshes the index first, so newly dropped files are found.
        Returns `path § heading — excerpt` lines; follow up with read_reference.
        """
        store.reindex()
        hits = store.search(query)
        if not hits:
            return f'no reference sections match {query!r}'
        warnings = store.staleness()
        return '\n'.join(hits + warnings)

    def read_reference(path: str, heading: str = '') -> str:
        """Read a reference file (or one section by exact heading) from the index."""
        try:
            content = store.read(path, heading or None)
        except ValueError as exc:
            return str(exc)
        warnings = [w for w in store.staleness() if path in w]
        return '\n'.join([content] + warnings)

    def set_reference_version(path: str, version: str) -> str:
        """Record which library version a reference documents (freshness pin)."""
        try:
            return store.set_version(path, version)
        except ValueError as exc:
            return str(exc)

    return FunctionToolset([search_references, read_reference, set_reference_version])
