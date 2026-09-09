# North-Star Gap Analysis: what separates CodingDude from best-in-class

Status: proposal for the next build phase — measured against the north star
(*best-in-world AI coding tool, zero slop, first-class UX, solid software
engineering at its heart*), benchmarked against the 2026 leaders: Claude Code,
Cursor, Codex, Aider, Cline.

## Where we already match or lead

Don't rebuild these — they're the moat:

- **Discipline loop**: plan → approve → tracked steps → mandatory review with
  findings fed back. Most competitors generate and hope; we gate and verify.
- **Tiered approvals with visible gates** — interactive cards, session-scoped
  patterns, always-gated destructive tier, budget cap surviving `--yolo`.
- **Self-hosted engineering methodology** — directives, skills, review
  checklist editable in the UI; the methodology is a feature, not a prompt.
- **Analysis tools**: test coverage, dead-code detection (Python + JS/TS),
  dead exports (knip), AST navigation.
- **Observability**: per-session JSONL traces, cost meter, failover, structured
  login/auth, CI, typed API layer.

## The gaps that matter, ranked by north-star impact

### Tier 1 — the SWE heart (do these first)

**1. Checkpoints & instant rollback.** Biggest safety gap. Today, edits to a
non-git workdir are irreversible; even in git repos, undoing means manual
revert. Standard: automatic snapshot before every edit batch (shadow copy or
git commit on a hidden ref), a **Rollback** button per checkpoint in the UI.
*Claude Code calls these checkpoints; Aider auto-commits. Table stakes for
"trust the agent with my code".*

**2. Auto test-fix loop with iteration cap.** "Fix until green" as a
first-class mode: run tests → diagnose failures → patch → re-run, up to N
iterations (configurable), with the loop visible as plan-like steps. We have
all the primitives (tests, shell, coverage, plan); the loop itself is
assembled ad hoc by the model today. Deterministic loops beat hopeful ones.

**3. Repo map for large codebases.** Our tools are per-call (grep/glob/read).
Best-in-class agents build a **compact repo overview** — tree + key signatures
+ imports graph, budget-sized — auto-included at session start so the agent
orients in one hop instead of twenty. Direct payoff: fewer wasted tool calls,
better plans, lower cost on big repos. Tree-sitter already in the stack.

**4. Claim verification in review.** The reviewer checks the diff, but not the
agent's *claims*. Upgrade: extract the final summary's verifiable claims ("tests
pass", "build succeeds", "endpoint returns X"), re-run the checks, and flag
claims that don't hold. This is the strongest anti-slop mechanism available —
the agent cannot say "verified" unless the verification re-ran.

**5. CI integration.** Read failing CI runs (`gh run view --log-failed`),
reproduce locally, fix, push. The team loop: agent works on CI failures the
same way it works on local test failures.

### Tier 2 — first-class UX

**6. Inline diff blocks in chat.** Today edits live in the side Diff panel.
Best-in-class shows the diff inline in the message stream (Cursor-style), with
accept/reject per block. Combine with an optional **suggest mode**: agent edits
become proposals to accept rather than instant writes — for sensitive repos.

**7. Git worktree isolation for parallel sessions.** Run multiple sessions on
the same repo without them stepping on each other: each gets an isolated
worktree + branch, merge when satisfied. Unlocks parallel agents safely
(Claude Code's differentiator in 2026 rankings).

**8. Screenshot/image input.** Paste a design mock → implement it. Requires
multimodal input through the worker/model path. The single highest-demand
feature for UI work.

**9. Completion notifications.** Browser title change + optional sound when a
run finishes or waits at a gate — you stepped away and came back to find it
waiting; that shouldn't happen silently.

**10. Multi-session parallel view.** The backend already supports concurrent
workers; the UI assumes one active session. A session switcher that keeps runs
streaming in the background.

### Tier 3 — depth and scale

**11. Safe rename/refactor tools.** Tree-sitter rename-symbol across files
(find_references exists; rename is the application). With JS/TS + Python
support already in the analysis stack, this is the natural completion of
refactoring tooling.

**12. Bench expansion to 15+ tasks incl. live scoring** — SWE-bench-style
local suite; leaders compete on benchmark scores, and our prompt/model changes
should be measurable. Add: repo-setup tasks, multi-file refactors, bug-fix
scenarios with hidden tests.

**13. knip/dependency-vulnerability sweep integration** — extend dead-code
tooling to unused *dependencies* and `npm audit`-style vulnerability surfacing
in the Standards tab.

**14. Trace viewer upgrade** — spans with durations grouped per run/step
(we have the JSONL; add timing deltas and a tree view), optional OTel export.

### Explicit non-goals (anti-slop stance)

- Tab-completion/autocomplete — that's an IDE feature, not an agent feature.
- Fully-autonomous long-horizon "Devin-style" runs without checkpoints —
  contradicts the discipline-first philosophy until checkpoints are proven.
- Chat bot persona/frills.

## Proposed phases

- **Phase A (the trust batch)**: 1 checkpoints + rollback, 4 claim
  verification, 9 notifications. — *"You can trust what it did."*
- **Phase B (the scale batch)**: 3 repo map, 2 test-fix loop, 12 bench
  expansion. — *"It works on real codebases, not demos."*
- **Phase C (the UX batch)**: 6 inline diffs + suggest mode, 8 image input,
  10 parallel sessions, TS migration from the earlier roadmap. — *"First-class
  to use."*
- **Phase D (depth)**: 5 CI integration, 7 worktrees, 11 refactor tools,
  13 dependency sweep, 14 trace upgrade.

## Open questions for the next grilling round

1. Checkpoints: shadow-copy store vs hidden git ref? Auto-rollback scope
   (single file vs whole batch)?
2. Test-fix loop: iteration cap default? Stop conditions besides green?
3. Suggest mode: should it replace the current auto-apply default, or be a
   per-session toggle?
4. Image input: which model path (DeepSeek vision vs GLM-5v)?
