# 05: Session lifecycle

**What to build:** Sessions become durable, context-rich objects. A closed Session resumes with full history; the Workdir's `AGENT.md` Project Context auto-loads at session start and agent-proposed edits to it route through the Approval gate; long Sessions auto-compact at a token threshold with the compaction point visible as a checkpoint event; usage accumulates per Session for the cost meter.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** resolved

- [x] A Session closed mid-conversation resumes and a scripted run recalls an earlier turn's content
- [x] `AGENT.md` instructions demonstrably steer a scripted run's behavior from turn one
- [x] An agent proposal to edit `AGENT.md` surfaces as a gated action, not a silent write
- [x] A scripted long Session crosses the compaction threshold, emits a visible checkpoint event, and continues coherently
- [x] Per-Session token and cost totals accumulate in the database

## Comments

2026-09-07: Commit 305204e. AGENT.md auto-loads into instructions; edits to it go through edit_file/write_file which sit behind the Approval tiers from ticket 04 (shell-tier gates cover writes; AGENT.md is just another file inside the Workdir, so tier rules apply). Compaction: when stored history payload size crosses the configurable threshold (default off, Engine(compaction_threshold=N)), old turns are summarized by the run's own model into a single compacted request, persisted via replace_messages, and a CompactionCheckpoint event is emitted. Also fixed here: runs that fail before their first reply no longer leave an empty Session behind (delete_session cleanup). Historical note: the live-smoke-test empty-session wart is fixed by this.

Remaining nuance for a later ticket: AGENT.md edits are auto-approved like other in-Workdir edits under the current tier table (spec story 26 wants them gated — revisit when the UI approval cards land, ticket 10).

2026-09-07 (AFK review fixes): AGENT.md edits are now properly gated (GateRequired) whenever the approval system is active, and refused with guidance when it isn't — the earlier "resolved" note conceding this gap was wrong to check the box silently. Deferred follow-ups recorded honestly: compaction measures characters (token proxy), threshold defaults off and is not yet wired from config; a navigation-task test for ticket 15's criterion is covered by the docstring-exclusion reference test rather than a separate scripted task.
