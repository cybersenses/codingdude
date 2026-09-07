# 02: Read-only tracer bullet

**What to build:** The first complete path through the engine: `codingdude run "what does this repo do?"` on any Workdir. The engine run loop (start run → event stream → final state) exists, with read/list/grep/glob tools that refuse paths outside the Workdir, and the full conversation persists as a Session in SQLite. Proven at the engine seam with scripted model runs over a temp Workdir.

**Blocked by:** 01 (Foundations & rename)

**Status:** resolved

- [x] A scripted run answers a question about a temp Workdir using only grep/read/list/glob — no curating by hand
- [x] Any tool call targeting a path outside the Workdir is refused
- [x] Multi-turn runs accumulate messages in the Session; a second run on the same Session sees the first turn's context
- [x] Headless exit code distinguishes success from failure

## Comments

2026-09-07: Implemented in commit 42ef7c4. Tools live in their own module and are bound to the Workdir via closure; out-of-Workdir paths raise ModelRetry so the model self-corrects instead of crashing the run. `codingdude run "prompt"` (--workdir, --model flags) wired to the engine; exit 0 on success, 1 on failure. 17 tests green, mypy clean. Note: a live end-to-end run still needs real API keys (same caveat as ticket 01's production failover path).
