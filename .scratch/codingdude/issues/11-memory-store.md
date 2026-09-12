# 11: Memory store

**What to build:** CodingDude remembers across Sessions. Explicit remember/forget tools bank Memory Entries (global or Workdir-scoped); a cheap-model post-session extraction pass captures missed facts; at Session start the top relevant entries (keyword + recency) are injected into context; a UI panel lists and deletes entries — no hidden state.

**Blocked by:** 05 (Session lifecycle), 09 (React shell)

**Status:** resolved — engine + server endpoints + UI Memory panel (ticket 10) complete

- [x] A scripted run banks a fact via the remember tool; it persists scoped (global or Workdir)
- [x] A new Session on the same Workdir demonstrably receives the relevant Memory Entries in context
- [x] Post-session extraction adds a fact the run didn't explicitly remember
- [x] The forget tool removes an entry; the UI panel lists and deletes entries *(server endpoints `GET/DELETE /memory` exist; Memory tab in the right panel)*

## Comments

2026-09-07: Commit c24a894. `MemoryStore` over the memory table; retrieval = keyword hits with recency tiebreak, scoped global + this Workdir, injected into instructions. remember/forget are agent tools. Post-session extraction runs on the configured cheap model (`Engine(extraction_model=...)`, worker wires it to `models.subagent`), never fails the run, and dedupes against existing entries.
