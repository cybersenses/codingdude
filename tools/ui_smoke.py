"""UI smoke gate: render the running app and walk its panels.

Covers the part of R59 that tests cannot reach — no vitest file imports App.jsx,
so a moved component that renders nothing is invisible to `npm test`. This
drives the real bundle in Chromium and fails on: a render crash reaching
ErrorBoundary, an uncaught page error, an unexpected console error, a missing
dock tab, DOCK_TABS drifting from the list in App.jsx, a non-OK /api/sessions
response, any /api/ response with a 5xx status, a tab showing the dock's
"could not load this tab" banner (#231), or — when the workspace has a session —
a tab still showing the "select a session" placeholder (the #228 symptom).
Designed console noise (the auth-cookie 401) is reported, not fatal.

Two layouts:

* `--layout classic` (default) walks the sixteen `DockPanel` tabs.
* `--layout dock` opens `?layout=dock` (R59 P1) and checks the five dockable
  panels, their visible geometry, and that Monaco reflows with its container:
  the window is narrowed and restored and the editor must narrow with it and
  come back. Nothing is hidden or moved, so `renderer: 'always'` — which only
  matters for a hidden panel — is not what this exercises. The
  hidden-then-revealed variant is NOT covered — see
  `_monaco_reflow` for why the dock cannot hide a panel without UI it has not
  been given yet, and do not describe this gate as covering it.

The 5xx and banner checks are what make a broken data tab fail here: a tab that
cannot load renders its own error text, which is neither the placeholder nor a
console error, so neither of those alone would catch it.

It does not judge what a tab says beyond that: `chars` is recorded per tab and
`--shots` writes one screenshot per tab for a human to glance at.

Usage (server must already be running; default http://127.0.0.1:8765):

    uv run python tools/ui_smoke.py
    uv run python tools/ui_smoke.py --layout dock --shots .scratch/shots
    uv run python tools/ui_smoke.py --base http://127.0.0.1:8765 --shots .scratch/shots

Exit code 0 = every check passed. 1 = at least one failed. Requires the
`playwright` dev dependency and `playwright install chromium`.

Note: `tools/` is outside the repo's ruff/mypy scope (`ruff check src tests`,
`[tool.mypy] packages = ["codingdude"]`), so this file is held to the same
standard by convention, not by CI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

# `playwright` is imported inside `run()` rather than here: this module's
# browser-free parts (`verdict`, `_panel_banner_selector`, `_no_readme_reason`,
# `catalogue_panels`, the panel tables) are what `tests/test_ui_smoke_verdict.py`
# exercises, and a module-level import would make that file skip — silently
# unproving the gate's failure branches — on any checkout without the dev extra.

DOCK_TABS = [
    "Diff", "Graph", "Planning", "Artifacts", "Notes", "Renders", "Terminal",
    "Processes", "Output", "Waterfall", "Trace", "Cost", "Memory", "MCP",
    "Config", "Standards",
]
# R59 P1: the dockable shell's panels, as (data-panel attribute → tab title).
# The attribute is the seam the shell puts on each panel root, so the gate can
# assert a panel is really on screen rather than trusting the tab bar.
DOCK_PANELS = {
    "nav": "Projects & sessions",
    "explorer": "Explorer",
    "editor": "Editor",
    "chat": "Chat",
    "diff": "Diff",
}
PLACEHOLDER = "Select a session to see diffs, files, cost and trace."
# The dock's own error banner (#231): present means the tab's fetch failed. The
# classic walk reads it page-wide, where one tab body is mounted at a time; the
# dock walk joins this attribute to a panel id via `_panel_banner_selector`.
POLL_ERROR_SELECTOR = "[data-poll-error]"
CRASH_MARKER = "UI crashed"
REPO = Path(__file__).resolve().parents[1]
APP_JSX = REPO / "frontend" / "src" / "App.jsx"
CATALOGUE_TS = REPO / "frontend" / "src" / "workspace" / "catalogue.ts"
# Console errors that are the app working as designed, not defects: the boot
# probes the auth cookie first and logs the 401 before falling back to
# authLocal(). Anything else on the console fails the gate.
BENIGN_CONSOLE = ("the server responded with a status of 401",)
# Resource-load failures are reported, not fatal on their own: the browser logs
# one for every non-2xx fetch, and the real verdict comes from the 5xx response
# hook and the tab's own error banner below — not from this string.
NETWORK_NOISE = "Failed to load resource"


def app_tabs() -> list[str]:
    """The dock tab list as declared in App.jsx, so DOCK_TABS cannot drift."""
    match = re.search(r"const tabs = \[([^\]]+)\]", APP_JSX.read_text(encoding="utf-8"))
    return re.findall(r"'([^']+)'", match.group(1)) if match else []


def catalogue_panels() -> dict[str, str]:
    """Panel id → title as declared in the dock catalogue, so DOCK_PANELS cannot drift."""
    text = CATALOGUE_TS.read_text(encoding="utf-8")
    pairs = re.findall(r"\{ id: '([^']+)', title: '([^']+)'", text)
    return dict(pairs)


def run(base: str, shots: Path | None, workdir: str, layout: str = "classic") -> tuple[dict, int]:
    report: dict = {
        "base": base,
        "layout": layout,
        "workdir": workdir,
        "tabs": {},
        "console_errors": [],
        "page_errors": [],
        "api_5xx": [],
    }
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.on(
                "console",
                lambda m: report["console_errors"].append(m.text) if m.type == "error" else None,
            )
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            # A 5xx on any /api/ route is a server-side failure the UI cannot
            # paper over, however gracefully it renders — gate on it directly.
            page.on(
                "response",
                lambda r: report["api_5xx"].append({"url": r.url, "status": r.status})
                if "/api/" in r.url and r.status >= 500
                else None,
            )
            walk = _walk_dock if layout == "dock" else _walk_classic
            walk(page, report, base, workdir, shots)
        finally:
            browser.close()

    return report, verdict(report)


def _record_sessions(page, report: dict, base: str, workdir: str) -> None:
    """Whether the workspace has a session: the placeholder check needs to know."""
    sessions = page.request.get(f"{base}/api/sessions?workdir={quote(workdir)}")
    if not sessions.ok:
        report["sessions_error"] = f"GET /api/sessions -> {sessions.status}"
        report["sessions"] = None
    else:
        report["sessions"] = len(sessions.json())


def _walk_classic(page, report: dict, base: str, workdir: str, shots: Path | None) -> None:
    expected = app_tabs()
    drift = (sorted(set(expected) - set(DOCK_TABS)), sorted(set(DOCK_TABS) - set(expected)))
    if any(drift):
        report["tab_drift"] = {"app_jsx_only": drift[0], "smoke_only": drift[1]}

    # The app holds an EventSource open and polls every 3-5s, so
    # "networkidle" is slow and flaky here — wait for the dock itself.
    page.goto(base, wait_until="domcontentloaded", timeout=60_000)
    page.get_by_role("button", name="Diff", exact=True).first.wait_for(timeout=30_000)
    page.wait_for_timeout(1500)  # let the initial session/config fetches settle
    if shots:
        page.screenshot(path=str(shots / "01-boot.png"))

    # The app auto-resumes a session when the workspace has one. With none,
    # every session-scoped tab correctly shows the placeholder, so that check
    # only means something when a session exists.
    _record_sessions(page, report, base, workdir)

    if CRASH_MARKER in page.content():
        report["crashed"] = "on boot"
        return  # the verdict still comes from run(), one exit shape for both walks

    found = 0
    for name in DOCK_TABS:
        button = page.get_by_role("button", name=name, exact=True)
        if button.count() == 0:
            report["tabs"][name] = "MISSING"
            continue
        found += 1
        button.first.click()
        # Tab bodies fetch on mount; /memory is ~800 KB of JSON, so a shorter
        # settle leaves data tabs on "loading…" and the gate would report an
        # empty-looking tab that is merely in flight.
        page.wait_for_timeout(2000)
        crashed = CRASH_MARKER in page.content()
        # The dock is the section that owns the Diff tab button.
        dock = page.locator("section", has=page.get_by_role("button", name="Diff", exact=True))
        text = dock.first.inner_text() if dock.count() else page.inner_text("body")
        # #231: the tab's own error banner, which the placeholder and console
        # checks both miss. Page-wide is correct here: the classic dock mounts
        # one tab body at a time, so the only banner in the document is the
        # active tab's. The dock shell mounts all five — hence the scoped,
        # root-or-descendant search in `_panel_banner_selector`.
        err = page.locator(POLL_ERROR_SELECTOR)
        poll_error = _banner_text(err)
        report["tabs"][name] = {
            "crashed": crashed,
            "placeholder": PLACEHOLDER in text,
            "poll_error": poll_error,
            "chars": len(text),
        }
        if shots:
            page.screenshot(path=str(shots / f"tab-{name}.png"))
        if crashed:
            break

    report["tab_count"] = found


def _dock_url(base: str) -> str:
    return f"{base}{'&' if '?' in base else '?'}layout=dock"


def _dock_tab(page, title: str):
    """The dockview tab whose label is exactly `title` (substring matching is a
    trap here: 'Diff' is also a word inside the Diff panel's own body)."""
    for tab in page.locator(".dv-default-tab").all():
        if tab.inner_text().strip() == title:
            return tab
    return None


def _panel_banner_selector(panel_id: str) -> str:
    """A panel's own error banner, whether it *is* the panel root or nested in it.

    `Locator.locator()` matches descendants only, which is a trap here: when
    `DiffTabPanel`'s fetch fails it returns the banner element as the panel root
    (`data-panel` and `data-poll-error` on the same div, `Workspace.jsx`), so a
    scoped descendant search finds nothing and reports the failing panel as
    clean. The comma is an "or" — either shape, and still nothing belonging to
    another panel.

    Only the root shape exists under this layout today: `DiffTabPanel` is the one
    panel that arms a banner. The descendant half is a guard, not coverage —
    `DockPanel` does nest its banner in its body, but `DockPanel` is the *classic*
    shell and is never mounted behind `?layout=dock`, so it is the classic walk's
    page-wide read that sees that one.
    """
    return (
        f'[data-panel="{panel_id}"]{POLL_ERROR_SELECTOR}, '
        f'[data-panel="{panel_id}"] {POLL_ERROR_SELECTOR}'
    )


def _banner_text(banner) -> str | None:
    """The banner's text, or `None` when no banner is there.

    Presence, not presence-with-text: an empty banner still means the fetch
    failed, and `""` is falsy, so a plain `inner_text()` would report that panel
    as clean — the same class of blind spot as the scoped search this file fixed.
    """
    if banner.count() == 0:
        return None
    return banner.first.inner_text().strip() or "(banner present, no text)"


def _wait_for_tree(page, timeout_ms: int = 15_000) -> bool:
    """Wait for the explorer's file rows, which arrive after the session does.

    `FileTree` renders a placeholder — "no session" until the session id binds,
    then "loading…" until `/sessions/{id}/tree` resolves — and the file buttons
    (the ones carrying `title`) exist only once the tree is in hand. So a fixed
    settle in the walk is a race, and it was observed one: a run recorded 17
    chars for Explorer, which is "Explorer" plus the "loading…" placeholder, i.e.
    the session had bound and the tree fetch was still in flight. The Monaco step
    then reported that as a missing `README.md` — a false red about a missing file
    rather than a slow fetch. Bounded wait; the caller still reports a real miss.
    """
    tree = page.locator('[data-panel="explorer"] button[title]')
    try:
        tree.first.wait_for(timeout=timeout_ms)
    except Exception:  # a missing tree is a finding, not an exception
        return False
    return True


def _walk_dock(page, report: dict, base: str, workdir: str, shots: Path | None) -> None:
    """R59 P1: the dockable shell behind `?layout=dock`."""
    declared = catalogue_panels()
    if not declared:
        # The catalogue is the source of truth for how many panels exist. An
        # empty parse means the regex no longer matches the file, so every count
        # below is meaningless — say that rather than falling back to a number
        # the walk agrees with by construction. (A *missing* catalogue raises out
        # of `catalogue_panels()`: a broken checkout should be loud, not a
        # diagnostic.)
        report["panel_drift"] = {"_catalogue": "catalogue.ts parsed to no panels"}
    else:
        drift = {
            pid: {"smoke": title, "catalogue": declared.get(pid)}
            for pid, title in DOCK_PANELS.items()
            if declared.get(pid) != title
        }
        if drift:
            report["panel_drift"] = drift
    # The expected count comes from the catalogue, not from DOCK_PANELS: a
    # `DOCK_PANELS` list compared against itself cannot notice a panel the
    # catalogue added. (It is not literally unfailable — a stale extra entry in
    # `DOCK_PANELS` finds no tab and so fails the count — but it cannot see the
    # other direction.) A catalogue panel missing from `DOCK_PANELS` is not
    # recorded as `panel_drift` either — that dict names mismatched titles and
    # does not look in the other direction — so it fails the run as a count
    # mismatch instead.
    if declared:
        report["expected_entries"] = len(declared)

    page.goto(_dock_url(base), wait_until="domcontentloaded", timeout=60_000)
    page.locator(".dv-default-tab").first.wait_for(timeout=30_000)
    page.wait_for_timeout(1500)
    if shots:
        page.screenshot(path=str(shots / "dock-00-boot.png"))

    _record_sessions(page, report, base, workdir)

    if CRASH_MARKER in page.content():
        report["crashed"] = "on boot"
        return

    # Recorded, and waited for: an empty Explorer panel otherwise reads as a
    # missing file when it is a session fetch still in flight.
    report["tree_ready"] = _wait_for_tree(page)

    found = 0
    for panel_id, title in DOCK_PANELS.items():
        tab = _dock_tab(page, title)
        if tab is None:
            report["tabs"][title] = "MISSING"
            continue
        found += 1
        tab.click()
        page.wait_for_timeout(700)
        crashed = CRASH_MARKER in page.content()
        # `data-panel` is the attribute the shell puts on each panel root — the
        # tab bar saying "Chat" proves a tab exists, not that its body rendered.
        panel = page.locator(f'[data-panel="{panel_id}"]')
        present = panel.count() > 0
        first = panel.first if present else None
        box = first.bounding_box() if first else None
        text = first.inner_text() if first else ""
        # All five panels are mounted at once under this layout, so a page-wide
        # locator reports whichever banner it finds first for every tab — a single
        # failing Diff fetch once labelled all five panels as failing. Scoping is
        # only half the job: see `_panel_banner_selector` for why the search has
        # to match the panel root as well as its descendants.
        banner = page.locator(_panel_banner_selector(panel_id))
        report["tabs"][title] = {
            "crashed": crashed,
            "placeholder": PLACEHOLDER in text,
            "poll_error": _banner_text(banner),
            "chars": len(text),
            # Recorded, not asserted: the pinned columns land approximate because
            # each `setSize` redistributes the remainder, so asserting a width
            # here would only generate flakes. The geometry numbers quoted in
            # RESCUE/code-design/ROADMAP come from these recordings.
            "width": round(box["width"]) if box else None,
            "visible": bool(box and box["width"] > 0 and box["height"] > 0),
        }
        if shots:
            page.screenshot(path=str(shots / f"dock-{panel_id}.png"))
        if crashed:
            break

    report["tab_count"] = found
    if not report.get("crashed"):
        _monaco_reflow(page, report, shots)


def _no_readme_reason(report: dict) -> str:
    """Why the README opener was missing — four causes, four messages.

    All four fail the run (the check did not run), but they are not the same fact
    and the report should not guess: the sessions endpoint may have failed
    outright, a workspace with no session has no tree to render by design, a
    bound session whose fetch never landed is slow, and a rendered tree without
    README.md means this workdir cannot host the check.
    """
    if report.get("sessions_error"):
        return (
            f"{report['sessions_error']}, so it is unknown whether this workspace "
            "has a file tree to open README.md from"
        )
    if not report.get("sessions"):
        return (
            "the workspace has no sessions, so there is no file tree to open "
            "README.md from"
        )
    if not report.get("tree_ready"):
        return (
            "the explorer showed no file tree within the 15 s wait — either none "
            "rendered or the fetch was still in flight; nothing to open README.md from"
        )
    return "README.md not in the explorer — editor never opened"


def _monaco_reflow(page, report: dict, shots: Path | None) -> None:
    """The editor must reflow with its container, not keep the width it had.

    The regression P1 could introduce is an editor that keeps the geometry it
    had before its container changed, so its width is sampled before, during and
    after a window resize: it must shrink with the window and come back with it.
    Three samples from the same locator, not a node-identity assertion — nothing
    here hides or moves the panel, so there is no unmount for it to survive, and
    `renderer: 'always'` is therefore not what this exercises. What the reflow
    does depend on is `automaticLayout` in `baseOptions()`; drop that and this
    goes red.

    What this does NOT cover, and no doc may claim it does: the
    hidden-then-revealed case. Hiding the editor needs either a panel-level
    `setVisible` — dockview's `DockviewPanelApi` omits it, only gridview panels
    have it — or a group action to click, and the group header renders
    `.dv-right-actions-container` with no children unless the app supplies
    actions (verified live: five containers, none populated). Adding a hide
    control to the UI so a test can click it is P3's work, so this asserts the
    reflow it can actually reach and records the gap instead of faking it.
    """
    tab = _dock_tab(page, "Editor")
    if tab is not None:
        tab.click()
        page.wait_for_timeout(300)
    # Root-level file in the session's workdir, so the explorer has a stable,
    # unambiguous target to open. A workdir with no README.md fails loudly here
    # rather than silently skipping the check.
    opener = page.locator('button[title="README.md"]')
    if opener.count() == 0:
        report["monaco"] = _no_readme_reason(report)
        return
    opener.first.click()
    editor = page.locator(".monaco-editor")
    try:
        editor.first.wait_for(timeout=20_000)
    except Exception:  # the gate reports the miss, it does not raise
        report["monaco"] = "the editor never mounted"
        return
    page.wait_for_timeout(800)
    before = editor.first.bounding_box()

    page.set_viewport_size({"width": 1100, "height": 760})
    page.wait_for_timeout(800)
    narrowed = editor.first.bounding_box()

    # Restore the viewport so the run leaves the page where it found it — and
    # so an editor that reflowed once and then stuck is caught as well.
    page.set_viewport_size({"width": 1500, "height": 950})
    page.wait_for_timeout(800)
    restored = editor.first.bounding_box()
    if shots:
        page.screenshot(path=str(shots / "dock-01-restored.png"))

    report["monaco"] = {
        "width_before": before["width"] if before else None,
        "width_narrowed": narrowed["width"] if narrowed else None,
        "width_restored": restored["width"] if restored else None,
    }


def _monaco_followed_its_container(m: object) -> bool:
    """Whether the editor tracked a container change in both directions.

    A resize does not remount the panel, so it cannot rely on a fresh mount to
    pick up new geometry: narrowing the window must narrow it, and restoring the
    window must restore it. Both halves matter — an editor that reflows once and
    then sticks passes the first and fails the second. A non-dict value means the
    check could not run at all, which is a failure too, not a pass.
    """
    if not isinstance(m, dict):
        return False
    before = m.get("width_before")
    narrowed = m.get("width_narrowed")
    restored = m.get("width_restored")
    if not before or not narrowed or not restored:
        return False
    if not narrowed < before:
        return False
    # Sub-pixel rounding, not slack: a stuck editor is out by hundreds.
    return abs(restored - before) <= 2


def verdict(report: dict) -> int:
    """1 when the run reveals a defect, else 0.

    Extracted from `run()` so the decision can be exercised without a browser:
    a gate whose failure paths are never executed is a gate nobody knows works.
    Every key is read with a default, so a partial report — a boot crash, or a
    hand-built one in the tests — reaches a verdict instead of raising KeyError.
    A missing tab count counts as a defect: the walk never completed.
    """
    console_errors = report.get("console_errors") or []
    unexpected = [
        e
        for e in console_errors
        if not any(b in e for b in BENIGN_CONSOLE) and NETWORK_NOISE not in e
    ]
    report["console_errors_unexpected"] = unexpected
    report["console_errors_network"] = [e for e in console_errors if NETWORK_NOISE in e]
    has_session = bool(report.get("sessions"))

    def tab_failed(v: object) -> bool:
        if not isinstance(v, dict):
            return True  # "MISSING" and anything else unexpected
        return bool(
            v.get("crashed")
            or v.get("poll_error")
            or (has_session and v.get("placeholder"))
            # R59 P1: the dock gate reports whether the panel body was really on
            # screen; `is False` so the classic walk (no such key) is unaffected.
            or v.get("visible") is False
        )

    # The expected entry count comes from the walk: sixteen dock tabs in the
    # classic shell, five panels in the dock shell. Defaulting to the classic
    # count keeps a hand-built report meaningful.
    expected_entries = report.get("expected_entries", len(DOCK_TABS))
    monaco = report.get("monaco")
    monaco_failed = monaco is not None and not _monaco_followed_its_container(monaco)
    failed = (
        report.get("crashed") is not None
        or report.get("page_errors")
        or unexpected
        or report.get("api_5xx")
        or report.get("tab_drift") is not None
        or report.get("panel_drift") is not None
        or report.get("sessions_error") is not None
        or report.get("tab_count", 0) != expected_entries
        or monaco_failed
        or any(tab_failed(v) for v in (report.get("tabs") or {}).values())
    )
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765", help="running app URL")
    parser.add_argument("--shots", default="", help="directory for screenshots (omit to skip)")
    parser.add_argument(
        "--layout",
        default="classic",
        choices=["classic", "dock"],
        help="classic = the sixteen-tab dock; dock = ?layout=dock (R59 P1)",
    )
    parser.add_argument(
        "--workdir", default=str(REPO), help="workspace to query sessions for (default: this repo)"
    )
    args = parser.parse_args()

    report, code = run(
        args.base,
        Path(args.shots) if args.shots else None,
        str(Path(args.workdir).resolve()),
        args.layout,
    )
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
