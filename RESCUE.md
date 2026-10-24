# RESCUE.md — recovery sheet for the R59 P0/P1 frontend refactor

**Read this first if a session died, the UI is broken, or you are an AI taking over with no context.**
Owner: CodingDude. Last updated: R59 P0, chrome + cards + store/panels extracted.

---

## 1. Snapshot (update this table every time the state moves)

| Item | Value |
|---|---|
| Repo | `G:\pydantic` (branch `main`) |
| Last known-good commit | `0c4608a` — "fix(dock): one error surface for every tab" (last pushed, gates green; the #233 review fixes on top are #235) |
| Restore tag | `pre-r59-p0` → `0c2e58e` (created before any refactor; **do not delete**) |
| Working tree at kickoff | clean except `M ROADMAP.md` (R59 item) |
| Risk area | `frontend/src/` — React UI |
| Backend | untouched by R59 (Python, `src/codingdude/`) |
| `App.jsx` size | 3288 lines at kickoff → **1337** after chrome/cards/store/panel extraction (P0 complete), 1439 as of #233 |

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
- **P1** — dockview shell behind `?layout=dock` (nav, explorer, editor, chat, diff);
  the classic layout stays the default.
- P2–P4 — remaining panels, data store, persistence, popout. **Not started.**

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
npx vitest run     # must be 91 passed (no test imports App.jsx — they cover pure helpers)
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
uv run python tools\ui_smoke.py --shots .scratch\shots   # server must already be running
```

Exit 0 = every check passed; a JSON report of per-tab findings prints either way. It does *not*
judge content: `chars` per tab is recorded, so a tab stuck on "loading…" still passes — that
is what the screenshots and the manual pass are for. It needs the `playwright` dev dependency
plus `playwright install chromium`. Rebuild `frontend/dist` first or you are testing the old
bundle.

**Manual parity check (the last gate).** `npm run build` + the smoke gate passing does not
prove the UI looks *the same*. Load the app and confirm layout visually: login card · sidebar
projects/sessions · explorer tree · editor tabs + save/reload/diff · agent strip · chat +
prompt row · every dock tab renders (Diff, Graph, Planning, Artifacts, Notes, Renders,
Terminal, **Processes**, Output, Waterfall, Trace, Cost, **Memory**, MCP, Config, Standards —
16 tabs after #227/#228) · status footer. The smoke gate writes one screenshot per tab, which
is usually enough to eyeball this.

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
- No test imports `App.jsx`; the 91 vitest tests exercise `src/*.ts` pure logic only. So the
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
- Planning DB → tech design **#1**, design decision **#94**, ticket **#226** (P0)
- Artifact `R59-workspace-design` (rendered design + mock)
- This file — **update section 1 and 2 at every milestone**, so a successor never has to
  reverse-engineer how far the refactor got.
