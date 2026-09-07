# 03: Surgical edits

**What to build:** CodingDude changes code, not just reads it. The edit tool applies exact-match search/replace blocks with whole-file write only as fallback (and for new files), fails loudly on stale matches so the model retries instead of corrupting files, and every edit emits a structured change event on the run's event stream so the (future) UI can render diffs without touching files itself.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** ready-for-agent

- [ ] A scripted run surgically modifies a target function in a temp Workdir without rewriting the rest of the file
- [ ] A search/replace whose old-content doesn't match returns a retry-visible failure; the file is untouched
- [ ] New files and their parent directories are created through the same tooling
- [ ] Whole-file fallback path works and is exercised in tests
- [ ] Every edit surfaces as a structured change event (path, before/after) on the event stream
