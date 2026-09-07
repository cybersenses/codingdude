# 13: Git + `gh` PR flow

**What to build:** The full GitHub unit of work: "make a PR for this" as one task. Local reads (status/log/diff) are auto-approved tools; commits and branch creation gate behind Approval cards; push/PR/review interactions via `gh` sit in the always-gated tier — never pattern-unlockable.

**Blocked by:** 10 (Approval cards + panels)

**Status:** resolved at the engine seam; browser-flow verification lands with ticket 10

- [x] Scripted runs use status/log/diff freely to understand repo state
- [x] A commit surfaces as a gated action; approving creates it on the chosen branch
- [x] Push and PR creation are always-gated: no pattern approval unlocks them
- [x] A stubbed `gh` proves the PR-creation flow end-to-end in tests
- [ ] In the browser, "make a PR for this change" completes via approval cards *(cards are ticket 10; the engine-side gate/abort contract they will drive is done and tested)*

## Comments

2026-09-07: Commit 221d002. `build_git_toolset(workdir, policy)`: git_status/log/diff auto (pure reads); git_commit and git_branch gate via the policy (pattern-approvable — `Engine.approve_pattern` records session-scoped patterns); git_push, gh_pr_create, gh_pr_view always-gated (DENIED survives any pattern, only yolo unlocks, verified). Commit tool surfaces git errors honestly instead of claiming success (caught by review: scratch repos without committer identity made the first version lie). gh runs through the shell for Windows PATH resolution.
