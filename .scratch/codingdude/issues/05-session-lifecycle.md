# 05: Session lifecycle

**What to build:** Sessions become durable, context-rich objects. A closed Session resumes with full history; the Workdir's `AGENT.md` Project Context auto-loads at session start and agent-proposed edits to it route through the Approval gate; long Sessions auto-compact at a token threshold with the compaction point visible as a checkpoint event; usage accumulates per Session for the cost meter.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** ready-for-agent

- [ ] A Session closed mid-conversation resumes and a scripted run recalls an earlier turn's content
- [ ] `AGENT.md` instructions demonstrably steer a scripted run's behavior from turn one
- [ ] An agent proposal to edit `AGENT.md` surfaces as a gated action, not a silent write
- [ ] A scripted long Session crosses the compaction threshold, emits a visible checkpoint event, and continues coherently
- [ ] Per-Session token and cost totals accumulate in the database
