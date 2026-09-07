# 13: Git + `gh` PR flow

**What to build:** The full GitHub unit of work: "make a PR for this" as one task. Local reads (status/log/diff) are auto-approved tools; commits and branch creation gate behind Approval cards; push/PR/review interactions via `gh` sit in the always-gated tier — never pattern-unlockable.

**Blocked by:** 10 (Approval cards + panels)

**Status:** ready-for-agent

- [ ] Scripted runs use status/log/diff freely to understand repo state
- [ ] A commit surfaces as a gated action; approving creates it on the chosen branch
- [ ] Push and PR creation are always-gated: no pattern approval unlocks them
- [ ] A stubbed `gh` proves the PR-creation flow end-to-end in tests
- [ ] In the browser, "make a PR for this change" completes via approval cards
