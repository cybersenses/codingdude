# RESCUE.md — recovery sheet for the R59 P0/P1 frontend refactor

**Read this first if a session died, the UI is broken, or you are an AI taking over with no context.**
Owner: CodingDude. Last updated: R59 P1 — the dock shell behind `?layout=dock`.

---

## 1. Snapshot (update this table every time the state moves)

| Item | Value |
|---|---|
| Repo | `G:\pydantic` (branch `main`) |
| Last known-good commit | `96fbb6e` — "fix(dock): stop a dead fetch blanking a healthy panel" (#235), pushed, gates green |
| Restore tag | `pre-r59-p0` → `0c2e58e` (created before any refactor; **do not delete**) |
| Working tree at kickoff | clean except `M ROADMAP.md` (R59 item) |
| Risk area | `frontend/src/` — React UI |
| Backend | untouched by R59 (Python, `src/codingdude/`) |
| `App.jsx` size | 3288 lines at kickoff → **1337** after P0 → **1439** after #233 → 1439 after P1 (P1 is additive: `workspace/` is 320 lines across three files and `App.jsx` only gained the flag and the shared prop bags) |
| **Two shells** | classic flexbox = default; `?layout=dock` = the dockview shell (P1) |

### Progress log (P0 steps, newest last)

| Step | Result | Gate |
|---|---|---|
| Rescue sheet + restore tag | done | — |
| `ui.jsx` + `chrome/ErrorBoundary.jsx` (main.jsx updated) | done | build · 91 tests · lint |
| `chrome/Login` · `Sidebar` · `AgentStrip` · `StatusFooter` | done | build · 91 tests · lint |
| `cards/chatCards.jsx` (6 chat cards) | done | build · lint |
| `store/useFileWorkspace.js` · `panels/Explorer` · `Editor` · `Chat` · `Prompt` | done | build · 91 tests · lint |
| `panels/dock/*`: Terminal, Notes, Artifacts, ModelsConfig, Planning, Standards, Diff | done | build · 91 tests · lint |
| Remaining dock bodies inline (Graph, Output, Waterfall, Trace, Cost, MCP, Renders, Processes, Memory) | **deliberately left in `DockPanel` — see below** | — |
| `DockPanel` reduced to a shell | partial (7 extracted of 16 bodies) | — |
| **P0 COMPLETE** — move-only refactor landed | done | build · 91 tests · lint |
| #227 fix: `Processes` tab was missing from `tabs` (body unreachable) | done | build · 91 tests · lint |
| #228 fix: `Memory` tab polled but had no body branch | done | build · 91 tests · lint |
| #229 perf: Memory list capped at newest 200 (15.8k → 2.2k DOM nodes) | done | build · 91 tests · lint · DOM count |
| #230 fix: composer placeholder now says *why* it is disabled | done | build · 91 tests · lint · live DOM |
| `tools/ui_smoke.py` — Playwright gate walking all 16 dock tabs | done | exit 0, 16/16 tabs |
| #231 fix: dock poll errors surfaced on every tab (one banner, not per-tab keys) | done | build · 91 tests · lint · smoke exit 0 |
| #231 gate: smoke now fails on `/api/` 5xx and on that banner | done | smoke exit 0, 0 5xx, 0 banners |
| #233 review fixes: dead `/artifacts` poll removed (could blank a healthy panel), helpers moved to `pollErrors.ts` + 11 tests, `verdict()` no longer KeyErrors on a partial report | done | build · 102 tests · lint · ruff · mypy · pytest 796 · smoke exit 0 |
| **P1 START** — `dockview-react@8.6.1` installed (exact pin) | done | install 8.6.1 / dockview 8.6.1 |
| P1 `workspace/catalogue.ts` — 5 panels + `DEFAULT_PRESET` placements | done | 13 vitest tests, red-verified (forward reference fails 2) |
| P1 `workspace/Workspace.jsx` — shell, five panels, watermark reset | done | build · 115 tests · lint |
| P1 geometry fix — `initialWidth` left the editor at 115 px; `pinSizes()` after one frame | done | gate records widths 256/208/652/384, Monaco 634 → 460 → 634 px (narrowed and restored; the hidden-panel path is NOT covered — see below) |
| P1 `index.css` — `--dv-*` mapped onto `--ss-*` tokens | done | visual (screenshots inspected) |
| P1 `App.jsx` — `?layout=dock` flag + prop bags shared by both shells | done | build · lint · classic smoke 16/16 |
| P1 gate — `tools/ui_smoke.py --layout dock` + `data-panel` seam + Monaco reflow check | done | dock smoke exit 0, 5/5 · 19 verdict tests |

`App.jsx` is now ~1439 lines: `DockPanel` (tab shell + the 9 inline bodies) and `App`
(session/SSE state + layout). Eight of those nine bodies (Graph, Output, Waterfall, Trace,
Cost, MCP, Renders, Memory) read `DockPanel`'s single shared poll (`data`, `setData`;
`selRun` belongs to Output and Waterfall only). Only **Processes** is inline for a different
reason: it renders the `processes` prop from App's own 3 s poll. **Memory** is the ninth —
*added* inline by #228, and it polls like the rest. (Two earlier drafts of this paragraph got
the count wrong; this one was checked against the branches in `DockPanel`.) Extracting a
move-only component would mean threading those props through more files — work that P2's
data store deletes again. They are left inline on purpose and move in P2, when each panel
gets its own subscription.

If a step is in doubt, `git log --oneline -20` shows which extraction commits landed; everything
above is one commit per row.

## 2. What is being attempted

Roadmap **R59** / tech design **#1** / design decision **#94**: replace the hard-coded
five-zone flexbox UI with a dockable-window workspace (`dockview-react`), so users can put
panels anywhere.

- **P0 (complete)** — pure move-only refactor: split the 3288-line `frontend/src/App.jsx`
  into `src/chrome/`, `src/panels/`, `src/cards/`, `src/store/`. **No behaviour change.**
  Exit gate: `npm run build` clean, `npx vitest run` 91/91, `npm run lint` clean, UI
  visually identical. Landed at 1337 lines; the 9 data-coupled dock bodies stay inline
  until P2 (see the note after the progress log).
- **P1 (complete, #236)** — the dockview shell behind `?layout=dock`: five panels (`nav`,
  `explorer`, `editor`, `chat`, `diff`) built from `workspace/catalogue.ts`, themed from the
  StyleSeed tokens, reached by query flag so the classic layout stays the default. Exit gate:
  build · 115 tests · lint · classic smoke 16/16 · dock smoke 5/5 with Monaco reflow
  measured (634 → 460 → 634 px). Deviation recorded: no `onDidVisibilityChange` hook on
  `CodeEditor` — the gate proves `automaticLayout` reflows a *mounted* editor when its
  container changes. It does **not** prove the hidden-then-revealed case: dockview's
  `DockviewPanelApi` omits `setVisible` and its group headers ship no actions, so hiding a
  panel needs P3 UI before a gate can test it. Do not read this as covered.
- P2–P4 — remaining fifteen panels + the visibility-gated data store, then
  persistence/presets/palette/keyboard *plus* two obligations deferred from P1: the
  panel-hide control a reveal test needs, and the REQ-9 drag → reload → assert proof.
  Then popouts. **Not started.**

**Rollback for P1 is one query parameter**: load the app without `?layout=dock` and the
classic shell renders exactly as before. Nothing server-side changed, so no data migration
and no API version concern exists for this phase.

P0 is safe to abandon at any moment: nothing is deployed, nothing is pushed until the
gates pass.

## 3. Restore — pick the smallest action that fixes the problem

```powershell
# 0. TRIAGE FIRST — what actually changed?
cd G:\pydantic
git status --porcelain
git diff --stat

# 1. Abandon uncommitted refactor work, keep the tree at the restore tag
git reset --hard pre-r59-p0

# 2. Undo a committed-but-bad P0 step, keeping history honest
git revert <bad-sha>          # preferred: published history is never rewritten

# 3. Nuclear: force main back to the tag (only if the commits were never pushed)
git reset --hard pre-r59-p0
git tag -f pre-r59-p0 0c2e58e  # keep the tag pointing at the known-good commit
```

The UI is served from `frontend/dist`, which is **gitignored** — a `git reset` restores
sources but *not* the bundle. Always rebuild:

```powershell
cd G:\pydantic\frontend
npm install     # only if node_modules is missing/corrupt
npm run build   # rewrites dist/ from src/
```

Then **restart the server** (the running process holds the old bundle in memory):
`start-codingdude.bat`, or `uv run codingdude serve`. Confirm `GET /health` reports the
expected `version` / `git_sha`.

## 4. Verification — run all four before believing anything works

```powershell
cd G:\pydantic\frontend
npm run build      # must exit 0; watch for a chunk-size or unresolved-import warning
npx vitest run     # must be 115 passed (no test imports App.jsx — they cover pure helpers)
npm run lint       # eslint src, must be clean
```

Backend is not in scope, but if you touched anything shared:

```powershell
cd G:\pydantic
uv run pytest -q
uv run ruff check src tests
uv run mypy
```

**Machine-checked parity (do this first — it catches what the build cannot).** No vitest file
imports `App.jsx`, so a moved component that renders *nothing* still builds clean. The smoke
gate drives the real bundle in Chromium and walks all 16 dock tabs, failing on an
ErrorBoundary crash, an uncaught page error, an unexpected console error, a missing tab,
`DOCK_TABS` drifting from the tab list in `App.jsx`, an unreachable `/api/sessions`, any
`/api/` response with a 5xx status, a tab showing the dock's "could not load this tab"
banner (#231), or — when
the workspace has a session — a tab still showing the "select a session" placeholder:

```powershell
cd G:\pydantic
uv run python tools\ui_smoke.py --shots .scratch\shots                 # classic shell
uv run python tools\ui_smoke.py --layout dock --shots .scratch\dock-shots   # R59 P1 shell
```

Exit 0 = every check passed; a JSON report of per-tab findings prints either way. It does *not*
judge content: `chars` and `width` per panel are recorded, so a tab stuck on "loading…" still
passes — that is what the screenshots and the manual pass are for. It needs the `playwright`
dev dependency plus `playwright install chromium`. Rebuild `frontend/dist` first or you are
testing the old bundle.

`--layout dock` is the P1 gate: it reads `?layout=dock`, waits for the explorer's tree (it
renders nothing until a session binds, so without the wait a slow session fetch reads as a
missing `README.md`), checks the five `DOCK_PANELS` against `workspace/catalogue.ts` (drift
fails), asserts each panel root marked `data-panel="<id>"` has non-zero geometry — a bounding
box, not a visibility test: a scrolled-away element still has one — and records each panel's
width. A tab in the tab bar proves a tab exists, not that its body rendered; the geometry and
the recorded text are what make that difference visible. It then opens `README.md` in the
editor to confirm Monaco re-lays-out when the viewport changes. The hidden-then-revealed
variant is **not** covered — see §2 — because the dock has no control that hides a panel. Its
verdict has unit tests (`tests/test_ui_smoke_verdict.py`, 19) because a gate nobody exercises
is a gate nobody knows works.

**Manual parity check (the last gate).** `npm run build` + the smoke gate passing does not
prove the UI looks *the same*. Load the app and confirm layout visually: login card · sidebar
projects/sessions · explorer tree · editor tabs + save/reload/diff · agent strip · chat +
prompt row · every dock tab renders (Diff, Graph, Planning, Artifacts, Notes, Renders,
Terminal, **Processes**, Output, Waterfall, Trace, Cost, **Memory**, MCP, Config, Standards —
16 tabs after #227/#228) · status footer. The smoke gate writes one screenshot per tab, which
is usually enough to eyeball this. Repeat once with `?layout=dock`: the five panels should be
nav 256 px · explorer 208 px · editor + diff stacked in the middle · chat 384 px, i.e. the
classic arrangement with draggable splitters. Those are the widths the preset requests, and the
gate records the panel roots landing on them (`tabs[<title>].width`), with the middle column
taking the remainder (~652 px). Nothing asserts a width — `pinSizes` calls `setSize` per column
and each call redistributes the remainder — so compare against the recording and treat a few px
either way as normal. An earlier draft of this paragraph quoted 250/215/650/385 as gate output;
the gate does not reproduce those numbers.

## 5. If the UI is blank / crashed

`ErrorBoundary` (now `src/chrome/ErrorBoundary.jsx`) shows the stack trace on screen — read
it first. A blank page with a console error almost always means one of:

1. **A component was moved but a stale import remains** — `grep` the old name across `src/`.
2. **`dist/` is stale** — rebuild; a stale bundle after a source move is the single most
   likely false alarm.
3. **A named export went missing** — `App.jsx` imports from each new module; check the
   import list at the top of `App.jsx` against the exports in the moved file.

## 6. Environment facts (do not re-derive these)

- OS Windows 11; shell is **PowerShell** — `&&` is a syntax error, use `;`.
- Project dir is `G:\pydantic`; `cd /g/pydantic` fails. `cd frontend` from the repo root works.
- Python tooling is venv-scoped: `uv run pytest` / `ruff` / `mypy`. Never assume global PATH.
- Frontend is Vite + React 18.3.1, Tailwind v4, vitest 5. `node_modules` is present.
- `frontend/dist` is gitignored and served from disk by the Python server.
- No test imports `App.jsx`; the 115 vitest tests exercise `src/*.ts` pure logic only. So the
  refactor cannot be caught by tests — **the build + manual parity check are the real gate.**

## 7. Traps that have bitten before

| Trap | Reality |
|---|---|
| "Edit reported success" | Verify every edit with `grep`/`Select-String` before moving on. Silent non-persistence has happened repeatedly in this repo. |
| Parallel `edit_file` calls on the same file | They race and one edit is silently lost. **Edit one file at a time, sequentially.** |
| PowerShell `&&` | Syntax error. Use `;`. |
| Push exit code 1 | Usually PowerShell flagging git's stderr progress line — check `git status` / `git log origin/main` before assuming failure. |
| Mojibake in output | Often a PowerShell console artefact, not the file. Verify bytes before "fixing" UTF-8. |
| Bulk edits via python/shell | **Not permitted** without explicit user approval. Use `write_file` / `edit_file`. |

## 8. Where the plan and decisions live

- `ROADMAP.md` → **R59**
- Planning DB → tech design **#1**, design decision **#94**, ticket **#226** (P0), ticket **#236** (P1)
- `code-design.md` → §R59 (P0 structure) and §R59 P1 (the dock shell: decisions, evidence, deviations)
- Artifact `R59-workspace-design` (rendered design + mock)
- This file — **update section 1 and 2 at every milestone**, so a successor never has to
  reverse-engineer how far the refactor got.
