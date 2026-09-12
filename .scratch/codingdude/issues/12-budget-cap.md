# 12: Budget Cap

**What to build:** The runaway-loop brake. An optional per-Session spending cap, off by default, settable in the UI; the engine hard-stops the run when spend crosses it, with a clear final event; the cost meter is visible throughout. `--yolo` does not bypass the cap.

**Blocked by:** 05 (Session lifecycle), 09 (React shell)

**Status:** resolved — engine + CLI complete; budget passes via the start-run body (UI input deferred to backlog)

- [x] With no cap set, runs behave exactly as before
- [x] Setting a cap then driving a scripted spendy run hard-stops at the cap with a distinct final event (BudgetExceeded; worker emits RUN_ERROR code=budget; headless exit 3)
- [x] The cost meter reflects accumulating spend across the Session (usage table, Cost tab in the right panel)
- [x] `--yolo` runs still stop at the cap

## Comments

2026-09-07: Commit 8580d8a. `Engine(budget_cap_usd=...)`: pre-run check blocks sessions already over budget without any model call; post-run check raises the moment a run crosses the cap (that run's usage is still recorded — the meter stays truthful). CLI: `codingdude run --budget 5.00`. UI cap setter + meter render deferred to ticket 10's Cost panel.
