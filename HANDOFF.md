*Updated after commit (see git log). Main == origin/main, tree clean.*

## Handover — R46 CFG analysis done (agent + HITL)
- **#153 (`3575c3d`):** `analyze_control_flow(path, function?)` agent tool —
  `cfg.py::build_cfg_toolset`, attached in `plugins.build_all` next to the
  AST toolset. ModelRetry on bad path/function/escape. 5 tests
  (`tests/test_cfg_toolset.py`).
- **#154 (`c6a0f84`):** `GET /sessions/{sid}/cfg?path=&function=` — no
  `function` → `{functions: [...]}` picker payload; with it → blocks/edges
  (`reachable` flag). Frontend: `frontend/src/cfgView.ts` (`cfgMermaid`, 5
  tests) + Graph tab "control flow" section (function picker, green =
  reachable / red = dead, dead-count warning line).
- Gates run this session: pytest **618 passed/1 skipped**, ruff + mypy
  (63 files) clean, eslint clean, vitest **87/87**, vite build OK, dist
  rebuilt. Porcelain 0; HEAD == origin/main.
- Bounce required to serve the new endpoint + dist.
- Note: ROADMAP.md bookkeeping writes land *after* the work commit —
  commit it separately before claiming clean (bit me twice today).

## Previous state (R37-era, superseded)
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

## Handover — 2026-09-20 (R41 #92 full roster)
- Entire agency-agents tree distilled: +9 division checklists (finance-accounting, game-development, marketing-growth, product, security-compliance, qa-testing, gis-spatial, healthcare-regulated, business-operations). reference/checklists/ now has 22 files, all indexed + search-verified (CRS/reproject, server-authority, PHI, single-sourcing all hit).
- reference/ gitignored — checklists on disk only, not in git. Roadmap/handover committed and pushed.
- Next: #90 (surgical-patch scope discipline, in_progress), #91 (caveman-explore output levels), #93 (specialty-actions seam exposing these checklists to users).

## Handover — 2026-09-20 (R42 user-facing comprehension, #94/#95)
- Audience correction accepted: prior tickets were agent-introspective; R42 = human comprehension of generated code. #96 = process gate (state user value in every ticket).
- #94 shipped `1720941`: `src/codingdude/callgraph.py` (AST py / tree-sitter JS/TS, orphan = zero in/out degree, fails fast on bad file), `GET /sessions/{sid}/callgraph?path=` (workdir-contained, 422 on parse fail), frontend `callgraphMermaid` + Graph tab (Mermaid of active file).
- #95 shipped `525cc8b`: `src/codingdude/structure.py` (per-file symbol outlines, 200-file cap), `GET /sessions/{sid}/structure`; Graph tab shows collapsible structure overview when no file open.
- Gates: 555 pytest / 1 skipped, ruff+mypy (58 files) clean, eslint clean, vitest 49/49, vite build. Server healthy :8765 on `525cc8b`. Tree clean, main == origin/main.
- For refinement guidance: line numbers currently decorative in structure view; JS symbol lines are 0; no click-through from structure to editor; call graph is single-file only (no cross-file edges yet).

## Handover — 2026-09-20 (post-R42 review)
- Review of 9468136...HEAD complete (two-axis). 0 standards blockers; 1 spec blocker. All findings ticketed, none fixed yet — fixes are the next session's first work.
- #97 (🔴): orphan flagging inverted — orphan = total degree 0; should be in-degree 0 (never called). Dead-but-calling fns never flagged.
- #98: JS arrow/const fns invisible in call graph (no node + bogus self-edge) — frontend files graph as ~empty.
- #99: 422 readable errors swallowed by DockPanel poll catch; tab shows misleading "no callable symbols". Also catch UnicodeDecodeError server-side.
- #100: structure seam untested; _js_symbols re-parses repo_map display strings; duplicate tree descent in callgraph; inline untested structure render in App.jsx.
- Gates at review time: 555 pytest/1 skip, ruff+mypy clean, eslint clean, vitest 49/49, build ✓. Tree clean, main == origin/main @ da22f1f. Server healthy :8765 on 525cc8b.
- Next session order: #97 → #98 → #99 → #100 (all TDD, red-first), then update ROADMAP/handover.

## Handover — 2026-09-20 (AFK run: fixes + remaining tickets)
- #97-#100 review fixes shipped (orphan semantics, JS arrows, error surfacing, structure seam) — c6daa49, df5c6ca, c705f40, 900ac0f.
- #90 surgical-patch scope discipline: RED (43-line creep control) → GREEN (6-line patch, "Not done on purpose" section, traps table, Success Signal).
- #91 caveman-explore: Shapes A/B (evidence block + 3-level explanation) + mandatory `not inspected:` coverage line. RED→GREEN verified via delegation.
- #96 audience gate: AGENTS.md rule + project note 3 (Audience: human|agent, human first).
- #93 checklists as user-invokable runs: GET /checklists + /checklists/{name}; frontend checklists.ts (checklistTitle/checklistPrompt, TDD 4 tests); "checklist…" picker in chat composer sends an evidence-citing NEEDS WORK/PARTIAL/PASS audit run. Commit 1fda07a pushed.
- Gates: pytest 565/1 skip (one infra flake of test_interactive_approval_roundtrip, green on rerun), ruff+mypy clean, eslint clean, vitest 59/59, build ✓. R40/R41/R42 → done; ALL tickets closed.
- SERVER BOUNCE NEEDED to serve new dist + /checklists endpoints (last push @ 1fda07a).
- Fixture removal note: skillscope test scaffold committed then removed (922da08).

## Handover — 2026-09-20 (R43 wave 2: #101 + #102 shipped, bounce needed)
- Research: reference/research/human-code-comprehension.md (As-of 2026-09-20, indexed, gitignored). Top-5 shortlist → R43 tickets #101–#105.
- #101 shipped `5820a35`: build_module_graph(workdir) in callgraph.py — files as nodes, cross-file imports as edges (Python AST incl. relative/package resolution; JS/TS import specifiers with ext/index resolution); reuses _finish orphan flagging. GET /sessions/{sid}/archmap. Graph tab (no file open) renders the map via existing callgraphMermaid above the structure list. 7 new python tests.
- #102 shipped `9069b3f`: frontend/src/repoqa.ts buildRepoQuestionPrompt (4 vitest tests) — question grounded in structure+archmap, demands file+line citations, runs through the normal send() flow. Ask box in Graph tab; DockPanel gained onAsk prop.
- Gates: pytest 573/1 skip, ruff+mypy (58 files) clean, eslint clean, vitest 63/63, build ✓. main == origin/main @ 9069b3f.
- SERVER BOUNCE NEEDED (new dist + /archmap endpoint; last push @ 9069b3f).
- Remaining R43: #103 trust-my-tests report (S/M), #104 code tour of a run (M), #105 auto design doc/ADR (M/L).

## Handover — 2026-09-20 (R43 complete: #103/#104/#105)
- #103 `72fe6b7`: src/codingdude/trustreport.py build_trust_report (tests referencing a file via dotted-name match; hypothesis property-test flagging; honest empty evidence); GET /sessions/{sid}/trust?path=; "test evidence" panel under the call graph in Graph tab (⚠ no tests = red).
- #104 `4f65bd0`: frontend/src/tour.ts buildTour (run events → ordered narrative steps; handles EDIT_APPLIED-before-TOOL_CALL_END, unclosed calls, ISO+numeric ts); "tour of this run" list in Output tab.
- #105 `b7c5e1a`: frontend/src/designdoc.ts buildDesignDocPrompt (tour → ADR-drafting prompt, Context/Decision/Consequences); "draft design doc" button in Output tab sends through normal send() flow.
- R43 COMPLETE — all five tickets (#101–#105) done. Gates: pytest 576/1 skip, ruff+mypy (59 files) clean, eslint clean, vitest 70/70, build ✓. main == origin/main @ b7c5e1a, tree clean.
- SERVER BOUNCE NEEDED for #103 endpoint + new dist (trust panel, tour, design-doc button all appear after bounce).
## 2026-09-20 — #107 semantic search "found:nothing" (fixed, ef93c61)
### Post-Mortem
- **Timeline**: red repro 2.3s → isolated retrieval probe passed → engine probe showed checklist hits → fix same session.
- **Impact**: semantic_search returned reference docs / nothing in every new project since #106.
- **Contributing factors**: two index seams over one workdir (SemanticIndex + ReferenceStore) with no corpus ownership rule; "pre-existing at HEAD~1" verification was wrong (scaffold changes uncommitted in tree).
- **5 Whys**: found:nothing → code crowded out of top-5 → checklists indexed → scaffold seeds reference/ into workdir (#106) → no rule that reference/ belongs only to ReferenceStore.
- **Action items**: exclude+prune reference/ in SemanticIndex (done, ef93c61); corpus-ownership rule noted in module docstring (done). No open items.

## 2026-09-25 — #145 zombie ask/gate cards
- Terminal events (RUN_FINISHED/ERROR/CANCELLED) and stop() now clear last.ask/last.gate; runRef nulled on stop. Pure seam clearPendingPrompts in askUser.ts (+1 test).
- Gates: vitest 76/76, eslint clean, build OK. Commit 3d81ec1 pushed, tree clean.
- Bounce needed to serve new dist.

## 2026-09-25 — #146 spawn errors fed back to agent
- run_captured converts spawn failures (missing binary, WinError 206, OSError) into Captured(code=-1, stderr="spawn failed: ...") — every one of the 26 call sites now surfaces readable errors instead of aborting the run. Tool bodies remain covered by R25 ToolErrorFeedback -> ModelRetry.
- gh/audit toolsets updated to detect spawn-failure Captured and keep friendly "not installed" wording.
- Gates: 590 passed/1 skipped, ruff+mypy clean. Bounce needed to go live.

## 2026-09-25 — #147 durable pending ask/gate restore
- worker: ask_user_interaction/gate_interaction seam traces ASK_USER/GATE_REQUEST + RESOLVED markers (run_id stamped); run() wired to them.
- frontend: pending.ts pickPending pure seam (6 tests); reattach effect restores pending card for still-active runs; refresh no longer hides an open question.
- Gates: pytest 593/1 skip, ruff+mypy clean, eslint clean, vitest 82/82, build ok. Bounce to go live.

## 2026-09-25 — #148 run janitor (post-mortem + fix, caa3553)
- **Root cause (run -cnQwMpicBI, "bounce has completed", 11:16 UTC):** worker
  process died before executing ANY worker code (silent spawn failure 17s
  after server bounce; prompt file never consumed, zero log lines). The R31
  reaper was armed only in the worker-ws endpoint's finally — a worker that
  never connects arms nothing → no RUN_ERROR, runs row stuck 'running',
  UI waiting forever. Boot reconcile is the only other sweep and needs a bounce.
- **Fix:** `_run_janitor` (app startup task) sweeps channels: reaps exited
  workers (idempotent `_reap_worker`) regardless of ws lifecycle; terminates
  live workers that never connected ws within `_BOOT_TIMEOUT_S` (60s).
  `_reap_worker` now records terminal status on the runs row
  (`_terminal_status`: completed/cancelled/failed). `RunChannel` gained
  boot_seen/created/reaped; ws connect stamps boot_seen.
- Stuck row -cnQwMpicBI manually marked 'failed' in live DB.
- Gates: 599 passed/1 skipped (4m48s), ruff clean, mypy clean (62 files).
  Commit caa3553 pushed, tree clean, #148 closed.
- **BOUNCE NEEDED** for janitor to go live (also still serving pre-#147 dist).
- Process note: another edit_file ghost edit (import cleanup reported success,
  didn't persist — caught by ruff). Recurring seam, stay suspicious.
