# 17: Durable-exec decision spike

**What to build:** A research ticket, not code: evaluate whether CodingDude adopts pydantic-ai's durable execution (DBOS vs Temporal vs defer), given a single-user Windows setup that already has Session resumption from SQLite. Produce a written recommendation with the operational cost of each option and the concrete failure modes it would fix that Session resume doesn't.

**Blocked by:** 05 (Session lifecycle)

**Status:** resolved

- [x] Each option's infrastructure burden on a personal Windows machine is documented
- [x] The failure modes Session resume already covers are listed so the gap is honest
- [x] A clear adopt/defer recommendation with rationale is appended under `## Answer`

## Comments

2026-09-07: Scope verified against pydantic-ai 2.40: durable execution ships as attachable "durability capabilities" (`TemporalDurability`, `DBOSDurability`, `PrefectDurability`) that checkpoint model requests, tool calls, event-stream handlers, and compaction as replayable operations. Storage is entirely the engine's — pydantic-ai provides none.

## Answer

**Recommendation: defer.** Revisit only if a concrete workflow appears that Session resume cannot cover.

**Infrastructure burden (single-user Windows machine):**
- **DBOS**: requires a PostgreSQL server installed and running locally (or a paid cloud instance). Windows-native Postgres is a real service to install, patch, and keep running — the heaviest permanent addition of the three.
- **Temporal**: a full Temporal cluster (server + worker + persistence backend). Industrial-grade, but absurd for one user; Docker-based local dev clusters on Windows are the standard route, adding Docker Desktop as a permanent dependency.
- **Prefect**: lightest to start (pip install + local server/process orchestrator), but its model (flows/tasks, a scheduler, an API server) is workflow-orchestration machinery around what is fundamentally a single interactive agent run.

**What Session resume already covers (the honest gap list):**
- Conversation continuity across browser refreshes, server restarts, and worker crashes (messages persisted per turn in SQLite; resume replays history into the next run).
- Crash mid-run: the worker dying loses at most the current model turn; the user re-sends and the agent continues with full context.
- Approval interruptions: the deferred-approval flow already pauses/resumes runs by design.
- Cost caps bound the blast radius of a runaway loop.

**The real gap durable execution would close:** a long *autonomous* (`--yolo`) run surviving a machine reboot or server restart *without any user action* — replaying the exact in-flight model request and tool call from a journal instead of asking the model to continue from history. That matters for unattended batch usage; it does not matter for interactive use, where the user is present anyway.

**Decision:** stay with Session resumption. The cost (a permanent database or cluster dependency, an extra moving part in every run) buys resilience for a scenario (unattended long autonomous runs surviving OS-level interruptions) that hasn't occurred and isn't part of the product's daily shape. If `--yolo` batch usage ever becomes a habit, DBOS is the closest fit for this codebase (lightest engine, plain SQLite→Postgres story, cleanest capability attach) — re-evaluate then.
