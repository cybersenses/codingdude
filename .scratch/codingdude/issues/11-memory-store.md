# 11: Memory store

**What to build:** CodingDude remembers across Sessions. Explicit remember/forget tools bank Memory Entries (global or Workdir-scoped); a cheap-model post-session extraction pass captures missed facts; at Session start the top relevant entries (keyword + recency) are injected into context; a UI panel lists and deletes entries — no hidden state.

**Blocked by:** 05 (Session lifecycle), 09 (React shell)

**Status:** partially resolved — engine complete, UI panel pending (ticket 10)

- [x] A scripted run banks a fact via the remember tool; it persists scoped (global or Workdir)
- [x] A new Session on the same Workdir demonstrably receives the relevant Memory Entries in context
- [x] Post-session extraction adds a fact the run didn't explicitly remember
- [ ] The forget tool removes an entry; the UI panel lists and deletes entries *(forget tool done and tested; the UI panel lands with ticket 10's right-panel work — server endpoints `GET/DELETE /memory` still to add)*

## Comments

2026-09-07: Commit c24a894. `MemoryStore` over the memory table; retrieval = keyword hits with recency tiebreak, scoped global + this Workdir, injected into instructions. remember/forget are agent tools. Post-session extraction runs on the configured cheap model (`Engine(extraction_model=...)`, worker wires it to `models.subagent`), never fails the run, and dedupes against existing entries.
