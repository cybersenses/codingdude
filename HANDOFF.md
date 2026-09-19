# Handoff note - to the next agent on duty

*Updated after commit a75b458 (pushed). Main == origin/main, tree clean.*

## Current state
- **R34 (Human interface & cowork / Monaco) DONE** - all 3 tickets closed:
  - #69 `be12533`: server file API - GET/PUT `/file` + `/tree`; nanosecond
    staleness guard (GET returns `mtime` ns; PUT takes `expected_mtime`,
    409 on stale), `_atomic_write` (uuid tmp + retried `os.replace`),
    path containment via `resolve_workdir_path`.
  - #70 `afd0241`: Monaco editor (`@monaco-editor/react`, custom `cd-dark`
    theme) replaced CodeMirror; tabbed editing (max 8 tabs, logic in
    `frontend/src/editor.ts`, vitest-covered); save gated on dirty +
    staleness; 409 -> "changed on disk" + explicit reload.
  - #71 `a75b458`: diff view - `GET /sessions/{id}/file_diff?path=` returns
    `{path, base, content}` (base = `git show HEAD:...`, '' for new files;
    route named file_diff because `/diff` whole-tree route already exists).
    Frontend `CodeDiff` (named export in CodeEditor.jsx) + toggle in
    FileExplorer showing HEAD vs draft.
- Gates: 503 passed / 1 skipped, ruff + mypy clean (52 files), vitest 16/16,
  build clean (17.6s).

## MUST DO after bounce
- Bounce the server: new /file_diff endpoint + new dist bundle only serve
  after restart. Then verify: Files panel loads tree, open file, edit,
  toggle diff view, save.

## Open roadmap
- R31 (run-end determinism residual) - flicker fix live; user may close it.
- R33 review automation: #66 auto PR summaries, #67 auto code-review
  post-push, #68 graph-informed reviews (codegraph impact mandate).

## Known accepted gaps
- #71 diff state resets on tab activate/close were done in App.jsx; no new
  logic tests for the thin UI glue (intentional).
- Monaco adds a large chunk; chunk-size warning in build is pre-existing.
- Vision pixel gate still has no live end-to-end check.

## Environment notes
- Windows 11, project at G:/pydantic, venv ./.venv/Scripts/.
- Gates: ./.venv/Scripts/python.exe -m pytest -q; ruff check src tests;
  python -m mypy src; frontend: cd frontend && npx vitest run && npm run build.
- WSL git uses Windows GCM for credentials - push works from agent shell
  (git push origin main, ~seconds). Docker CLI: use docker.exe from WSL.
- tools.py and other files are CRLF - preserve; the edit tool keeps
  normalizing some files to LF, restore CRLF pre-commit when diff explodes.
- HANDOFF.md must stay UTF-8 (this file was once cp1252 and blocked edits).

## Process reminders
- TDD red-first at pre-agreed seams; full gates before any done claim.
- Every user message means continue-the-work; user says proceed/afk -> keep
  going without re-asking. Bounce = delivery mechanism, not a new task.
- Keep ROADMAP.md statuses in sync when closing items; ticket tool closes
  record the closing commit.
