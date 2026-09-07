# 11: Memory store

**What to build:** CodingDude remembers across Sessions. Explicit remember/forget tools bank Memory Entries (global or Workdir-scoped); a cheap-model post-session extraction pass captures missed facts; at Session start the top relevant entries (keyword + recency) are injected into context; a UI panel lists and deletes entries — no hidden state.

**Blocked by:** 05 (Session lifecycle), 09 (React shell)

**Status:** ready-for-agent

- [ ] A scripted run banks a fact via the remember tool; it persists scoped (global or Workdir)
- [ ] A new Session on the same Workdir demonstrably receives the relevant Memory Entries in context
- [ ] Post-session extraction adds a fact the run didn't explicitly remember
- [ ] The forget tool removes an entry; the UI panel lists and deletes entries
