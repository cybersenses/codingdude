# R11-tracer — Per-project reference knowledgebase (ticket #7)

Thin vertical slice. Folder-first, DB-indexed, freshness-flagged.

## Convention (ratified)
- Source of truth: the project's **`reference/` folder** (existing; `reference/pydantic-ai-main` already present). Human-editable, git-versioned.
- The DB index is **rebuildable cache**, never authoritative.

## Module: `src/codingdude/references.py`
- `ReferenceStore(db, workdir)`:
  - `reindex()` — scans `reference/**/*.md`, splits into sections by markdown headings (`#`–`###`), stores one row per section in `reference_sections` (workdir-scoped), plus file mtime+size in `reference_meta`. Only re-reads changed files (mtime/size key), so repeated searches are cheap.
  - `search(query)` — keyword scoring over section headings + content (same token-hit idiom as `MemoryStore.retrieve`), top 8. Returns `path § heading` lines with excerpt.
  - `read(path, heading=None)` — full file or one section; readable errors for missing path/heading.
  - `staleness()` — compares each file's recorded version against `pyproject.toml` / `package.json` pins:
    - version match → nothing
    - version diverges (major.minor) → `⚠ stale: documents X.Y, project pins Z.W`
    - version unknown → `version unknown — pin it with set_reference_version`
- Version metadata: leading HTML comment in the file (`<!-- codingdude: version=2.10 -->`) or set via the `set_reference_version` tool (persisted in `reference_meta`).

## Tools (`build_references_toolset(db, workdir)`, wired in `build_all`)
- `search_references(query)` — indexed search; refreshes index first.
- `read_reference(path, heading='')` — cite/read a section; staleness warning appended.
- `set_reference_version(path, version)` — records the documented library version.

## Schema (added to `db.py` `_SCHEMA`)
- `reference_sections(id, workdir, path, heading, content, indexed_at)`
- `reference_meta(workdir, path, version, mtime, size, PRIMARY KEY(workdir, path))`

## Test seam
`ReferenceStore` + toolset functions against a real tmp workdir (`reference/` with a couple of markdown files) and a real `Database.connect(home)` — no mocks. Staleness tested against a synthetic `pyproject.toml` pin.
