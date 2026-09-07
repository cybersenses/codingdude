# 17: Durable-exec decision spike

**What to build:** A research ticket, not code: evaluate whether CodingDude adopts pydantic-ai's durable execution (DBOS vs Temporal vs defer), given a single-user Windows setup that already has Session resumption from SQLite. Produce a written recommendation with the operational cost of each option and the concrete failure modes it would fix that Session resume doesn't.

**Blocked by:** 05 (Session lifecycle)

**Status:** ready-for-agent

- [ ] Each option's infrastructure burden on a personal Windows machine is documented
- [ ] The failure modes Session resume already covers are listed so the gap is honest
- [ ] A clear adopt/defer recommendation with rationale is appended under `## Answer`
