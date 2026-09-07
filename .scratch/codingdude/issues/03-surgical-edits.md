# 03: Surgical edits

**What to build:** CodingDude changes code, not just reads it. The edit tool applies exact-match search/replace blocks with whole-file write only as fallback (and for new files), fails loudly on stale matches so the model retries instead of corrupting files, and every edit emits a structured change event on the run's event stream so the (future) UI can render diffs without touching files itself.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** resolved

- [x] A scripted run surgically modifies a target function in a temp Workdir without rewriting the rest of the file
- [x] A search/replace whose old-content doesn't match returns a retry-visible failure; the file is untouched
- [x] New files and their parent directories are created through the same tooling
- [x] Whole-file fallback path works and is exercised in tests
- [x] Every edit surfaces as a structured change event (path, before/after) on the event stream

## Comments

2026-09-07: Commit 5b73c7d. edit_file demands a unique exact match (0 or >1 matches raise ModelRetry with self-correction hints); write_file is confined to new/empty files and refuses to clobber non-empty ones. Edits emit EditChange(path, before, after) via Engine.run(on_event=...) — the future UI's diff feed. Also: provider keys can now come from [providers] in config.toml (env vars still win).
