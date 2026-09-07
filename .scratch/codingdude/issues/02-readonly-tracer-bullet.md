# 02: Read-only tracer bullet

**What to build:** The first complete path through the engine: `codingdude run "what does this repo do?"` on any Workdir. The engine run loop (start run → event stream → final state) exists, with read/list/grep/glob tools that refuse paths outside the Workdir, and the full conversation persists as a Session in SQLite. Proven at the engine seam with scripted model runs over a temp Workdir.

**Blocked by:** 01 (Foundations & rename)

**Status:** ready-for-agent

- [ ] A scripted run answers a question about a temp Workdir using only grep/read/list/glob — no curating by hand
- [ ] Any tool call targeting a path outside the Workdir is refused
- [ ] Multi-turn runs accumulate messages in the Session; a second run on the same Session sees the first turn's context
- [ ] Headless exit code distinguishes success from failure
