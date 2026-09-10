# CodingDude Self-Review — Issues & Improvements

Scope: full source review of `src/codingdude/**`, `tests/**`, `frontend/src/**`, `bench.py`, and supporting config/docs.
Method: static inspection cross-checked against the spec (`.scratch/codingdude/spec.md`), ADRs (`docs/adr/`), and the existing test suite. Python/ruff/mypy could not be executed in the review environment, so findings are from code reading plus the existing tests.

Severity legend:

- **Critical** — approval/security bypass, path escape, or cross-project data leak.
- **High** — broken feature, wrong result, or a latent correctness/safety bug in a shipped path.
- **Medium** — real bug or fragility with narrower impact.
- **Low / Improvement** — cleanup, maintainability, or hardening suggestion.

---

## Summary

| Severity | Count |
|---|---|
| Critical | 5 |
| High | 9 |
| Medium | 14 |
| Low / Improvement | 11 |

---

## Critical

### C1. `find` is auto-approved, enabling un-gated `find -delete` / `find -exec`

- **Where:** `src/codingdude/approvals.py` (`AUTO_SHELL`, line ~26)
- **Problem:** `AUTO_SHELL` matches `find` as a read-only convenience. `find` is not read-only: `find . -delete` deletes files and `find . -exec rm -rf {} \;` executes arbitrary commands, yet both start with `find` and therefore run with no Approval.
- **Impact:** The "destructive filesystem operations are always-gated" guarantee (ADR-0004) is bypassable with an auto-approved command. This is the most serious approval-tier hole found.
- **Fix:** Remove `find` from `AUTO_SHELL`, or auto-approve only a safe form (e.g. `find . -maxdepth N -type f -name ... -print`) and route anything with `-exec`/`-delete`/`-ok` to `DENIED`.

### C2. Pattern Approval uses only the leading token, and `ALWAYS_GATED` is not comprehensive

- **Where:** `src/codingdude/approvals.py` (`ALWAYS_GATED`, `pattern_for`, `decide`)
- **Problem:** A Pattern Approval for a command stores only `command.strip().split()[0]`. Approving `npm test` for the session unlocks every `npm` command, including remote mutations such as `npm publish`, `npm unpublish`, or `npm access grant`. The `ALWAYS_GATED` regex only lists a handful of commands (`git push`, `gh pr|repo|release|api`, `rm`, etc.), so many destructive/remote commands fall into `NEEDS_GATE` and become pattern-unlockable.
- **Impact:** Pattern Approval is intended to cover "all future actions matching a pattern" such as `pytest`, but in practice it can cover `npm publish` or `curl <exfil>` after a single "approve all matching" click. Combined with C1/C3 this materially weakens the approval model.
- **Fix:** Use multi-token command families for patterns (e.g. `npm test` rather than `npm`), add an explicit deny-list for publish/push/apply/delete verbs, and/or make always-gated classification verb-based and provider-aware.

### C3. `--fix-loop` pre-approves `python` (and any leading token in the test command)

- **Where:** `src/codingdude/engine.py`, `run()` lines ~280-285
- **Problem:**
  ```python
  for base in test_command.split():
      if base not in ('-', 'q'):
          approvals.patterns.add(base)
  approvals.patterns.add(test_command)
  ```
  If `test_command = "python -m pytest"`, this adds `python` as a session pattern. `decide()` then auto-approves **any** command beginning with `python`, including `python -c 'import shutil; shutil.rmtree(...)'`, `python -m http.server`, or an exfiltration one-liner.
- **Impact:** Enabling the fix-until-green mode can silently auto-approve arbitrary code execution.
- **Fix:** Pre-approve the exact command (or a tightly scoped token such as `pytest` only when the command *is* pytest), never a broad interpreter token like `python`, `bash`, `node`, or `ruby`.

### C4. AST tools do not enforce the Workdir boundary

- **Where:** `src/codingdude/ast_tools.py` (`_check_python`, `_python_files`, `find_definition`, `find_references`)
- **Problem:** Unlike `tools.resolve()`, the AST tools resolve `path` without a containment check. `path='../../other-project'` can target files/directories outside the Workdir. For an outside directory, `_python_files` yields outside files and `f.relative_to(workdir)` raises an unhandled `ValueError`; for an outside file, `_check_python` passes it and then `relative_to` raises. Either way it is a crash and/or a containment violation rather than a clean `ModelRetry`.
- **Impact:** The hard "file tools refuse paths outside the Workdir" boundary (spec story 2) is not enforced by the AST navigation tools.
- **Fix:** Route all AST paths through the same `resolve_workdir_path` / `resolve()` containment logic used by `tools.py`, and return `ModelRetry` for escapes.

### C5. `SemanticIndex.search` leaks results across Workdirs

- **Where:** `src/codingdude/semantic.py`, `SemanticIndex.search()` line ~85
- **Problem:** `index_workdir()` stores rows by *relative* path only, and `search()` queries the whole `embeddings` table:
  ```python
  rows = self.db._conn.execute('SELECT path, vector FROM embeddings').fetchall()
  ```
  There is no workdir scope column or filter. Two projects with `src/app.py` overwrite each other (`ON CONFLICT(path)`), and semantic search in project A can return paths from project B.
- **Impact:** Cross-project information disclosure and wrong search results; the per-Workdir isolation that Sessions promise is broken for semantic search.
- **Fix:** Add a `workdir` column (or use absolute paths) to `embeddings`, filter by `workdir` in `search()`, and clean up stale rows on reindex.

---

## High

### H1. Image input is wired up but non-functional end-to-end

- **Where:** `src/codingdude/engine.py` (`run`, lines ~244-246 and ~393-400), `src/codingdude/worker.py` (`run`, line ~174), `src/codingdude/config.py` (`ModelLineup.vision`), `src/codingdude/server.py` (`start_run`, line ~205)
- **Problem:** `engine.run()` only switches to a vision model when *both* `image_path` and `vision_model` are provided. No caller ever provides `vision_model`, and `config.models.vision` has no readers. The worker passes `image_path` but not `vision_model`, so binary image content is sent to the configured text model (`deepseek-v4-pro`). The server also hardcodes the uploaded file as `.png`, so a JPEG is labeled as PNG in `engine.run`.
- **Impact:** The screenshot/image-input feature fails or misroutes images to a text-only model.
- **Fix:** Resolve `vision_model` from `config.models.vision` in the worker (and/or engine) and pass it through; preserve the uploaded file's real media type instead of forcing `.png`.

### H2. Git and coverage tools are attached even when `approvals is None`, then crash on gated calls

- **Where:** `src/codingdude/engine.py`, `run()` lines ~298-299
- **Problem:**
  ```python
  toolsets.append(build_git_toolset(workdir, approvals))
  toolsets.append(build_coverage_toolset(workdir, approvals))
  ```
  runs unconditionally. When `approvals` is `None` (the default `engine.run(...)` path), `git_commit`, `git_branch`, `git_push`, `gh_pr_create`, `gh_pr_view`, and `run_coverage` call `policy.decide(...)` and raise `AttributeError` (`'NoneType' object has no attribute 'decide'`). The tools are still advertised to the model.
- **Impact:** Any `engine.run()` without an `ApprovalPolicy` can crash if the model invokes one of these tools. Read-only git tools happen to work, which hides the issue in smoke tests.
- **Fix:** Only attach git/coverage tools when `approvals is not None`, or make `_gate`/`run_coverage` treat `None` as "no gates" / `GateRequired` explicitly.

### H3. `run_coverage` interpolates `source` into a shell command without escaping

- **Where:** `src/codingdude/tools.py`, `build_coverage_toolset.run_coverage()` line ~360
- **Problem:**
  ```python
  command = f'python -m pytest --cov={source} --cov-report=term-missing -q'
  ...
  await asyncio.create_subprocess_exec('bash', '-c', command, ...)
  ```
  `source` comes straight from the model. A value like `.; rm -rf /` executes two commands. Because the tool is gated like shell, the gate partially mitigates this, but the gate is showing the composed string and approval/`--yolo` still runs it.
- **Impact:** Command-injection risk inside a gated tool; also `bash -c` is always used even on PowerShell projects.
- **Fix:** Pass arguments as an `argv` list (no `bash -c`), validate `source` is a relative path under the Workdir, and honor the configured shell.

### H4. `.codingdude.toml` project shell override is parsed with the wrong shape

- **Where:** `src/codingdude/config.py`, `load_project_config()` lines ~119-128
- **Problem:** The documented format (issue 04) is top-level `shell = "powershell"`:
  ```toml
  shell = "powershell"
  ```
  The code does `raw.get('shell', {})`, then checks `'shell' in raw.get('shell', {})`. With the documented top-level string this is `'shell' in "powershell"` → `False`, so it returns `{}`. With a `[shell] default = "powershell"` table (matching global config) it also returns `{}`. The only shape that works is the undocumented `[shell]\nshell = "powershell"`.
- **Impact:** The per-project PowerShell option (spec story 8) silently does nothing for the documented configuration.
- **Fix:** Accept both `shell = "powershell"` (top-level string) and `[shell] default = "powershell"`; return the value consistently.

### H5. JS/TS dead-code analysis suppresses references inside function bodies

- **Where:** `src/codingdude/deadcode.py`, `_tree_sitter_definitions_and_refs()` lines ~46-70
- **Problem:** The `in_definition` flag is set on entering a function/class and never reset for siblings, so **all** identifiers inside a definition body are skipped:
  ```python
  if node.type in (... function/class ...):
      ...
      in_definition = True
  if node.type == 'identifier' and not in_definition:
      referenced.add(...)
  ```
  A function that is called only from inside another function's body is never counted as referenced, so it is reported dead.
- **Impact:** `find_dead_code` produces false "dead code" findings for normal JS/TS code. The current test only calls `keepMe()` at top level and does not catch this.
- **Fix:** Only suppress the definition's own name, not the whole subtree (e.g. pass a flag that is scoped to the name node, or check `node is name_node` explicitly).

### H6. Headless plan abort leaves an `approved` plan in the database

- **Where:** `src/codingdude/planning.py`, `PlanStore.create()` line ~28 and `propose_plan()` lines ~115-135
- **Problem:** `create()` hardcodes `status = 'approved'` in SQL. When a headless run has no `ask` callback, `propose_plan()` raises `GateRequired` after creating the row, so the aborted run's plan remains `approved` in the DB even though it was never approved.
- **Impact:** The UI can later show an approved plan for an aborted run, and `update_step` could operate on it if the session resumes.
- **Fix:** Insert plans as `proposed`, transition to `approved` only after approval, and mark `aborted`/`rejected` on `GateRequired`.

### H7. Usage/budget under-counts all auxiliary model calls

- **Where:** `src/codingdude/engine.py` (`run`, `_maybe_compact`, `_extract_memory`, `_verify_claims`), `src/codingdude/planning.py` (`_review_impl`)
- **Problem:** `record_usage()` is only called once for the final `result.usage` of the main run. Not billed to the session:
  - compaction summarizer (`_maybe_compact`),
  - every fix-loop retry except the last,
  - memory extraction (`_extract_memory`),
  - claim verification and its retry (`_verify_claims`),
  - plan review (`_review_impl`),
  - subagent delegation calls.
  `_check_budget()` is only called before and after the main run, so the budget cap is not a hard stop during these sub-runs.
- **Impact:** The cost meter is wrong and the Budget Cap can be exceeded by significant spend in sub-runs.
- **Fix:** Record usage per sub-run into a shared usage accumulator, and check budget between iterations/auxiliary calls.

### H8. Non-streaming runs do not persist history incrementally

- **Where:** `src/codingdude/engine.py`, `run()` non-streaming path (line ~405 vs streaming persist at ~603)
- **Problem:** Only `_run_streaming` persists incremental snapshots (`persist(run.all_messages())` when a tool-call node is reached). The non-streaming path (`agent.run(...)`) persists only at the end. A crash/stop/kill before completion loses the entire in-flight exchange.
- **Impact:** Headless runs and any non-streaming execution lose work on interruption, contradicting the "Session resumption covers crash recovery" story (ADR-0002/0003).
- **Fix:** Use a streaming/iterating agent path (or a callback) for every run so history is snapshotted after each model/tool turn.

### H9. String model override is silently ignored

- **Where:** `src/codingdude/engine.py`, `run()` line ~244
- **Problem:**
  ```python
  resolved = model if isinstance(model, Model) else self.build_model()
  ```
  If `model` is a `str` (a supported signature per `build_model(main: Model | str)` and `run(model: Model | str)`), it is discarded and the configured `models.main` is used instead.
- **Impact:** Callers passing a string model name get the default model with no error.
- **Fix:** Call `self.build_model(main=model)` (or `infer_model(model)`) when `model` is a string.

---

## Medium

### M1. `build_toolset.resolve()` compares against the unresolved Workdir

- **Where:** `src/codingdude/tools.py`, `resolve()` lines ~52-59
- **Problem:** `target.relative_to(workdir)` is called with the original `workdir` Path, not `workdir.resolve()`. If the Workdir path contains a symlinked parent (common for `/tmp` on macOS), legitimate paths raise "outside the Workdir."
- **Fix:** Compare against `workdir.resolve()`.

### M2. `glob` bypasses the `resolve()` containment check

- **Where:** `src/codingdude/tools.py`, `glob()` line ~100
- **Problem:** `glob` uses `workdir.glob(pattern)` directly instead of `resolve()`. Pathlib glob behavior with `..` and absolute patterns can vary by version; this is the one file tool not routed through the shared containment boundary.
- **Fix:** Normalize the pattern/root through the same containment-checked resolver and verify escape attempts are refused.

### M3. `OUTSIDE_WORKDIR` regex has a broken Windows-tilde alternative and weak absolute-path detection

- **Where:** `src/codingdude/approvals.py`, lines ~35-38
- **Problem:** `~\\\\` in a raw string matches a tilde followed by two literal backslashes, not the intended Windows `~\` path. The Windows drive-letter branch only matches `X:\\` but not `X:/`, and the Unix branch misses many absolute paths.
- **Impact:** Outside-Workdir shell commands are detected on a best-effort basis, but the Windows patterns are essentially dead, making an already-heuristic check weaker than intended.
- **Fix:** Use a dedicated path parser or at least correct the regex (`~[\\/]`, `(?:[A-Za-z]:[\\/])`, `/` prefix handling).

### M4. Server token is exposed in worker process arguments

- **Where:** `src/codingdude/server.py`, `start_run()` line ~182
- **Problem:** The bearer token is embedded in the worker's `--server ws://...?token=...` command line, so it is visible in `ps`/Process Explorer to other local users.
- **Impact:** The localhost+token security boundary leaks the token via process listings.
- **Fix:** Pass the token to the worker via environment variable or stdin instead of argv.

### M5. `run_ws` allows `testclient` regardless of `allow_testclient`

- **Where:** `src/codingdude/server.py`, `run_ws()` line ~569
- **Problem:** `host not in ('127.0.0.1', '::1', 'testclient')` always allows the `testclient` host, while `authorize` and `run_events` only allow it when `allow_testclient=True`.
- **Impact:** Inconsistent auth policy; a test-only host bypass is present in the WebSocket path.
- **Fix:** Use the same conditional tuple as the other auth paths.

### M6. `delete_session` orphans `plans` rows and there is no migration story

- **Where:** `src/codingdude/db.py`, `delete_session()` line ~179 and schema
- **Problem:** `delete_session` deletes `messages`, `approvals`, and `usage`, but not `plans` (or anything else referencing `session_id`). The schema only uses `CREATE TABLE IF NOT EXISTS`, so existing databases never get columns/constraints added.
- **Impact:** Orphaned plan rows and no upgrade path for schema changes (e.g. the workdir-scoped embeddings fix in C5).
- **Fix:** Add cascades / explicit deletes for all child tables, and introduce a `user_version`-based migration step.

### M7. MCP config failures crash a run instead of degrading gracefully

- **Where:** `src/codingdude/mcp_config.py`, `load_merged_mcp_toolsets()` / `merged_mcp_config()`
- **Problem:** Malformed `mcp.json` raises `json.JSONDecodeError`, and `load_mcp_toolsets()` failures propagate. `engine.run()` calls `toolsets.extend(load_merged_mcp_toolsets(...))` without a `try/except`.
- **Impact:** A single bad MCP config file prevents all runs.
- **Fix:** Catch and warn (or disable the offending server) so MCP configuration can never brick the engine.

### M8. A globally disabled MCP server cannot be re-enabled from the project config

- **Where:** `src/codingdude/mcp_config.py`, `merged_mcp_config()` and `set_mcp_disabled()`
- **Problem:** `merged_mcp_config` unions the global and project `disabled` lists, so a server disabled globally remains disabled even if the project sets `disabled=false`. `set_mcp_disabled(name, disabled=False)` only removes it from the project list.
- **Impact:** The UI's enable button appears to work (project file is written) but the server stays disabled.
- **Fix:** Model enable/disable as a per-server override, not a union (project wins per server name, including enablement).

### M9. Claim-verification retry is never persisted to session history

- **Where:** `src/codingdude/engine.py`, `_verify_claims()` lines ~624-668
- **Problem:** The retry agent's messages/tool results are used only to emit `CLAIMS_ADDRESSED`; they are not written back to the session, and the original `result.output` is returned. If the retry actually runs commands or fixes files, that exchange is missing from history.
- **Impact:** Session history is inconsistent after a verification retry.
- **Fix:** Persist the retry messages (or rerun through the normal persist path) and return the corrected output when appropriate.

### M10. Shell/coverage/fix-loop hardcode `bash` on Windows

- **Where:** `src/codingdude/tools.py` (`run_coverage`), `src/codingdude/engine.py` (`fix_loop` test run)
- **Problem:** `run_coverage` and the fix-loop test runner always execute `bash -c`, ignoring the configured `shell.default` (`powershell`) that `build_shell_toolset` otherwise honors.
- **Impact:** On PowerShell-only Windows setups these tools fail.
- **Fix:** Route through the same shell resolution as `build_shell_toolset`.

### M11. Frontend: Chat Revert uses the wrong index

- **Where:** `frontend/src/App.jsx`, `Chat()` `m.edits.map((ed, i) => ...)`
- **Problem:** The inner `i` (edit index) shadows the outer message index, and `onEditRevert(i, ed)` passes the edit index where a message index is expected. `App.onEditRevert(msgIndex, edit)` then filters edits on the wrong message.
- **Impact:** Revert can remove the wrong edit or fail; the Architecture Review already flagged this as a crash path.
- **Fix:** Rename the inner variable and pass the outer message index (e.g. `onEditRevert(msgIndex, ed)`).

### M12. Frontend: duplicated `editSkill`/`saveSkill`/`deleteSkill` and reference to undefined state setter

- **Where:** `frontend/src/App.jsx`, `RightPanel()` (two definitions of each function)
- **Problem:** A first set of `editSkill`/`saveSkill`/`deleteSkill` is defined before the Standards state and references `setSkillSaved`, which is never defined. A second set later shadows the first. The dead first set is confusing and would crash if the later definitions were removed.
- **Fix:** Delete the duplicate first set and keep a single implementation.

### M13. TypeScript support is declared but unused; TS files are parsed with the JS grammar

- **Where:** `pyproject.toml` (`tree-sitter-typescript`), `src/codingdude/repo_map.py`, `deadcode.py`, `refactor.py` (all import only `tree_sitter_javascript`)
- **Problem:** `.ts`/`.tsx` files are processed with the JavaScript parser, so TS-only syntax (types, interfaces, generics) may not parse correctly. `tree-sitter-typescript` is a dependency with zero readers.
- **Fix:** Use the TypeScript grammar for `.ts`/`.tsx`, or drop the unused dependency.

### M14. Several implemented toolsets are never attached to the agent

- **Where:** `src/codingdude/engine.py` (`run()` toolset assembly)
- **Problem:** These builders exist and are tested directly but are not included in `engine.run()`:
  - `build_worktree_toolset` (`worktrees.py`)
  - `build_knip_toolset`, `build_ci_toolset`, `build_audit_toolset` (`tools.py`)
  - `build_repo_map_toolset` (`repo_map.py`)
  - `build_refactor_toolset` (`refactor.py`)
- **Impact:** Features documented as shipped (dependency audit, worktree isolation, rename/refactor, etc.) are unreachable from real runs; the toolset surface is inconsistent and untestable as a whole.
- **Fix:** Build a single toolset registry and attach every intended toolset (or explicitly deprecate/remove the orphans).

---

## Low / Improvement

### L1. `Engine.run()` is a god-method with ~34 deferred imports
`run()` handles session creation, model resolution, instruction assembly, compaction, toolset wiring, streaming dispatch, fix-loop, usage, memory extraction, and claim verification in one body. Split it into prepare/assemble/execute/post-process phases over a `RunContext`.

### L2. `_run_streaming` depends on pydantic-ai private internals
`from pydantic_ai._agent_graph import CallToolsNode` is a private API and will break across pydantic-ai upgrades. Prefer the public iteration API.

### L3. `scrubbed_env()` markers are overbroad and the `SYSTEMROOT` clause is redundant
`SECRET_MARKERS = ('KEY', 'TOKEN', ...)` removes any env var whose name contains `KEY`/`TOKEN` (e.g. harmless vars), and `SYSTEMROOT` is already preserved by the first condition. Consider an exact-name/allowlist approach (the ADR already lists this as future hardening).

### L4. `load_config()` crashes on malformed `config.toml`
A `TOMLDecodeError` propagates and the CLI dies with a traceback rather than falling back to defaults with a warning.

### L5. `rewind_to` does not remove later checkpoints
`rewind_to` creates a safety checkpoint and restores the target, but the later checkpoints remain listed, which is confusing for "undo all later checkpoints."

### L6. `refactor._js_replace` renames every identifier, including object keys/properties
The JS rename path replaces all `identifier` nodes named `old`, including `obj.old` property accesses and object literal keys. Use definition/reference analysis (already present in `deadcode.py`) instead.

### L7. `cosine()` in `semantic.py` returns a dot product, not cosine similarity
There is no normalization. It works with `FakeEmbedder` (which normalizes) but will rank incorrectly if a provider returns unnormalized embeddings.

### L8. `SkillRegistry._scan` silently ignores non-JSON frontmatter
The parser only handles `json.loads(...)` before the first blank line. The common `---\nname: ...\n---` frontmatter style is silently skipped. Support YAML frontmatter or document the exact JSON format.

### L9. `cli.main` has a no-op statement
`if args.fix_loop: args.fix_loop = True` does nothing (`src/codingdude/cli.py` line ~97). Remove it or make it do the intended work.

### L10. `tests/helpers.py` has a duplicated `return` statement
The `scripted()` builder ends with the same `return FunctionModel(...)` twice. The second is unreachable.

### L11. Frontend history reload drops tool/edit events
`App.loadMessages()` only maps `user-prompt` and `text/response` parts, so a resumed session shows none of the tool calls, edits, gates, or review findings until a new run streams events. Persist/derive those from stored messages or the trace.

---

## Positive notes

- The engine seam is genuinely testable: `FunctionModel`-driven tests exercise real file/search/edit/git tools and are the right shape for this codebase.
- The approval tier concept, per-run worker isolation, localhost+token server, Budget Cap surviving `--yolo`, and checkpoint-before-edit model are all sound architectural choices.
- `resolve_workdir_path` (server file access) correctly resolves both sides before the containment check — it should be the template for the other path tools (C4/M1/M2).
- The existing test suite covers many happy paths and several abuse cases (outside-Workdir read, gate aborts, always-gated push/PR, MCP echo). The main gaps are the negative cases for the issues above.

---

## Suggested fix priority

1. **C1, C2, C3** — approval-tier holes (`find`, leading-token patterns, fix-loop pre-approval).
2. **C4, C5** — Workdir/scope containment for AST and semantic tools.
3. **H1–H4, H7, H8** — broken image path, gated-tool `None` crash, coverage injection, project shell config, usage/history accounting.
4. **H5, H6, H9** — correctness of dead-code, planning status, and string model overrides.
5. Then the Medium list, then the Low/Improvement cleanups.
