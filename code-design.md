# Code Design Notes

## #212 — user-defined providers (any OpenAI-compatible endpoint)

**Problem:** provider names were hardcoded (deepseek/zai/github) in config,
API, verification, and UI; users could not add providers or select between
them at runtime.

**Design:**
- `ProviderDef` (config.py): `{api_key?, base_url?, env_var?}`; stored as
  `[providers.<name>]` tables in config.toml; legacy string shorthand kept.
- Key resolution: `provider_effective_key(name, def)` — env var
  (`env_var` or legacy name or `<NAME>_API_KEY`) wins over stored `api_key`;
  `apply_provider_keys` setdefaults it into the environment at load.
- Model resolution (`engine._model_from_name(name, base_url, providers)`):
  1) prefix matches a provider def with `base_url` → `OpenAIChatModel` on
     `AsyncOpenAI(base_url)` (works for any OpenAI-compatible API);
  2) `zai:` + `fallback_base_url` → dedicated ZaiModel (coding-plan endpoint);
  3) else pydantic-ai `infer_model` (all native providers).
- Validation relaxed: any `x:y` model ref is accepted (ModelLineupIn).
- API: `models_payload` adds `provider_defs` (base_url/env_var, no secrets)
  and `provider_prefixes` (suggestion list); `save_provider_keys` accepts
  per-entry string (key), table (full def merge), or null (delete);
  SECRET_MASK sentinel contract unchanged. `/models` also returns
  `provider_prefixes` for the run composer.
- Verify: generic per-provider smoke against its base_url; legacy trio keep
  default endpoints; no-base_url providers report `ok: null` "not tested".
- UI: Config tab renders dynamic provider rows (key/base_url/env_var,
  clear/remove) + add row; lineup fields get a provider-prefix datalist;
  run composer model selector now sends real `provider:model` strings
  (previously sent slot names, which never resolved).

**Impact:** config.py, engine.py, worker.py, server.py, App.jsx, README.
Config loads per run — provider changes apply from the next run, no bounce.

**Fail-safe:** unknown provider-table shapes warn+skip; bad PUT payloads are
validated before any write; `provider_effective_key` falls back to
`'not-set'` key so construction errors surface at run time, not boot.

## PRDs & Tech Designs — general planning docs (DB-backed, UI-surfaced)

**Problem:** planning surface had roadmap/tickets/decisions but no
requirements (WHAT/WHY) or technical-design (HOW) artifacts; agents jumped
from conversation straight to tickets.

**Design (user-chosen: DB-backed like tickets, surfaced in web UI):**
- Schema (db.py, additive): `prds` (status draft|active|sunset) and
  `tech_designs` (status draft|approved|superseded, optional `prd_id` FK-ish
  link for requirements traceability). Both workdir-scoped.
- RoadmapStore: list/create/update/delete for prds + designs; constants
  PRD_STATUSES / DESIGN_STATUSES.
- Agent tools (build_roadmap_toolset): create_prd/read_prd/update_prd,
  create_tech_design/read_tech_design/update_tech_design; list_planning now
  shows PRDs and Tech designs sections. Approved designs are superseded,
  never rewritten (tool docstring states this).
- Server: GET /planning returns prds+designs; POST/PUT/DELETE
  /planning/prds[/{id}] and /planning/designs[/{id}], mirroring decisions
  endpoints (422 on bad status, 404 on unknown id).
- Frontend: Prd/TechDesign types + api methods; Planning tab gets PRDs and
  Tech designs sections with status selects and add-kind options.
- Skills (general, in .codingdude-seed/skills): `prd` (WHAT/WHY doc,
  REQ-<n> numbering, mandatory Non-Goals + Open Questions, feeds roadmap/
  tickets) and `tech-design` (HOW doc, REQ traceability table, alternatives,
  supersedes-not-rewrites, hard trade-offs still go to record_decision).
  Positioned explicitly against to-spec/grilling/grill-with-docs.

**Impact:** additive schema (CREATE TABLE IF NOT EXISTS — no migration
needed); /planning response gains two keys (frontend tolerates absence via
optional chaining); no existing tool signatures changed.

## GitHub issue auto-mirror (R53) — convention enforced in code

**Problem:** the dual-logging convention (local planning item first, then a
mirrored GitHub issue) lived only in agent memory/skills; sessions drifted
and backfills were needed repeatedly.

**Design:** enforcement moved into the store, not agent discipline.
- `gh_mirror.py` (new): `GitHubMirror` — best-effort `gh` CLI boundary.
  Availability probed once per process per workdir (gh on PATH, github.com
  origin remote, gh auth ok), cached at class level. `create_issue` parses
  the issue number from the returned URL; `close_done` closes as completed
  and applies the green `done` label (label ensured once). Every failure
  logs one line and returns None/False — never raises, never blocks.
- `db.py`: additive `gh_mirror` mapping table (workdir, kind
  ticket|roadmap, local_id, issue_number) so closes reach the right issue.
- `roadmap.py`: `RoadmapStore(db, mirror=None)` — create_ticket and
  create_roadmap_item (DB rows) mirror on create; update_ticket/update_
  roadmap_item mirror-close on `done`. The agent toolset md-path
  (ROADMAP.md items) mirrors too, keyed by R-id. Single choke point covers
  agent tools, server endpoints, and execution.py ticket closes.
- `config.py`: `[planning] github_mirror` (default true) disables the
  mirror entirely.

**Impact:** additive schema + new module; no existing tool signatures
changed; local writes unaffected when gh/GitHub is unavailable (skips with
one log line). Tests mock the gh boundary (FakeMirror) — no network.

## Docker install-path verification (R56)

**Problem:** setup scripts (`setup-codingdude.bat`, `gates.bat`) were only
ever exercised on the dev Windows machine; unverified whether the pinned
lockfile, package build, frontend build, home seeding, and server boot all
work from a bare machine.

**Design:** `docker/Dockerfile.verify` — python:3.12-slim + uv + Node.
Build: `docker build -t codingdude-verify -f docker/Dockerfile.verify .`
(context trimmed by `.dockerignore`: no .git, caches, .venv,
node_modules, dist, DBs, logs). Installs the Linux equivalent of setup:
`uv sync --frozen`, then `npm ci && npm run build`; boots
`codingdude.cli serve`. Gates (ruff/pytest/mypy) run
interactively (`docker run codingdude-verify uv run pytest -q`) because
full pytest OOM-kills the default docker build sandbox. Semgrep is not
installed in the image, so the in-container security gate runs in its
degraded bandit/regex mode (as setup-codingdude.bat warns when semgrep
is absent).

**Verified findings (2026-10):**
- `uv sync` needs the full source (incl. README.md) — no pre-source
  dependency-only layer is possible with the uv-build backend.
- ruff clean; mypy reports 2 Linux-only typeshed false positives
  (restart.py Windows `creationflags`, code correctly `os.name`-guarded).
- pytest: 765 passed / 9 failed / 7 skipped — all 9 failures
  platform-specific (docker CLI absent in container, `gh` stub path,
  Windows process-tree semantics in restart/run-captured tests).
- Server boots on Linux, seeds `~/.codingdude`, `/health` ok (v0.4.0),
  serves the freshly built UI (logo + JS/CSS assets 200). Server binds
  127.0.0.1 by design, so health is checked via
  `docker exec <name> curl -sf http://127.0.0.1:8765/health`.

**Impact:** additive `docker/Dockerfile.verify` + `.dockerignore`; no source
changes. Genuinely Windows-only setup steps (winget gh, github-mcp.exe)
don't apply on Linux by design; codegraph (`npm i -g`) is
platform-independent but was not installed in the verify image.

## Stale artifact expiry (R58) — retiring orphaned choice/spec cards

**Problem:** `ArtifactStore.emit_choice_card` / `emit_spec_block` write a row
with `status='pending'`; the chat card and the Artifacts tab render every
row that is not `answered`. Nothing retires a card when its run is stopped,
crashes, or simply ends unanswered, so dead cards accumulate and reappear at
every boot (7 found on the remote install, 2026-09-28 → 2026-10-10). The
only way to clear one from the UI was to pick a bogus option, which then
wrote a fake answer into decision history.

**Design:** add a terminal state rather than reusing `answered` — a
dismissed card recorded no answer, and inventing one corrupts the audit
trail. Dismissal is **user-driven only**: nothing expires a card
automatically, because silently hiding a question the user has not read
yet is worse than a stale card.
- `artifacts.py`: `dismiss(artifact_id)` → `status='dismissed'` (KeyError on
  unknown id, ValueError if already terminal); `respond()` raises
  ValueError on a dismissed artifact so a stale card cannot be resurrected.
  `feedback()` is unchanged — it already returns None for any status other
  than `answered`, so the agent's replacement sees nothing.
- `server.py`: `POST /artifacts/{artifact_id}/dismiss` (404 unknown, 422
  non-pending), mirroring the respond endpoint. `start_run` deliberately
  does *not* sweep pending cards.
- `App.jsx`: dismiss button on each pending card in the chat column and in
  the Artifacts tab; choice buttons disabled for any non-pending status and
  a dismissed spec block renders its markdown read-only.
- `artifacts.ts`: unchanged — `pendingArtifacts` already filters
  `status === 'pending'`, so dismissed rows never surface in chat.

**Impact:** no schema change (status is a free-text column; the SSE `watch`
loop emits its `answered` delta for any status transition, so dismissal
propagates live). Existing `answered` cards are untouched, and re-answering
an `answered` card stays allowed — only `dismissed` is closed. Not covered
by design: a card is not auto-retired when its worker dies mid-run; the
user dismisses it (or answers it, which still works if the run is alive).

## R59 — Dynamic dockable workspace (P0: frontend decomposition)

**Goal.** Users arrange panels themselves (drag to split/merge/float, popout,
persisted layout). Engine: `dockview-react` 8.6.1, MIT, pinned exactly — see
tech design #1 and design decision #94. P0 is the prerequisite: `App.jsx` was
a 3288-line monolith, and docking needs each surface to be an independently
mountable panel.

**P0 structure** (`frontend/src/`, move-only — no behaviour change):

| Module | Contents |
|---|---|
| `ui.jsx` | `Mermaid`, build constants (`UI_VERSION`/`UI_BUILD`/`UI_SHA`), `shortStamp` |
| `chrome/` | `ErrorBoundary` (imported by `main.jsx`), `Login`, `Sidebar`, `AgentStrip`, `StatusFooter` — the surfaces that stay fixed |
| `cards/chatCards.jsx` | `ToolTimeline`, `EditBlock`, `AskUserCard`, `PendingArtifactCard`, `ApprovalCard`, `PlanCard` |
| `store/useFileWorkspace.js` | shared tab/draft/dirty/diff state |
| `panels/` | `Explorer` (TreeNode + FileTree), `Editor` (EditorPane), `Chat`, `Prompt` |
| `panels/dock/` | `Terminal`, `Notes`, `Artifacts`, `ModelsConfig` (+`CfgTextField`/`CfgNumField`), `Planning`, `Standards`, `Diff` (`DiffPanel`) |

**Why `cards/` groups six components in one file:** they share one lifecycle —
they appear mid-run and settle with the run — and the codebase already
precedent-sets this in `CodeEditor.jsx` (exports `CodeEditor` + `CodeDiff`).

**Deliberate remainder.** `Graph`, `Output`, `Waterfall`, `Trace`, `Cost`,
`MCP`, `Renders`, `Processes` and `Memory` stay inline in `DockPanel`. Eight
of those nine read its single shared poll through `data`/`setData` (`selRun`
belongs to `Output` and `Waterfall` only). The exception is `Processes`, which
renders the `processes` prop from App's own 3 s poll. `Memory` is the ninth —
*added* inline by #228, and it polls like the rest. Extracting them move-only
would thread those props through more files — work P2's data store deletes.
They move in P2, each with its own visible-subscriber subscription. (Two
earlier drafts of this paragraph got the count wrong — first "all eight read
the poll via `selRun`", then "seven read the poll". The branches in `DockPanel`
are the source of truth: eight poll, `Processes` does not.)

**Impact.** `App.jsx` 3288 → 1337 lines (historical: P0's count, not today's) and now holds only `DockPanel` plus
`App` (session/SSE state machine + layout). No API, DB, or behaviour change.
Tests do not touch `App.jsx` (all 91 cover pure `src/*.ts` helpers), so the
gates are `npm run build`, `eslint src`, and a manual visual parity pass —
documented in `RESCUE.md`, which is the recovery sheet for this refactor.
Two pre-existing gaps found during P0 were **left alone by P0 (move-only) and
then fixed under their own tickets**: the `Processes` tab body was unreachable
(`Processes` missing from the `tabs` array — #227) and `Memory` polled
`/memory` with no body branch (plus it was gated on a session it does not
need — #228). Both are behaviour changes, so they are separate commits from
the move-only ones and both got a full build/lint/91-test pass.

**UI smoke gate.** `tools/ui_smoke.py` renders the running bundle in Chromium
and walks all 16 dock tabs, failing on an ErrorBoundary crash, an uncaught page
error, a missing tab, or a leftover placeholder. It exists because nothing in
`frontend/src/*.test.ts` imports `App.jsx` — the build and the tests cannot see
a component that renders nothing. It found two further defects:
`Memory` mapped the entire table (2,144 rows → 15,822 DOM nodes rebuilt every
4s poll; now newest 200 at 2,226 nodes — #229) and the chat composer said
"create or select a session first" whenever disabled, including mid-run when a
session *is* selected (now cause-specific — #230).

**Post-push review fixes (#231 and the gate itself).** Reviewing the pushed
range found the gate weaker than `RESCUE.md` claimed and one more instance of
the #228 class:

- `DockPanel`'s poll ended in `catch { /* transient */ }`, so a failing
  `/usage` or MCP fetch was invisible *and* left the tab on the "select a
  session" placeholder — the exact symptom #228 fixed for `Memory`, still live
  on `Cost` and `MCP`. This is the repo rule "no silent catches" applied where
  it was violated.
- **The first fix for it was too narrow, and the review of the fix said so.**
  It rendered the error only in the shared fallback, so it reached the two tabs
  it named and nothing else: `Diff`, `Graph`, `Trace`, `Artifacts`, `Renders`
  kept stale or empty bodies with no reason given, and `Config`/`Memory` had
  their own keys (`configError`, `memoryError`) that the poll never populated —
  `configError` was reachable only on the no-session path, `memoryError` the
  same. The error was also stamped with nothing but a tab name, so it could
  follow the user to another session. The design is one surface for the *poll*:
  `pollErrors[tab] = {sessionId, message}` written by every failing fetch in
  `DockPanel`'s poll and cleared once per successful poll; a single banner
  renders it for whichever tab is on screen, and `body` is suppressed while it
  shows so a panel cannot pair "could not load this tab" with "loading…"
  underneath. `configError` and `memoryError` are gone, and `ModelsConfig` lost
  its error branch with them. The helpers live in `frontend/src/pollErrors.ts`
  with tests — no vitest file imports `App.jsx`, so anything left inside it is
  untestable by construction.
  What this deliberately does not cover, checked rather than assumed: `Graph`
  keeps `graphError`/`cfgError` for the selected file (they are per-file detail
  in the body, not poll state), and the self-fetching panels — `Notes`,
  `Standards`, `Terminal` — still swallow their own fetch failures and cannot
  reach the banner (#234). "Every failing fetch" would be an overclaim; "every
  failing poll" is what the code does.
  The lesson recorded: fixing the instance a review named is not the same as
  fixing the class, and the class here was "per-tab error state that only some
  branches rendered".
- The gate never failed on `console_errors` (collected, never read), asserted
  the placeholder without knowing whether a session existed (spuriously red on
  a fresh workspace, and it only passed before because this workspace has
  sessions), waited on `networkidle` while an `EventSource` is always open, and
  duplicated the tab list as a second source of truth. It now gates unexpected
  console errors (the designed auth 401 and resource-load failures are
  reported, not fatal), queries `/api/sessions` for the workdir to decide
  whether the placeholder is legal, waits for the dock element instead of
  network idle, and compares `DOCK_TABS` against `const tabs` in `App.jsx` so
  drift fails. The per-tab settle went 900 ms → 2 s: `/memory` is ~800 KB of
  JSON, and a shorter wait photographed "loading…" and called it a rendered
  tab. Review of that fix found the remaining hole: a data tab that failed
  rendered its own error text, which is neither the placeholder nor a console
  error, so a genuine 500 still passed. The gate now also fails on any `/api/`
  response with a 5xx status and on the presence of the dock's error banner
  (`[data-poll-error]`) — one hook and one attribute, rather than trusting each
  tab to look broken in a way the gate recognises.
- **Logged, not fixed** (#232): `refreshKey` is declared, passed to
  `DockPanel`, and never read — `setRefreshKey` is never called. Pre-existing
  (identical at `0c2e58e`), inert, and worth a decision rather than a silent
  deletion: the dock already refetches on `activePath`, so the prop is
  redundant rather than broken.

### R59 P1 — the dock shell behind `?layout=dock` (#236)

`dockview-react` 8.6.1 (exact pin, `"dockview-react": "8.6.1"`; it pulls
`dockview` 8.6.1, which re-exports `dockview-core`) is now installed and a
second shell renders five dockable panels. The classic flexbox layout is still
the default: `?layout=dock` opts in, so both can be compared in one browser and
rollback is flipping a query parameter.

**Files.**

| Module | Contents |
|---|---|
| `workspace/catalogue.ts` | `PANELS` (the five shipped panels), `DEFAULT_PRESET` (placements), `panelSpec`/`isKnownPanel` |
| `workspace/catalogue.test.ts` | 13 tests: registry integrity, preset references, geometry parity with `PANE_SPECS` |
| `workspace/Workspace.jsx` | `Workspace` shell, the five panel components, preset application, watermark with "Reset layout" |
| `App.jsx` | `USE_DOCK` flag + prop bags shared by both shells |
| `index.css` | `--dv-*` → `--ss-*` theme mapping |
| `tools/ui_smoke.py` | `--layout dock` walk (see below) |

**Decisions and why.**

- **The preset is a placement list, not serialized grid JSON.** `SerializedDockview`
  is an internal shape (grid root, orientation, per-group views) that cannot be
  verified from here; `addPanel` with `position: {direction, referencePanel}` is
  the documented public API. The preset's real invariant is order — dockview
  resolves a reference eagerly, so a forward reference throws at mount — and
  that is exactly what `catalogue.test.ts` asserts. Red-verified: pointing
  `editor` at `chat` fails two tests.
- **`initialWidth` alone did not reproduce the classic geometry.** Read off the
  panels' bounding boxes in a one-off run (the gate recorded no geometry at the
  time): nav ≈497 px, explorer ≈503 px, editor ≈115 px. The new group
  is created by splitting its reference and lands on proportional sizes. Fixed
  by pinning the three fixed-width columns with `group.api.setSize()` one frame
  after the preset is built (`pinSizes`), leaving the flexible middle the
  remainder. The gate now records each panel root's width
  (`tabs[<title>].width`) and reports 256 / 208 / ~652 / 384 in a clean run —
  the preset's requested 256 / 208 / flexible / 384, landed as asked — with
  Monaco's own width at 634 px (98 px before the pin). Nothing asserts a width:
  `pinSizes` is order-dependent by construction, each `setSize` redistributing
  the remainder, so the numbers are recorded for a reviewer to compare against
  and a few px either way is not a regression. An earlier draft of this bullet
  quoted 250 / 215 / 650 / 385 as gate output — a measurement the gate does not
  reproduce, and the reason the width recording was added.
- **The catalogue's minimum sizes are wired, not decorative.** `PanelSpec`'s
  `minWidth`/`minHeight` are passed to `addPanel` as `minimumWidth`/
  `minimumHeight` — `AddPanelOptions` extends `Partial<Constraints>`, read from
  the shipped `dockview-core` typedefs rather than assumed
  (`frontend/node_modules/dockview-core/dist/cjs/gridview/gridviewPanel.d.ts`,
  `interface Constraints`). The path is
  recorded because `node_modules` is gitignored: this claim cannot be re-checked
  from a bare checkout, and a misspelled option in a `.jsx` file is silently
  inert — the exact bug being fixed. Left out, the entries were inert data and a
  docked `nav` could be dragged below the 180 px `PANE_SPECS` clamp the classic
  layout enforces. The matching `max` clamps are **not** wired: tech design
  §4.1's `PanelSpec` declares minimums only, so the upper bounds land with P3's
  constraint pass.
- **Panel data comes from React context, not dockview `params`.** Params are
  serialized into the saved layout, so they cannot carry callbacks or live
  state; React portals keep docked panels inside the provider's tree, so context
  reaches them wherever they dock. Recorded caveat: a P4 *popout* renders in
  another document with its own root and will not see the provider — popouts
  must move these bags into a module-level store first (tech design §4.3/§4.7).
- **`renderer: 'always'` only where state must survive a move** — `editor` and
  `chat`. A useful consequence for the rest: dockview's default
  `onlyWhenVisible` unmounts a hidden panel, so a tabbed-together panel's poll
  would stop while it is hidden without any visibility plumbing — **not yet
  reachable in P1**, where the default preset gives every panel its own group,
  so no panel is ever hidden and `diff`'s 4 s poll runs whenever the dock is up.
  The diff panel keeps its own 4 s poll for now because P1 runs both shells side
  by side and `DockPanel`'s shared poll is not reachable from here; P2 retires
  both into the visibility-gated store, which is when stacking makes the
  unmount-on-hide behaviour do real work.
- **No `onDidVisibilityChange` hook was added to `CodeEditor`** (deviation from
  tech design §4.7, which asked for one). `automaticLayout: true` was already
  set in `baseOptions()`, so the question was whether it actually copes with a
  docked, resizable container — and the gate answers it with numbers: the window
  is narrowed and restored, and the editor's width must narrow with it and come
  back. The assertion is only "narrower than before" and "within 2 px of where it
  started", so 634 → 460 → 634 px is a recording, not a requirement. **The
  hidden-then-revealed case is not covered, and an earlier draft of this section
  wrongly claimed it was.** It cannot be reached from the gate: hiding a panel
  needs either a panel-level `setVisible` — `DockviewPanelApi` *omits* it, only
  gridview panels have it — or a group action to click, and dockview renders
  `.dv-right-actions-container` empty unless the app supplies actions (verified
  live: five containers, none populated). Testing it therefore needs a hide
  control that is P3's to build; until then the honest statement is that
  `automaticLayout` handles a resize of a mounted editor, and the reveal path is
  reasoned-about, not measured. If a future change drops `automaticLayout`, the
  reflow check goes red.
- **Not shipped yet, deliberately:** `sanitiseLayout` (REQ-8's defensive load
  path) — nothing loads a saved layout until P3, so it would be dead code today;
  it lands with the loader that exercises it. Also absent: the remaining fifteen
  panels (P2); persistence/presets/palette/keyboard (P3), *plus* the panel-hide
  control a reveal test needs and the REQ-9 drag proof deferred from P1; popouts
  (P4).
  **REQ-9's drag proof is not satisfied and P1 does not claim it:** the gate
  clicks tabs and measures geometry, but nothing drags a panel or moves it
  between groups, so REQ-4's "state survives a move" is backed by the
  `renderer: 'always'` declaration and a test on the declaration, not by a
  moving panel. The drag → reload → assert run is P3's exit criterion because
  asserting after a reload needs the persistence P3 adds. Reading this as
  "parity proven" would be the overclaim the rest of this section tries to
  avoid.

- **Shared prop bags, and one signal that needed re-wiring.** `AgentStrip`,
  `Sidebar`, `Prompt`, `Chat` and `StatusFooter` are fed from single prop-bag
  objects that both shells spread, so the five surfaces both shells host take
  their props from one object each. That prevents drift on what the bags
  carry, not on the wiring around them: the classic shell still wires
  `workdir`, `activePath`, the artefacts badge and the twelve dock tabs P1 does
  not host, and the dock shell adds its own `data-panel` seam and watermark.
  One behaviour did not survive the move for free: `AgentStrip`'s
  "Review changes →" bumps a counter that the classic shell answers by
  switching `DockPanel` to its Diff tab. The dock shell rendered the same
  button and ignored the signal — a dead control that a superficial parity
  claim would have hidden. `Workspace` now keeps the `DockviewApi` and
  activates the `diff` panel on that counter.

**Theme.** dockview ships sixteen palettes; none of them are ours. Rather than
adopt one, the colour-carrying `--dv-*` variables are re-pointed at the
StyleSeed tokens, so the dock follows `[data-theme]` with the rest of the app
and re-theming stays a change to `index.css`. Specificity is load-order
independent: the override selector repeats the theme class
(`.dockview-theme-dark.dockview-theme-dark`) to outrank dockview's own
`.dockview-theme-dark` rule, since the library stylesheet is imported from
`Workspace.jsx` and can land after `index.css` in the bundle.

**Gate.** `tools/ui_smoke.py` gained `--layout dock`:
`DOCK_PANELS` maps a panel id to its tab title and is checked against
`catalogue.ts` (drift fails, the same anti-duplication trick as `DOCK_TABS` vs
`App.jsx`). Each panel root carries `data-panel="<id>"`, because a tab in the
tab bar proves a tab exists, not that its body rendered — the gate asserts the
panel element exists, has non-zero geometry, and records the text it shows and
its width (`chars` and `width` are reported, not judged: a legitimately empty
panel would make a length assertion brittle, and `pinSizes` redistributes the
remainder, so an exact width would make a flake generator). The expected panel
count comes from `catalogue.ts`, not from
`DOCK_PANELS` — a `DOCK_PANELS` list checked against itself cannot notice a
panel the catalogue added (it can still fail the other way: a stale extra entry
finds no tab and misses the count). The #231 banner takes two possible shapes,
though only one of
them exists in this shell: `DiffTabPanel` returns the banner element *as* the
panel root when its fetch fails. The gate also matches a nested banner — a
comma-joined "root or descendant" selector scoped to the panel id, built from
`POLL_ERROR_SELECTOR` so the attribute is not retyped — as a guard rather than
as coverage: `DockPanel` does nest its banner in its body, but `DockPanel` is
the *classic* shell and is never mounted behind `?layout=dock`. Scoping alone was
not enough: all five panels mount at once, so a page-wide read reports whichever
banner it finds first for every tab, and a descendant-only read finds nothing of
the root shape at all. Both mistakes were real in sequence. The gate reads the
banner's presence, not its text (`""` is falsy, so an empty banner would have
read as clean). The selector string
is pinned by a test; its match behaviour was checked against this app's real DOM
in a one-off probe (not committed — the committed test pins the string only):
`data-poll-error` set on the live diff panel root and counted both ways: the
old scoped descendant form 0 (the bug, on the exact shape `DiffTabPanel` returns),
the comma form 1, a neighbouring panel 0, page-wide 1, and 0 again once the
attribute is removed. `_no_readme_reason` now separates four causes rather than
three: a failed
`/api/sessions` fetch is reported as a failed fetch, not as an empty workspace
(`_record_sessions` stores `sessions: None` there, which `not ...` read as
"no sessions"). It also requires
Monaco to reflow in both directions — narrowed with
the window, restored with it — sampling the same locator three times (node
identity is not asserted: nothing is hidden or moved, so there is no unmount for
it to survive). It does **not** cover the hidden-then-revealed path, for the
structural reason recorded above.
`verdict()` gained three failure branches (`panel_drift`, `visible: false`, a
`monaco` result that did not follow its container), with tests in
`tests/test_ui_smoke_verdict.py` (23 total); red-verified — by deleting the
`visible` check, by making `_monaco_followed_its_container` return `True`, by
unquoting the selector id, and by dropping the failed-fetch branch — each time
watching a test fail. (The quoting pin guards a convention, not validity: an
unparsable selector raises rather than matching 0, and the ids are plain
identifiers, so `[data-panel=diff]` parses. Both were probed against a browser,
not assumed — the first version of that docstring asserted the opposite.)

**Evidence (this session).** `npm run build` exit 0 · `vitest` 115/115 (was 102)
· `eslint src` 0 · `pytest` 802 passed / 1 skipped (was 796; 805/807 once the
gate's own fixes and tests landed, below) · `ruff` and `mypy`
(72 files) clean · classic gate exit 0, 16/16 tabs, 0 unexpected console errors,
0 page errors, 0 `/api/` 5xx · dock gate exit 0, 5/5 panels visible, monaco
634 → 460 → 634, panel widths recorded 256/208/652/384.

**Bundle cost — measured, and over budget until it was made conditional.** The
figure first published here was ≈17.4 KB gzip, taken from two package files
(`frontend/node_modules/dockview-react/dist/package/main.esm.min.mjs` 20,007 B
raw / 4,820 B gzip and
`frontend/node_modules/dockview-react/dist/styles/dockview.css` 159,552 B raw /
12,611 B gzip). That omitted the largest of the
three packages:
`frontend/node_modules/dockview-core/dist/package/main.esm.min.mjs` is 390,319 B
raw / 90,074 B
gzip, and it ships inside the bundle (the chunk carries `dv-dockview`). So the
"17.4 KB against a ~60 KB budget" claim was wrong by 5×, and tech design #1 §5 —
"measure `dist` before/after … reject if it exceeds ~60 KB gzip without a stated
reason" — was never actually run.

Run properly, with a worktree build of `96fbb6e` (pre-dockview) against the
built `dist`:

| Build | entry chunk raw | entry chunk gzip |
|---|---|---|
| `96fbb6e` (pre-P1) | 386,814 | 117,580 |
| P1, static import | 807,083 | 215,732 |
| **P1, lazy import (now)** | **387,694** | **118,022** |

Static import cost every user **+420,269 B raw / +98,152 B gzip** — 1.6× the
§5 budget — including anyone who never passes `?layout=dock`. `Workspace.jsx` is
now `React.lazy`, so the engine lands in its own 419,264 B raw / 97,883 B gzip
chunk fetched only when the flag is present; the always-loaded entry moved by
**+880 B raw / +442 B gzip**, which is the Suspense stub. The §5 limit is met on
the default path and a `?layout=dock` user pays 97.9 KB knowingly.

The earlier note "a dynamic import is the escape if the flag outlives P4" had it
backwards: the flag exists to keep the classic path *free*, so a static import
made the flag pointless for the people it protects.


**Docs deferred on purpose.** Tech design §8 lists a "Arranging the workspace"
section in `docs/USER-MANUAL.md` and a `docs/TECHNICAL-DESIGN-MANUAL.md` §UI
update. P1 is flag-gated and default-off, so a user-manual section would
describe something no user can reach from the UI; both land when the dock
becomes the default (P4) or the moment the flag is flipped, whichever comes
first. Recorded here so the omission is a decision rather than an oversight.

## R60 — Claims must be checkable (`tools/claim_check.py`)

**Problem it addresses.** Six consecutive commits carried a written claim the code
did not support, each found by a reviewer after publication. The mechanism was
identical: the narrative was written from the diff, in the same pass as the change,
so nothing could contradict it — `pytest`, `ruff` and `mypy` test code, not prose.

**What it checks, and why exactly that set.** Backticked paths resolve (on disk,
against the tracked tree for bare basenames, by prefix for directory claims);
`path:LINE` lands inside the file; short hex refs name a real commit; "N lines"
beside one named file matches; identifiers appear in tracked source. Deliberately
not checked: test counts (settling those means running the suites, which is
`gates.bat`'s job) and any claim phrased in prose. A check that cries wolf gets
ignored, so the first version's 157 false findings are recorded in the docstring as
the failure mode to avoid.

**Two scoping decisions, each from a defect the first version shipped.**

1. *Gitignored paths are skipped.* `frontend/dist/`, `node_modules/`, `reference/`
   and `.scratch/` are build products and a local library: absent from a fresh
   checkout by definition, present on the author's machine because a build or a scan
   ran. Asserting on them made the check machine-dependent — green locally, twelve
   findings in a clean one. Probe: a `git worktree` of `862c939`,
   `pytest tests/test_claim_check.py` → 4 of 7 documents failed. `git check-ignore`
   decides, queried with *and* without a trailing slash, because a directory-only
   pattern (`frontend/dist/`) matches only the slash form. Fails closed: if git
   cannot answer, the path is still checked, so a genuine missing file is still
   caught on a machine without git.
2. *The identifier check runs on commit messages, not documents.* Prose names other
   people's APIs (`DockviewApi`), planned ones (`sanitiseLayout`) and library
   keywords (`wal_checkpoint`) by design. With documents inside the corpus the check
   could never fire — a symbol written in `ROADMAP.md` vouched for itself, which is
   why it silently passed the exact class of claim it was built for. With documents
   excluded it fires twelve times on correct text. The shape it can settle is a
   commit message claiming "this symbol is mine and I just wrote it". So
   `STRICT_DOCS` covers paths, line references, commit refs and line counts, while
   `--message-file` covers all five. Digit-bearing tokens are not symbols
   (`G0SUN1seqSI` is a run id).

**Impact.** `tests/test_claim_check.py` (47 tests) rides on `pytest`, so a stale
count or a renamed file fails the suite instead of waiting for a reviewer.
`gates.bat` now runs `ruff` over `tools/` too: a new tool outside the linter is a
file that rots. `main` delegates to `run`, so there is one definition of the check
set and its order.

**What it could not do, and what R62 took over.** A claim phrased in prose — "the
step hides the editor" — was invisible to it. That half moved from a `RESCUE.md`
rule into the checker's sixth check under R62 (see below), gated to commit
messages by default: living documents narrate history in prose, and gating them
retroactively would scream on correct text.

## R57 — The database lockup, and where it actually came from

**The reported symptom.** `sqlite3.OperationalError: database is locked` surfacing
mid-run, with the UI wedged. First seen 2026-09-28, again 2026-10-20. The prior
mitigation (`busy_timeout=15000` plus three commit retries) had already shipped and
the report still recurred, which was the signal that the window had been widened
rather than the cause addressed.

**What the harness found.** `.scratch/db_contention.py` drove four concurrency
shapes against the real `Database`. Four connections — the server/worker/CLI/eval
process model — produced a lock after 16.4 s. Four threads on one shared connection
produced corrupted transactions in 0.1 s. A deliberate 17 s lock holder produced two
locks after 16.7 s. Cutting it down (`.scratch/db_minimise.py`) left three load-bearing
elements: `record_usage` alone never failed; `append_messages` alone did; and after
the failure `holder.in_transaction` was `True`, after which a different connection
failed with `database is locked after 16.4 s`.

**Three defects, not one.**

1. *No rollback, anywhere.* Before this fix, `grep` over `src/` found no
   `rollback()` call — today the only one is the guard in `_Connection`. Python's
   `sqlite3` opens a transaction before DML and leaves it open when a statement
   raises, so the doomed transaction keeps SQLite's write lock. Every other writer
   then waits out `busy_timeout` and fails — and because the wedged connection
   belongs to a long-lived process, the lock is never released. This, not the retry
   budget, is the lockup.
2. *Non-atomic sequence allocation.* `append_messages` read `MAX(seq)+1` and then
   inserted, so two concurrent appenders took the same `seq` and the second tripped
   `UNIQUE (session_id, seq)`. The server writes the user turn while the worker
   writes assistant turns to the same session, so those two callers collide by
   design.
3. *One connection shared across the server's threadpool.* A `sqlite3` connection is
   a transaction boundary; sharing it lets two threads commit each other's
   half-written work, and CPython raises `InterfaceError: bad parameter or other API
   misuse` when it notices.

**The fix, and why it sits where it does.** Defect 1 is fixed one level **below**
every caller: `Database` connects through a `sqlite3.Connection` subclass
(`_Connection`) whose `execute`/`executemany`/`executescript` roll back and re-raise.
The alternative — a `try/except` at each write site — would have had to cover the
45 statements in `db.py` *plus* the 58 in the eight modules that reach
`db._conn` directly (`artifacts`, `execution`, `memory`, `planning`,
`projectnotes`, `references`, `roadmap`, `semantic`) — 58 by the `db._conn`
attribute path alone; six more in `references.py` reach the same connection
through a local alias (counted with the commit sites below) — and any new caller added
later would have re-opened the hole. Defect 2 becomes one statement: `INSERT ... SELECT
COALESCE(MAX(seq), -1) + 1`, which computes the sequence under the write lock.
Defect 3 becomes one connection per thread, created lazily through a
`threading.local`, with schema and migration run once on the calling thread.

**The guard had a hole, found by the post-push review of `229f96c`.** The first
version guarded `execute`, `executemany` and `executescript` but not `commit`,
while `Database._commit` — then the only place that retried — is bypassed by 31
call sites in those eight modules, which call `db._conn.commit()` directly. A
`COMMIT` returning `SQLITE_BUSY` leaves the transaction open exactly as a failed
`INSERT` does, so the reported lockup was still reachable from the write path
that matters most. Retry and rollback now live in `_Connection.commit`, and
`Database._commit` delegates to it, so both paths get them. The layering is
deliberate and the two cannot be split: a rollback inside `commit` combined with
a retry one level up would retry a COMMIT whose statements are already gone,
commit an empty transaction, and lose the write silently. Red-verified by
deleting the override — the direct path then commits without a single retry, and
a failing `COMMIT` neither raises nor rolls back.

**Evidence.** `tests/test_db_contention.py` (3 tests) asserts the user-visible
symptom, plus the mechanism where the mechanism *is* the symptom: a rejected write
leaves `in_transaction` false and another connection can write immediately;
concurrent appends neither collide nor lose rows; a shared `Database` survives four
threads. All three failed before the change (`IntegrityError`,
`OperationalError: database is locked`, `InterfaceError`) and pass after — the third
because two threads interleaved, so it is the weakest of the three rather than a
guaranteed red. Seven commit-path tests sit in `tests/test_db.py` alongside them:
retry-then-succeed, give-up-after-budget, the direct `db._conn.commit()` path,
rollback when a `COMMIT` never succeeds, non-lock `OperationalError` raising on
the first attempt, and two for interrupts — one raised
inside the `COMMIT`, one inside the backoff sleep between retries, both asserting
`in_transaction` is false afterwards. The interrupt cases exist because `commit`
guards `BaseException` for the same reason the statement shims do: a `COMMIT` can
block for the full `busy_timeout`, which is exactly when a Ctrl-C arrives, and the
rollback therefore wraps the whole retry loop rather than each attempt — an
exception raised in the handler would otherwise escape with the write still
locked. `uv run pytest tests/test_db.py
tests/test_db_contention.py -q` runs them in about a second.

The measurements above come from `.scratch/db_contention.py` and
`.scratch/db_minimise.py`, which are gitignored and therefore **not** reproducible
from a checkout — the committed tests are the durable half of the evidence, and the
timings are the record of the diagnosis.

**What this does not claim.** Two shapes still produce the error and are expected to:
a writer that holds the write lock past `busy_timeout` (17 s in the probe) is by
definition beyond what a 15 s wait covers, and an explicit `BEGIN` on one connection
followed by another connection's commit then a write yields
`SQLITE_BUSY_SNAPSHOT` — immediate, and not helped by a timeout. The second is
latent rather than live: no code path issues an explicit `BEGIN`, verified by
searching `src/` for it. The production symptom's disappearance cannot be proven
from here; what is proven is that the mechanism which wedged the store is gone and
now has a regression test.


## R61 — chrome-devtools-mcp as a default MCP server

**Structure.** One entry in `_default_mcp_servers()` (`src/codingdude/mcp_config.py`), behind the same `shutil.which('npx')` gate as zai-vision. The Windows `.cmd/.bat` shim handling is one shared branch that rewrites both npx servers' `command`/`args` pairs (codegraph has its own branch, because its command differs) — the duplication is the two arg-lists, not the shim detection. Spawn: `npx -y chrome-devtools-mcp@latest --no-usage-statistics --no-update-checks` — Google's telemetry and update checks default to on and are explicitly opted out.

**Rationale.** Automated browser testing (screenshots, console, network, performance traces) becomes a standard capability instead of a per-project setup step. Not vendored: npx fetches at spawn, so no Apache-2.0 redistribution obligation; NOTICE.md records the dependency.

**Impact.** `ensure_default_mcp` seeds the entry additively — user edits win, and any
spawn/initialise failure is caught by `verify_mcp_toolsets`, which drops the server for the
run with a warning (no run ever dies from it). Absent npx, no entry. Existing installs pick
it up on next bounce via the additive seed. Cost: each run pre-flights a second `npx -y`
process (the first also downloads the package) — accepted, same trade as zai-vision.
Not yet verified: behaviour on a machine without Chrome (whether pre-flight drops it or it
survives to fail at first tool call).

**Verified.** `npx -y chrome-devtools-mcp@latest --version` → 1.12.0; seeded entry inspected live (cmd wrapper + both flags); tests in `tests/test_mcp.py` (seeding with flags, absent without npx).

## R62 — Claim gate: failure-mode prose must carry probe evidence (#241)

**Problem.** The R60 half of the claim gate settles arithmetic (paths, refs,
counts). The four other findings in the six-commit pattern were sentences about
what happens when something goes wrong — "silently returns 0", "can't miss a
banner", "hides nothing" — written from the diff, never executed. R60 recorded
that half as a human rule; this makes it mechanical.

**Design.** `check_failure_modes` in `tools/claim_check.py`: a sentence
containing a failure-mode verb (`raises`, `silently`, `can never`, `cannot miss`,
`can't miss`, `always`, `unreachable`, `hides`, `prevents`, `guarantees`) must
carry a `[probe: ...]` annotation with at least one non-space character inside
the brackets, or contain `not yet verified`; anything else is a finding. The verb
list is small on purpose — a check that fires on ordinary prose gets ignored.
Scope: on by default for `--message-file`, opt-in (`--failure-modes`) for
documents, and the two defaults are per-source so mixing a message file with
documents in one run does not leak the strict default onto the docs.

**Four holes found by the post-push review, each red-verified before fixing.**
Empty `[probe: ]` counted as a vouch; a probe on a neighbouring bullet vouched
for the claim on the previous line (bullets are separate claims, so sentence
splitting now breaks on any newline, not just blank ones); `pecan never` matched
`can never` (multiword verbs gained word boundaries); and a document named in the
same run as a `--message-file` inherited the message's failure-mode default.

**What this does not do.** Nothing runs the checker at commit time — no hook,
no `gates.bat` step — so "rejected" means "the check fails when run with
`--message-file`, which is this agent's documented pre-commit step", not a
mechanical git-level block. Wiring a commit-msg hook is a separate decision.
And the gate cannot force the probe to be honest; it forces the author to choose
between naming a command and writing `not yet verified`.

**Impact.** `tests/test_claim_check.py` 43 → 47 tests; the living-docs sweep is
unchanged (paths/refs/counts only). Shipped in `f051ad5`, tightened after review.
