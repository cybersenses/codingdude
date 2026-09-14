# R7 curation: session marking + timestamped notes → selective scenario export

Recording is already always-on (traces JSONL + messages in SQLite). This feature
adds curation on top: mark sessions worth keeping, annotate them at points in
time, and export annotated scenarios.

## Decisions (agreed)
- **No record on/off flag.** Always record (as today); add a per-session
  `keep_for_evals` mark plus a per-project `never_record` escape hatch is
  *deferred* (thin, no current need).
- **Notes attach to run + time offset** within the session timeline; V1 stores
  the offset in seconds from session start and the note text. Notes ride along
  on export as human annotation — they are NOT machine-checkable (CHECKS stays
  the only assertion mechanism).

## Data model (db.py)
- `sessions.keep_for_evals INTEGER DEFAULT 0` (via `_migrate`, matching the
  `context_tokens` pattern).
- New `session_notes` table: `id, session_id, run_id TEXT NULL, offset_s REAL
  NULL, content TEXT NOT NULL, created_at TEXT NOT NULL`.

## API (Database)
- `set_keep_for_evals(session_id, keep: bool) -> None`
- `add_session_note(session_id, content, run_id=None, offset_s=None) -> int`
- `list_session_notes(session_id) -> list[dict]` (chronological)

## Evals (evals.py)
- `export_scenario` includes `'notes': db.list_session_notes(session_id)` when
  any exist (key always present, possibly empty list).

## Server (server.py)
- `POST /sessions/{id}/notes` `{content, run_id?, offset_s?}` → `{id}`
- `GET /sessions/{id}/notes` → list
- `POST /sessions/{id}/keep` `{keep: bool}` → `{ok: true}`

## Frontend (App.jsx)
- Session view: 📌 toggle (keep for evals) + notes list with an add-note field;
  note shows content + offset. No new tab.

## Tests
- db: mark/unmark round-trip; add/list notes ordering; export_scenario carries
  notes.
- server: endpoints via TestClient at existing auth seams.
- Frontend: no JS tests (repo convention); verified via `npm run build`.
