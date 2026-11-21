# Changelog

## Unreleased

### Added

- **The map authors its own inputs (#376, R103)**: floorplan cannot know what a
  part of the codebase is for, so it expects three authored files ? and until now
  nothing wrote them, which is why `build.mjs` had nothing to draw.
  `src/codingdude/floorplan_inputs.py` writes all three from facts already on
  disk, in the map dir beside the scan (decision #107): `<map dir>/architecture.json` with
  one chip per directory that actually owns files, `<map dir>/descriptions/repo.json`
  quoting each Python module's own docstring, and `<map dir>/recent-work.json`
  listing the files `git status` reports as changed. The order is the design ?
  scan, then author, then build ? because the scan is the file list the builder
  assigns, so every glob is a measurement rather than a guess, and a path that
  claims no included file is refused before the build instead of warned about
  after it (`build.mjs` only warns, and the first probe of this feature shipped 5
  such paths with 30.5% of files unassigned). Names are the repository's own
  words and a directory summary is its `__init__.py` docstring or nothing at all,
  so the map never states a purpose nobody wrote. On this repo the whole thing
  now builds itself with 0 errors, 0 warnings and 0 unassigned files.

- **`map_query`: the map answers the agent too (#378, R103)**: `map_query(verb,
  query, kind)` wraps the CLI the builder generates into the map dir, so the same
  graph that draws the picture answers `overview`, `find`, `show` and `path` in
  one call instead of a search loop over the source. Read-only by construction,
  bounded, and capped with the truncation announced. The two ways it can be
  missing are separate answers: no map means "build one first", a map without its
  CLI means the payload changed shape ? sending a reader to rebuild something
  that already exists is a wild goose chase.

- **Human-in-the-loop repo map, foundation (#375, R103)**: the map comes from
  floorplan, an upstream node project that draws a repo map and never calls a
  model, so the integration is a process boundary rather than a
  re-implementation. `src/codingdude/floorplan.py` is that whole boundary at
  this stage: locate it (explicit path, then `CODINGDUDE_FLOORPLAN_HOME`, then
  the copy vendored at `vendor/floorplan`), run its scanner and builder with
  `--json --unattended` under a timeout, and hand back their receipts. The
  payload ships with the repo rather than resolving from a path, because a core
  surface must not be absent by default: `vendor/floorplan` is pinned to
  upstream commit 94f81b4, with a checksum file that a test re-hashes, so an
  upstream update cannot drift from its stated pin in silence. A missing copy, a
  missing node and a timeout are all readable reasons, never an escaping
  exception: the map is an aid, never a precondition for a run. Two shapes were
  measured rather than assumed - the `--json` receipt carries `counts` plus repo
  and skip lists, while the scan artifact it writes carries the graph - so sizes
  come from the graph and fall back to the receipt. Twenty tests; the
  integration one drives the real scanner over a fixture repo.

- **The map gets its own panel (#377, R103)**: a catalogue panel (`map`,
  `renderer: 'always'`) rather than an artifact card, and the reason is
  mechanical. floorplan's output is a JavaScript app - 2.6 MB with the ELK
  layout engine and the fonts inlined, so it loads nothing and works offline -
  while the Artifacts viewer runs every artifact under `sandbox=""`, scripts
  disabled. Widening that shared viewer to `allow-scripts` would hand script
  execution to every artifact ever emitted, including chat-authored HTML, so
  the map declares its own sandbox instead: `allow-scripts`, and deliberately
  not `allow-same-origin`, which leaves the frame on an opaque origin that
  cannot reach this app's DOM, storage or session cookie. The page is served by
  `GET /sessions/{id}/map` from `<config home>/maps/<slug>-<hash8>/` - the
  build's `index.html`, or the exported `<map dir>/index.export.html` beside it
  once that copy is current (#381) - the derived-state home (decision #107) rather than
  the project's own tree, so a build cannot dirty the repo it maps
  rather than carried as a payload - the artifacts endpoint is polled, so a
  payload route would re-serialize 2.6 MB continuously - with `no-cache` so a
  rebuild reaches the frame without a hard refresh, while `/map/state` answers
  "is there a map" in JSON because a sandboxed frame reports no load failure to
  its parent. Absent from `DEFAULT_PRESET` on purpose: reachable from the
  sidebar and the palette like graph/planning/notes, and a 2.6 MB page is not
  first-boot work.

- **Something can finally build the map (#379, R103)**: the panel could only ever
  say "not built" — `scan`, `build` and `available()` had no production caller at
  all, so its one action, *Check again*, re-asked a question whose answer could
  not change. `POST /sessions/{id}/map/build` now runs the scan and the build into
  the map dir, the empty state gains a **Build map** button that shows the receipt
  verbatim, and `map_build` gives the agent the same call so it can refresh the map
  before pointing a human at it. The route waits 20 s and then answers 202 rather
  than holding a request open for minutes on a large tree — the pair settles well
  inside that here (2.1 s + 1.0 s at 621 files), and when it does not, the build
  carries on while the panel polls `/map/state`, recording its outcome at
  `<map dir>/build.json` so a failure that finished after the request can still be
  explained. Status is 200 whatever the build did, because the reason *is* the
  payload — a non-2xx would make the panel render an exception instead of
  floorplan's own words. One build at a time per project (`<map dir>/build.lock`,
  409 on conflict), and a lock older than both timeouts is taken over rather than
  honoured, because a lock nobody releases would refuse every later build for
  ever. `/map/state` also reports `available`, `detail`, `running` and `build` now,
  so "node is not on PATH" is never rendered as "no map yet — expected `<path>`",
  and `available()` is the single answer to that question — the state route awaits
  it, so the panel and the adapter cannot disagree. Build warnings reach the page
  on both outcomes: each one names a field of `<map dir>/architecture.json` that
  matched no file, which is the only signal that the authored input is wrong.

### Fixed

- **The map panel showed a control that could never work (#381)**: floorplan's
  page carries an Ask bar that shells out to a `claude` or `codex` CLI, and these
  runs one neither — so the frame drew a permanently disabled strip reading
  "Asking is unavailable" across the bottom of the diagram, and every Ask
  affordance in its context menus led nowhere. The panel now serves the copy
  floorplan's *own* export path writes (`serve.mjs --export`, the code its Export
  button takes): `meta.exported` set, `body.exported` hides the bar, no engine
  detection, no `/api/ask` fetch. `map_frame_page()` prefers that copy and falls
  back to the built page when it is missing or not *provably* newer — a tie
  resolves to the build page, because coarse filesystem timestamps are not
  evidence the copy is current — so a rebuild whose copy failed, or whose copy
  landed in the same clock tick, cannot leave the frame showing the previous
  build while the panel says "built". `health` is
  deliberately left out of the copy: floorplan's health scan is heuristic and
  reports a HIGH "unprotected-endpoint" on routes that do carry
  `Depends(authorize)`, so the panel does not present a verdict we know to be
  wrong as ours. Measured on this repo: the copy costs 0.20s and is 2,651,445 B
  against the build's 2,655,620 B (it re-serialises flows, notes and recent
  work); rendered in the same browser at 1440x900, the Ask box is 700x127
  `display:flex` in the build against 0x0 `display:none` in the copy, with its
  input `disabled` in the former and enabled in the latter, 42 SVG layers and 0
  console errors on both. The placeholder string is *not* the discriminator and
  is not claimed as one: "Asking is unavailable" occurs twice in both files'
  source, and a placeholder is not innerText. It is written to a per-call
  sidecar and published with a retried `os.replace` — the frame may be holding
  the copy being replaced, and on Windows that refusal passes — and an empty
  copy is the same class of failure as a non-zero exit, so a failed or blank
  export cannot leave a truncated page that the frame would serve as newer than
  the build.

- **A panel could construct a React component instead of a Map (#380)**: the
  Graph panel's structure list calls `new Map()`, and the map panel's component
  was imported into the same file as `Map`, so that line constructed the
  component with no arguments and threw "Cannot destructure property 'sessionId'
  of 'undefined'" as soon as the list rendered. Invisible to the test suite ?
  `no-undef` is satisfied because the name is defined, and eslint's
  `no-redeclare` with `builtinGlobals` covers the global scope rather than a
  module's ? so it is pinned by scanning every module in `frontend/src` for an
  import binding that shadows a JavaScript built-in. The UI walk also stopped at
  the first crashing panel, which meant the architecture map was never opened:
  it now records the crash and keeps walking, and the designed boot 401 is no
  longer graded as a network failure. The walk walks 22 of 22 panels with no
  crashed tab and no catalogue drift.

- **Ten walkers were half a rule away from the truth (#374)**: `tools.skip_dir`
  is the shared answer to "is this directory outside the project?" — it covers
  `SKIP_DIRS` *and* the `.venv-*` side venvs *and* plain `venv`. Ten walkers
  asked the same question with `any(part in SKIP_DIRS ...)`, which holds
  neither, so third-party copies were read as project source: on this repo
  24,736 of 25,122 walked files. The damage is wrong answers, not just cost — a
  site-packages copy counts as a dependent of `tools.py`, its functions as
  project definitions, its imports as call-graph edges, its `.py` files as the
  language mix, and a newer file there reported the codegraph index stale. New
  `tools.skip_parts(rel, extra=..., keep=...)` is the parts-aware twin, and
  eighteen call sites across eleven modules were migrated: the seven modules the
  ticket listed (including *both* deadcode walkers — the second one had its own
  private set), `delegation._iter_target_files`, the two private bare-name
  copies in `onboarding.detect_conventions` and `codegraph_boot.index_is_stale`,
  the two server scans that special-cased the `.venv*` prefix by hand while
  still missing plain `venv`, and the Explorer tree fetch. A caller needing an
  extra subtree passes `extra=`; an *artifact* scan (renders, session files)
  passes `keep=ARTIFACT_KEEP` because a screenshot lands in `.scratch`. Each
  migrated walker has its own side-venv-decoy test in `tests/test_skip_rule.py`
  (33 tests), and a guard test fails if any module outside `tools.py` defines a
  SKIP* set again — the fork, not the individual site, is what the defect was.
- **The impact graph now sees relative imports (#373)**: `_py_imports_of` read
  `node.module` and dropped `node.level`, so `from .tools import X` resolved to
  `tools` and never matched `_module_name`'s `codingdude.tools`. Intra-package
  edges were therefore invisible whenever the package prefix was omitted — the
  house style here: 49 of 80 modules import relatively, only 16 carry an
  absolute sibling import. Resolution now takes the importing file's package
  (`_package_of`), walks `level` dots out (`_relative_base`, `None` when that
  climbs past the root, where the import is an ImportError rather than an edge)
  and treats `from . import x` as the submodule import Python performs. #371's
  text pre-filter moved with it: it keyed on the module's first dotted segment,
  which a relative import never spells (`from .b import V` contains `.b`, never
  `pkg`), so it would have silently dropped every dependent the fix adds — it
  now keys on last segments with identifier boundaries. Measured on this repo,
  `src/codingdude/tools.py`: 27 → 54 dependents (2 → 28 src-side), 0.62s → 0.37s
  median of three warm runs — the base side probed in a worktree at `8799569`,
  so the corpus and disk cache differ. The dependents are the finding; the
  wall clock tracks machine state, not this change.
- **The Diff panel loads again (#371)**: `GET /sessions/{id}/diff` never
  returned, so the panel sat on "loading…" for the life of a session — one of
  21 panels `tools/ui_smoke.py` photographs without content. The 30s bound on
  `git diff` was never the problem; `impact.impact_graph` re-walked the whole
  workdir on every call, including when nothing had changed. On this repo that
  was 104,435 directory entries per poll, and a session with a clean tree paid
  ~62s to prove the empty answer. Three cuts: an unchanged tree now returns
  before the walk; `os.walk` prunes with `tools.skip_dir` — the shared
  walker rule: `SKIP_DIRS` plus the `.venv-*` side venvs and plain `venv` —
  instead of walking into them and discarding every file (24,736 of this
  repo's 25,122 walked files were side-venv files); and a file is only
  `ast.parse`d when its
  text actually contains the changed module's name — a necessary condition, so
  dependents are identical. Measured on this repo: 62.34s → 0.00s for an
  unchanged tree, 61.24s → ~6s for one changed file. A hung `git diff` now
  answers 504 with a readable message the panel renders, instead of a 500
  traceback that carried none.

### Added

- **The claim gate now runs where a push must carry it (R62 follow-up)**: R62's
  failure-mode checker shipped with a limitation it named itself — nothing ran
  it at commit time, so it fired only when the agent remembered to run it, and
  never over the review evidence a push must carry. Two wires close that.
  `.githooks/commit-msg` runs the checker over every commit message (activate
  once per clone: `git config core.hooksPath .githooks`), and `record_review`
  now runs it over both review axes, so a failure-mode claim is refused until
  it carries `[probe: <command>]` or says "not yet verified". The hook uses the
  repo's `.venv` python rather than `uv run`, which syncs the environment; with
  no venv present it warns and fails open — a hook that blocks every commit on a
  fresh clone would be switched off, not obeyed.

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

- **A worker that finished is no longer reported as a crash (#369)**: live run
  `L_AssjFaqRA` landed 23 minutes of work (commit and review record both on
  disk) and the UI said `worker exited unexpectedly (code 1)`. The worker had
  exited non-zero *on purpose* — its socket died mid-run, so it could not
  deliver the terminal event and said so in its own log — but nothing read that
  log, and `except WebSocketDisconnect: pass` meant `server.log` held no
  ws-close line in its entire history. Three changes: the socket close is now
  logged with run id, close code, reason and `terminal_seen` (plus a 1011 hint,
  which is what uvicorn sends when its keepalive ping goes unanswered), the two
  close-without-accept paths (4401/4404) are logged instead of vanishing, and
  the reaper reads the worker log tail — when it says this run dropped its
  terminal, the RUN_ERROR reads "finished, but its terminal event was lost …
  the work is persisted" with no `stderr:` clause instead of quoting MCP banner
  bytes as a cause. The runs row becomes `interrupted` rather than `failed`
  (the value a cancelled run already uses for "ended without a delivered
  terminal"), because the work is on disk and calling that a failure is a claim
  nobody observed either. `serve()` also pins
  `ws_ping_interval`/`ws_ping_timeout` at 20s each, so the timeout that decides
  when a stalled worker loses its channel is a declared number rather than a
  framework default — and the worker log path now comes from `config_home()`
  instead of a hardcoded `~/.codingdude/logs`, so the server can actually find
  the file it is asked to read.

- **A wedged test still burned the whole job cap (#368, cause 2)**: R101 bounded
  each *job*, which capped the damage but not the diagnosis — a hung test sat
  until the 30-minute cap with nothing naming it, and the re-run that followed
  cost another 10-100 minutes. pytest now runs under `pytest-timeout` with
  `timeout = 180` in `pyproject.toml`, sized from the measured distribution of
  1500 tests (759s total; slowest single test 12.6s, 36.0s with a second suite
  running concurrently, so 5x the worst observed). Red-proofed by forcing the
  budget to 2s: the slowest test fails with a `Timeout` block and exit 1
  instead of passing. `tests/test_gates_parity.py` pins the setting so it
  cannot be silently deleted, and `timeout_method = "thread"` because
  signal-based timeouts do not exist on Windows.

- **The local gate and CI linted different targets (#368)**: `gates.bat`
  checked `src tests tools` while the `test` job checked `src tests bench.py`,
  so a `bench.py` edit passed every local gate and failed CI — a manufactured
  re-run, and the same shape as the trailing-whitespace incident in R101. Both
  now check `src tests tools bench.py`, and the same set was restated two more
  ways in prose: `CONTRIBUTING.md` and `docs/TECHNICAL-DESIGN-MANUAL.md` both
  said `src tests`. Those now point at `gates.bat` as the single definition
  instead of copying the command. `tests/test_gates_parity.py` failed before
  the fix, naming `tools` as local-only and `bench.py` as CI-only, and it fails
  if any live doc restates a different set.
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
  with a warning naming the failure. `container_running()` — the same kind of
  question, but with *no* timeout at all, so `sandbox_exec` against a wedged
  daemon hung rather than failing — takes the bounded path too, as do the three
  best-effort `rm -f` calls (stale-container clear on create, teardown, and the
  long-run lane's cleanup, which runs inside the worker). Those were the last
  docker calls outside the bound, so the invariant is now greppable rather than
  asserted. Thirteen tests pin it, including negative controls that a healthy
  linux daemon still reports `True`, that the probe still lets a clean answer
  through, that a running container is still seen, and that the removals still
  reach a healthy daemon.
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
