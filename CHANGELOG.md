# Changelog

## Unreleased

### Added

- **Per-conversation trace recording (R100)**: tracing was all-or-nothing and
  unattributable — every span carried only pydantic-ai's own per-run
  `gen_ai.conversation.id`, a UUID7 no CodingDude surface knows, so "show me
  that conversation" had no answer. A `trace` checkbox beside `yolo` now
  decides recording per run (untouched = `[telemetry] enabled` decides), with a
  dot that turns amber when nothing is listening on the OTLP port — a
  `BatchSpanProcessor` drops spans on its own thread and the run still looks
  clean, so "recording is on" must not be the only signal. Every span now
  carries `codingdude.session_id`/`codingdude.run_id`, and a new **OTel Traces**
  panel groups one conversation's spans by `trace_id` with per-trace token and
  cost totals. It reads the store through the running viewer's JSON-RPC over the
  new `[telemetry] viewer_endpoint` (default `http://127.0.0.1:8000`) and never
  opens the DuckDB file, which the viewer holds locked as its single writer.

- **A trace viewer that is actually verified (R94-C follow-up)**: the manual
  documented OpenLIT as the collector and then admitted its dashboard had never
  been run against our spans. The OTel Desktop Viewer now leads instead — one
  executable, no Docker, receivers already on `4318`, UI on `:8000` — and the
  claim is measured rather than hoped: with `[telemetry]` enabled through the
  shipped `configure_tracing` → `OTLPSpanExporter`, one real `deepseek-flash`
  request stored `invoke_agent agent` and `chat deepseek-flash` with their
  `gen_ai.*` attributes (43 in / 12 out tokens). The manual also says plainly
  that the store holds prompts, outputs and instructions, since those
  attributes ride the spans. OpenLIT stays documented as the Docker
  alternative, still marked unverified for our spans specifically.

- **Hard spend ceilings on every agent call (R94-B)**: `[models] max_cost_usd` and
  `max_total_tokens`. Both are checked by pydantic-ai *before* the next request,
  so the request is refused instead of the spend being narrated afterwards. They
  reach every `agent.run()` inside the run — the main loop, the fix loop, the
  claims retry, the evaluator, the planning reviewer, the summariser, memory
  extraction, the claims auditor and the vision inspector — via one definition
  (`src/codingdude/limits.py`), with a guard test that fails if any of those
  seams stops passing its limits. Read them as a per-call ceiling: each
  `agent.run()` gets its own allowance, and the cumulative session figure remains
  the usage ledger behind `--budget`. Unset by default, so nothing changes until
  you configure one.
  `max_cost_usd` can only be enforced on a model pydantic-ai can price (it warns
  and enforces nothing otherwise); `max_total_tokens` always holds. A malformed
  value fails at load rather than silently becoming no cap.
- **Per-function delegation spans (R94-A)**: every delegation used to be
  `name='delegate'`, so a designer run and a coder run on different models were
  indistinguishable in any trace. Spans are now `delegate.<function>`
  (`delegate.designer`, `delegate.coder`, …; plain `delegate` when no function was
  requested), and `DELEGATION_COMPLETED` reports the same value so trace and event
  cannot drift apart.
- **OpenLIT documented as the trace viewer (R94-C)**: OpenLIT runs as a
  self-hosted OTLP receiver — no SDK, no new dependency, one config value, because
  `openlit.init()` competes with `logfire.instrument_pydantic_ai()` for the same
  hooks and the single global tracer provider. Its cost dashboard is documented as
  subordinate to the usage ledger. The export path gained its first end-to-end
  test: a span is asserted to reach a real collector at `/v1/traces`.
- **Delegation spends the session's budget (R93-A)**: a delegated run is handed
  the parent's usage accumulator, so its requests and tokens count against the
  run that caused them instead of vanishing. Its cap is the delegation slice
  (`used + [delegation].max_requests`, bounded by the session limit) rather than
  a fresh allowance per delegation. The operator kill switch is now observed at
  every tool boundary *inside* a delegation, not only between the parent's calls.
- **Tool output bounded at the source (R93-B)**: an oversized tool return is
  truncated where it is produced (80k chars → 40k head/tail) instead of arriving
  whole. Our own tools already self-cap; this bounds what MCP servers send.
  Cache-bust reporting from the provider's own numbers comes with it.
- **Local-OTLP tracing (R93-C)**: new `[telemetry]` table (`enabled`,
  `otlp_endpoint`, `service_name`). Traces go to a local collector only —
  `send_to_logfire=False`, no token, nothing off the machine — and every agent
  carries a name, so a failed run names the agent and request instead of
  requiring inference. Off by default; a missing collector never fails a run.
- **Pre-push review gate (R92)**: `git_push` refuses unless a recorded two-axis  review covers the exact diff being published. The record is content-addressed
  (`sha256` of the committed range plus the working tree), so amending or
  rebasing without changing the diff keeps it valid and fixing a finding voids
  it. `git push` through the shell is refused for the same reason, and the file
  tools refuse to touch the git directory, so a record cannot be fabricated by
  writing it. Post-push review stays as a failsafe.
- **Per-request context compaction (R91)**: a mechanical, LLM-free guard runs
  before every model request and compacts when the token estimate crosses the
  window threshold, instead of only at run start. A run can no longer grow until
  the provider rejects it with a context-length 400; the guard is fail-open, so
  a guard error degrades to sending the request rather than killing the run.
- **Prompt caching for every agent (R91)**: one resolution point turns config
  into pydantic-ai capabilities for the main loop, the fix-loop retry and the
  claims retry (conversation + retention) and for the one-shot agents
  (retention only). New `[models]` keys `prompt_cache`,
  `prompt_cache_messages`, `prompt_cache_settings`; unknown passthrough keys
  fail at load instead of being silently dropped.
- **Long runs (R80)**: `--long-run assisted|unattended` adds the sandbox lane,
  durable resume, structured evidence gate, evaluator loop, operator files, and
  a publish cycle that only ever pushes `codingdude/longrun-*` branches with
  draft PRs. Timeout auto-resume and lane bootstrap included.
- **Planning depth**: PRDs, technical designs, roadmap items and tickets with
  per-step evidence; function-tagged plan steps that phase-switch the session
  (`[models.functions.<name>]`); `delegate` sessions staffed by cognitive
  function with a registry-locked tool policy.
- **Wireframes (R85)**: screen-design packs, a flow map, inline DSL editing and
  implement handoff, rendered by the wireloom grammar.
- **Model tooling (R81/R86)**: per-run model picker in the composer, live model
  list fetch for OpenAI-compatible providers, custom `[providers.*]` tables.
- **Editor reveal (R69)**: `reveal_code` opens a file in the editor at the cited
  lines; chat citations are clickable.
- **Kickoff prompts (R71)**: every session's first turn rides an executed
  orientation block, overridable per project with `[kickoff]`.
- **Tech designs get a `delivered` state (#352)**: the ladder was
  `draft` → `approved` → `superseded`, so a design whose work shipped read
  `draft` — "not yet agreed" — because neither `approved` (agreed, unbuilt) nor
  `superseded` (replaced) says it was built. Same fix PRDs received in #351,
  including a per-status colour in the Planning panel so `delivered` and
  `superseded` cannot render alike. Existing databases are rebuilt in place;
  ids, bodies and `prd_id` links carry over.

### Changed

- **The codegraph boot no longer waits behind the previous turn's tail (#301)**:
  boot (project scaffold + index sync, both subprocess calls) ran inline on the
  event loop *after* the post-run drain, so its time was added to the tail's
  wall clock and the loop was blocked for its duration. It now runs on a worker
  thread, concurrently with the drain. The first-run onboarding decision stayed
  ordered the way it was — after the drain — because the tail writes the memory
  it reads.
- **`[delegation] max_cost_usd` is a ceiling, not a receipt (R94-B)**: it used to
  append "(note: delegation cost … exceeded the configured cap)" *after* the money
  was spent. It now translates into a real `cost_limit` slice (`already spent +
  allowance`, min'd with the run's limit), and the abort message names the limit
  that fired.
- pydantic-ai 2.66 → 2.68 and `pydantic-ai-harness` 0.68 added (R93-B). The
  harness pins the core version exactly, so this is one move. Note for anyone
  with a live server: the venv moves on the next `uv sync`.
- `main` is protected and changes land through PRs with CI (R73/R74); issue and
  PR templates plus a Contributor Covenant code of conduct are in the repo.
- `github-mcp-server.exe` is no longer vendored; `setup-codingdude.bat` fetches
  the upstream release (R74).
- The user manual is split into pages under `docs/manual/` (R70).
- Trace deltas are coalesced by default with a full-detail toggle (R79).
- Usage is tagged by cognitive function, so the Cost panel breaks spend down by
  function as well as by model.

### Fixed

- **One slow Docker daemon could take down the whole test job (#368)**:
  `docker_usable()` ran `docker version`/`docker info` under a 30s timeout and
  caught nothing, so an unhealthy daemon escaped as `TimeoutExpired` instead of
  the `False` its callers are written against; `container_image_ready()` then
  made two *unbounded* calls (`image inspect`, `pull`). Because
  `tests/test_sandbox.py` probed at import time, that exception aborted
  collection of the entire suite — a docs-only PR went red in 62s without
  running a single test. Every docker query now goes through one bounded
  `_docker_probe()` returning `None` on `TimeoutExpired`/`OSError`, an
  unanswerable inspect no longer falls through to a pull that would hang
  against the same dead daemon, and the import-time probe degrades to a skip
  with a warning naming the failure. `container_running()` - the same kind of
  question, but with *no* timeout at all, so `sandbox_exec` against a wedged
  daemon hung rather than failing - takes the bounded path too. Nine tests pin
  it, including negative controls that a healthy linux daemon still reports
  `True`, that the probe still lets a clean answer through, and that a running
  container is still seen.
- **A wedged CI runner blocked a required check for 78 minutes (R101)**: no job
  declared `timeout-minutes`, so a `test` job that stopped emitting at 67% sat
  against GitHub's 6-hour default while the PR's merge state read BLOCKED — not a
  failing check, an absent verdict. The command itself was healthy: the same
  `uv run pytest -q` passed locally in 671s and the job re-ran green in 11m14s.
  `test` now declares 30 minutes, `frontend` 15 and `bench` 10, each sized from
  its observed worst case and stated with those numbers in
  `docs/GITHUB-STRATEGY.md`, so a wedge fails in bounded time and is re-run
  instead of diagnosed by cancellation.
- **Three of the four agent entry points recorded nothing (#361)**: tracing was
  configured in one line inside `worker.run()`, so review mode (`--review`),
  headless runs and the eval replay — all real agent runs, the first two among
  the most expensive — emitted no spans at all, and the OTel Traces panel would
  insist no review had ever run. The call now lives at the engine's two
  executing entry points, `Engine.run` and `Engine.review`, where the session id
  the run writes to actually exists (headless and the replay mint theirs inside
  `_ensure_session`, which is why a worker-side call could never attribute
  them); the worker forwards its `--telemetry` choice instead of acting on it.
  The eval replay opts out explicitly with `telemetry=False` — it drives a
  scripted model, so its token counts are invented and must not enter a store
  read as real spend. Known gap, recorded rather than hidden: a review spawned
  from a conversation whose switch is off still follows `[telemetry] enabled`,
  because `POST /sessions/{id}/review` carries no telemetry field.
- **A stale bundle could not announce itself (#363)**: the built frontend was
  served with no `Cache-Control` at all, so `index.html` — the only file that
  names the content-hashed assets — fell back to heuristic caching. A pinned
  copy kept requesting asset filenames that no longer existed after a rebuild,
  and the footer read `ui <old sha>` while `/health` reported the current one;
  nothing short of clearing site data brought them back together. The mount now
  states the policy: files under `assets/` are `public, max-age=31536000,
  immutable`, everything else is `no-cache`, so a reload costs one 304.
- **A build made from a dirty tree called itself a clean commit (#364)**:
  `vite.config.js` stamped `git rev-parse --short HEAD` without asking whether
  the working tree matched it, so a bundle containing uncommitted code
  advertised the commit it was based on and looked identical to a clean build of
  that commit. The stamp now reads `<sha>-dirty` when `git status --porcelain`
  is non-empty, and `unknown` with a build warning instead of a silent empty
  string when git cannot be run.
- **The "never open the store" rule was prose only (#362)**: `codingdude.otel`
  reads the OTel DuckDB file exclusively through the running viewer's JSON-RPC,
  because DuckDB is single-writer and the viewer holds the lock — but nothing
  tested that, and with duckdb not installed a direct `connect` would have
  surfaced as a missing package rather than a broken invariant. A meta-path
  watcher now records any `import duckdb` while the read path executes, and the
  module source is parsed for import statements naming it, so either
  regression fails the suite.
- **The pre-push review could not finish a large diff (R92/R94-B)**: the reviewer
  pass was capped at a fixed 8 model requests, so a multi-file branch exhausted
  them before reaching a verdict and the gate reported the diff UNREVIEWED. The
  budget now follows the work — `limits.review_request_limit`, floor 8 plus two
  requests per changed file and two per plan step, ceiling 120 (one request per
  file plus the floor up to 56 files) — so a large review finishes and
  a small one stays cheap.
- Delegated spend was counted twice: a delegation's requests and tokens sat in
  both its own usage row and the run's row (the shared accumulator made both
  true at once), so the session total — and the Budget Cap that reads it —
  double-counted every delegation and would halt at roughly half the real
  spend. The two rows now partition the spend, and checkpoints order by a
  per-session sequence rather than a filesystem timestamp (`st_ctime` is
  inode-change time on POSIX, and capturing into an older checkpoint bumps it).
- A malformed `[telemetry] enabled` value (quoted `"false"`) no longer stops a
  worker at boot; like a malformed endpoint it logs once and leaves tracing off.
  A missing `pydantic-ai-harness` degrades to the history guard instead of
  failing every agent build.
- Provider context-length 400 that killed runs mid-session (the per-request
  guard above); the claims retry was the last path that could still overshoot.
- Artifacts panel crash on SSE deltas after a card was replaced (R87).
- `ask_user` payloads are validated at the tool boundary and the UI card can no
  longer take down the workspace; a malformed payload gets a readable
  `ModelRetry` instead of a React error (R90).
- Reviewer sub-agent now runs with repository tools and a prompt it can act on;
  it used to answer without file access (R90).
- `show:` panel deep-links no longer bury the editor in a merged dock group
  (R89).
- Run-failure visibility: worker stderr is captured and surfaced, MCP pre-flight
  blocks a run that cannot reach its servers, and `repo_map`/`arch_lint` were
  moved off the critical path (R76/R77).
- Navigation no longer grows the page (it scrolls internally), floating groups
  are clamped on screen, and the dock no longer produces a phantom scrollbar
  (R67/R88).

### Security

- Dependency advisories cleared across Python and npm trees; doMPurify pinned
  (R66).
- Constant-time token comparisons on the auth seams; mermaid renders with
  `securityLevel: 'strict'`; `gh` calls resolve through `shutil.which` with an
  argv list, no shell (R66).
- Security gate (Bandit + Semgrep + secret regexes) fails closed on a finding.

## 0.4.0 — 2026-09-21

Analysis hardening (R47) + codebase hygiene sweep.

### Added
- Security gate (#155): Bandit + secret regexes + bundled Semgrep rules, ModelRetry, fails closed
- Mutation testing trustreport (#156): mutmut-backed survived-mutant evidence
- On-demand cProfile (`profile_code` tool, #158) and A/B micro-bench (`compare_bench`, #160)
- Hypothesis API fuzzing (`fuzz_api` tool, #159)
- `resolve_workdir_file`: shared containment-checked file resolution for the analysis tools
- `setup-codingdude.bat`: one-shot setup that installs everything (uv, deps, Semgrep CLI, frontend build)

### Changed
- Contract docstrings on all public store/engine/server symbols (arch-lint clean)
- `utc_now_iso` is the single canonical timestamp helper (was duplicated in 6 modules)
- Dead `next_target`/`body_tail` parameters removed from the CFG builder

### Fixed
- UI version badge showed 0.3.0 after the bump: the frontend bakes `__APP_VERSION__ = package.json version` into the bundle at build time (vite `define`). Release rule: after bumping the version, run `npm run build` and ship the rebuilt `frontend/dist/` — a stale bundle keeps reporting the old version. Backend `__version__` is now derived from installed package metadata, pinned by `tests/test_version.py` (single source: pyproject.toml)

## 0.3.0 — 2026-09-09

Modernization completion (WS-C/E/F/G/H remainder).

### Added
- Trace viewer tab: replay every traced event of a session (gates, terminals, tool calls)
- `run_coverage` agent tool: pytest-cov execution with per-file missing-line report
- `find_unused_exports` agent tool: knip integration for JS/TS projects (uses project devDependencies, never auto-installs)
- `find_dead_code` agent tool: vulture (Python) + tree-sitter (JS/TS) unused-symbol detection
- On-demand code review: Diff-tab "Run review" button → reviewer findings
- Design tokens: brand palette defined as Tailwind @theme aliases
- Typed API layer (`api.ts`) with generated-style event/response models — first step of the TS migration
- Memory extraction wired into the worker (cheap-model post-session fact banking)
- Binary gates/terminals now land in the JSONL trace

### Changed
- `emerald-*` accent classes swept to `brand-*` tokens

### Fixed
- review refactor shared between plan-completion and on-demand flows

## 0.2.0 — 2026-09-08

Uber-agent layer (tickets 18–22) + modernization pass (WS-A–H).

### Added
- Directives: `~/.codingdude/DIRECTIVES.md` injected into every run (project AGENT.md as second layer), budget-capped, gate-protected edits
- Skills: SKILL.md registry (global + project), progressive disclosure via `load_skill`, seed skills (tdd, code-review, debugging)
- Planning mode: `propose_plan` → approval card → tracked steps (`update_step`) → automatic review pass with findings fed back to the model
- MCP client: global + per-project `mcp.json` merge, disable/enable, MCP tab in the UI
- Semantic search: injectable embedder, hash-cached file index, `semantic_search` tool, similarity-ranked memory
- Budget Cap: per-session spend limit, hard stop, survives `--yolo` (exit 3)
- Observability: per-session JSONL run traces; versioned prompt files (`prompts/*.md`)
- Web: login flow (HttpOnly session cookie, stable password in `~/.codingdude/server-token`), plan/review/findings cards, live Diff/Files/Cost/Memory/MCP panels

### Changed
- Shell/git subprocesses are now async and run with scrubbed environments (no secret env vars)
- Terminal panel delegates to the tool timeline; grep enforces per-file size caps

### Fixed
- Approval-card freeze (TOOL_CALL_START raced GATE_REQUEST and cleared the card)
- Stop leaking worker processes when the browser's event stream dropped
- /api prefix 405 when FastAPI serves the built frontend
- Empty sessions left behind by failed runs

### Engineering
- CI workflow (ruff + mypy + pytest + scripted bench), ruff lint clean, error taxonomy (`errors.py`), structured logging, gold-task benchmark (`bench.py`, `--live` for real models)
