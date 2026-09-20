*Updated after commit a2e8db5 (pushed). Main == origin/main, tree clean.*

## Current state
- **#83 / R37 CLOSED (`a2e8db5`):** selection AI actions in the editor.
  Highlight code in the Monaco editor -> toolbar appears under the editor
  (Explain / Fix / Optimise / Improve + clear). Click sends a scoped agent
  prompt (directive + file path + verbatim snippet, with "read the file for
  context first") through the normal `send()` run flow. Seams: pure
  `frontend/src/aiActions.ts` (`ACTIONS`, `buildActionPrompt` — 5 vitest
  tests), `CodeEditor` `onSelectionChange` prop, `EditorPane` action bar +
  new `onAsk` prop wired to App's `send`.
- Gates: vitest 34/34, eslint clean, vite build OK (dist rebuilt — hard
  refresh browser to see it).
- Tracker fully clean: all tickets + R1-R37 done.

## MUST DO after bounce
- Nothing mandatory. Clear to start fresh work.

## Open roadmap
- All roadmap items R1–R35 done. Remaining is the backlog: H7
  streaming-vs-usage, orphan toolsets guard, `engine.run` decomposition,
  Trace/Sidebar/Standards polish, R1 vision half, delete stale
  `reference/` pydantic-ai copy, R35 leftovers #75/#77 (run output in IDE
  shell).

## Known accepted gaps
- Post-push review loop is directive-driven, not a hard-enforced pipeline.
- Vision pixel gate has no live end-to-end check.
- Explorer rail width not user-resizable (deferred decision).

## Environment notes
- Windows 11, project at G:/pydantic, venv ./.venv/Scripts/.
- Gates: ./.venv/Scripts/python.exe -m pytest -q; ruff check src tests;
  python -m mypy src; frontend: cd frontend && npx vitest run && npm run build.
- WSL git uses Windows GCM for credentials - push works from agent shell
  (git push origin main, ~seconds). Docker CLI: use docker.exe from WSL.
- tools.py and other files are CRLF - preserve; the edit tool keeps
  normalizing some files to LF, restore CRLF pre-commit when diff explodes.
- HANDOFF.md must stay UTF-8 (this file was once cp1252 and blocked edits).

## Process reminders
- TDD red-first at pre-agreed seams; full gates before any done claim.
- Every user message means continue-the-work; user says proceed/afk -> keep
  going without re-asking. Bounce = delivery mechanism, not a new task.
- ALWAYS leave handover notes (update this file) before ending a session.
- Keep ROADMAP.md statuses in sync when closing items; ticket tool closes
  record the closing commit.

## Handover 2025-09-19 (e082906)
- Orphan-toolsets guard shipped: `rename_symbol` + `worktree_create` now gate
  through the approval policy (deny → ModelRetry, headless → GateRequired) and
  `rename_symbol` emits `EDIT_APPLIED kind:'rename'` per modified file
  (trace/checkpoints/UI see mass renames). `build_refactor_toolset(workdir,
  approvals, on_edit)`; wired via `ctx.on_edit` in plugins `build_all`.
- Backlog item "vendored reference/ deletion" done earlier this session
  (259MB freed); `ReferenceStore._prune_deleted()` keeps the index honest.
- Gates: 531 passed/1 skipped; ruff + mypy clean; pushed, tree clean.
- Remaining backlog: `engine.run` decomposition, H7 streaming-vs-usage,
  R1 vision half.

## Handover (10aa393)
- #81 done: fix-loop token accounting. Bug: loop billed each retry inline AND
  finalize re-billed the final result (double-billed last retry, main run's
  requests never billed). Fix: `_run_fix_loop` returns (result, usages);
  `telemetry.sum_usages` combines; `record_run_usage(usage=...)` bills once.
- TDD: `test_fix_loop_bills_every_request_exactly_once` (red vs old code,
  verified via git stash) + `test_sum_usages_adds_requests_tokens_and_costs`.
- Gates: 533 passed/1 skipped (4m09s), ruff clean (after autofix import
  order), mypy clean (54 files). Pushed `10aa393`, tree clean.
- Next in R36: #82 vision half (engine-side image passing).

## Handover (#82)
- R1 vision half done: `vision.build_run_prompt(prompt, image_path)` is the
  message-build seam (plain str | [str, BinaryContent]; fails fast on missing
  file / non-image suffix). `_assemble_agent` uses it; runs emit
  IMAGE_ATTACHED. Tests: tests/test_vision_prompt.py (4).
- Gates: 537 passed/1 skipped (3m20s), ruff clean, mypy 54 files clean.
- R36 now fully done (#80/#81/#82). Roadmap: close R36; next backlog is open.

## Handover (41500f8) — R38 Visual aids complete
- All 3 phases shipped: #84 run waterfall (DockPanel span timeline, pure
  `waterfall.ts` buildSpans, LIFO pairing + sort by start); #85 semantic
  change summary in Diff tab (`changesummary.ts`, astdiff symbols, Py ast +
  tree-sitter JS/TS); #86 Mermaid impact graph in Diff tab (`impact.py`
  reverse-dep edges via stdlib ast / import regex, `impact.ts` pure builder,
  server /diff now returns `impact`).
- Gates: ruff clean, mypy 56 files clean, vitest 45/45, eslint clean,
  vite build OK, dist rebuilt. Pushed `41500f8`, tree clean, main==origin/main.
- Known flake: test_interactive_approval_roundtrip timed out in one combined
  run, passed standalone — infra timing, watch for recurrence.
- Research doc: reference/research/agent-activity-visualization.md (indexed).
- Roadmap: R38 done. No open tickets. Next: pick new work from a clean baseline.

## Handover — R39 skill rigor upgrades (from agency-agents review)
- Researched msitarzewski/agency-agents (persona-prompt library). Adopted 4 ideas, rejected persona theatre/roster sprawl.
- R39 done, tickets #87/#88/#89 closed:
  - #87 diagnosing-bugs: added "Hypothesis timebox" (~15 min probe cap, cheapest killing test first) + "Phase 6: Post-mortem" (required Timeline/Impact/Contributing factors/5 Whys/Action items). TDD: red (untrained agent blessed 50-min sunk cost, prose-only wrap-up) → green (full template compliance).
  - #88 code-review: "Output contract" — 🔴/🟡/💭 markers matching ticket triage, one-pass complete feedback, red flags for drip-feeding. Red→green verified.
  - #89 writing-skills: skeleton gains required "Success Signal" section (observable compliance check) + checklist item. Red→green verified.
- Skills edited in C:/Users/norma/.codingdude/skills/ (not a git repo — no commit possible there). Scratch patch scripts deleted.
- ROADMAP.md R39→done committed with this handover.

## Handover — 2026-09-20 (R41 #92)
- R40 logged: #90 surgical-patch scope discipline (Minimal Change Engineer), #91 caveman-explore three-level output. #90 in_progress, not started.
- R41 #92 DONE: 13 checklists in reference/checklists/ (api, backend, cost-finops, data-eng, database, dev-exp, devops, frontend, i18n, incident-response, llm-app, payments, security-privacy). Format: As-of + source URLs + Use when + Checklist + Failure modes + Rejected. Indexed + search-verified. reference/ is gitignored — files live on disk only, not in git.
- Skipped with reasons (recorded in #92): mobile×2, multi-agent-architect, 4 already-adopted personas.
- Lesson: delegated write=true agents' sandbox writes did NOT land on disk (reported success falsely); sub-agents also couldn't see files created after session start. Distill heavy work in main session or verify delegated writes with real reads.
- #93 (specialty-actions seam) next after #90/#91. Gates not run (no code changed); ROADMAP committed c16d018, pushed, tree clean, main == origin/main.
