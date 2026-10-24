"""UI smoke gate: render the running app and walk its panels.

Covers the part of R59 that tests cannot reach — no vitest file imports App.jsx,
so a moved component that renders nothing is invisible to `npm test`. This
drives the real bundle in Chromium and fails on: a render crash reaching
ErrorBoundary, an uncaught page error, an unexpected console error, a missing
dock tab, DOCK_TABS drifting from the list in App.jsx, an unreachable
/api/sessions, any /api/ response with a 5xx status, a tab showing the dock's
"could not load this tab" banner (#231), or — when the workspace has a session —
a tab still showing the "select a session" placeholder (the #228 symptom).
Designed console noise (the auth-cookie 401) is reported, not fatal.

Two layouts:

* `--layout classic` (default) walks the sixteen `DockPanel` tabs.
* `--layout dock` opens `?layout=dock` (R59 P1) and checks the five dockable
  panels, their visible geometry, and that Monaco follows its container: the
  editor is hidden, the window is narrowed while it is away, and it is revealed
  again. `renderer: 'always'` keeps a hidden panel's DOM alive, so this is the
  regression the dock could introduce — an editor that comes back at the width
  it last had.

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

from playwright.sync_api import sync_playwright

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
# The dock's own error banner (#231): present means the tab's fetch failed.
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
        # checks both miss.
        err = page.locator(POLL_ERROR_SELECTOR)
        poll_error = err.first.inner_text() if err.count() else None
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


def _walk_dock(page, report: dict, base: str, workdir: str, shots: Path | None) -> None:
    """R59 P1: the dockable shell behind `?layout=dock`."""
    declared = catalogue_panels()
    if not declared:
        # The catalogue is the source of truth for how many panels exist. If it
        # cannot be read, every count below is meaningless — say so rather than
        # falling back to a number the walk agrees with by construction.
        report["panel_drift"] = {"_catalogue": "catalogue.ts could not be read"}
    drift = {
        pid: {"smoke": title, "catalogue": declared.get(pid)}
        for pid, title in DOCK_PANELS.items()
        if declared.get(pid) != title
    }
    if drift:
        report["panel_drift"] = drift
    # The expected count comes from the catalogue, not from DOCK_PANELS:
    # comparing the walk against its own list is a check that can never fail. A
    # panel added to the catalogue and not walked here is drift, exactly as
    # DOCK_TABS vs App.jsx's `tabs` behaves in the classic walk.
    report["expected_entries"] = len(declared) if declared else len(DOCK_PANELS)

    page.goto(_dock_url(base), wait_until="domcontentloaded", timeout=60_000)
    page.locator(".dv-default-tab").first.wait_for(timeout=30_000)
    page.wait_for_timeout(1500)
    if shots:
        page.screenshot(path=str(shots / "dock-00-boot.png"))

    _record_sessions(page, report, base, workdir)

    if CRASH_MARKER in page.content():
        report["crashed"] = "on boot"
        return

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
        box = panel.first.bounding_box() if panel.count() else None
        text = panel.first.inner_text() if panel.count() else ""
        err = page.locator(POLL_ERROR_SELECTOR)
        report["tabs"][title] = {
            "crashed": crashed,
            "placeholder": PLACEHOLDER in text,
            "poll_error": err.first.inner_text() if err.count() else None,
            "chars": len(text),
            "visible": bool(box and box["width"] > 0 and box["height"] > 0),
        }
        if shots:
            page.screenshot(path=str(shots / f"dock-{panel_id}.png"))
        if crashed:
            break

    report["tab_count"] = found
    if not report.get("crashed"):
        _monaco_relayout(page, report, shots)


def _monaco_relayout(page, report: dict, shots: Path | None) -> None:
    """The editor must follow its container, not the size it last had.

    `renderer: 'always'` keeps a hidden panel's DOM alive, so this is the
    regression P1 could introduce: the editor goes off screen, its container
    changes underneath it, and it comes back at the geometry it went away with.
    Measured by narrowing the window *while the editor is hidden* and comparing
    the width after the reveal against the width before it.
    """
    tab = _dock_tab(page, "Editor")
    if tab is not None:
        tab.click()
        page.wait_for_timeout(300)
    # Root-level file in the session's workdir, so the explorer has a stable,
    # unambiguous target to open.
    opener = page.locator('button[title="README.md"]')
    if opener.count() == 0:
        report["monaco"] = "README.md not in the explorer — editor never opened"
        return
    opener.first.click()
    editor = page.locator(".monaco-editor")
    try:
        editor.first.wait_for(timeout=20_000)
    except Exception:  # noqa: BLE001 - the gate reports the miss, it does not raise
        report["monaco"] = "the editor never mounted"
        return
    page.wait_for_timeout(800)
    before = editor.first.bounding_box()

    # Hide the editor by activating another panel, then change the container
    # width while it is away.
    away = _dock_tab(page, "Chat")
    if away is not None:
        away.click()
        page.wait_for_timeout(600)
        page.set_viewport_size({"width": 1100, "height": 760})
        page.wait_for_timeout(600)
    back = _dock_tab(page, "Editor")
    if back is not None:
        back.click()
        page.wait_for_timeout(900)
    shown = editor.first.bounding_box()
    if shots:
        page.screenshot(path=str(shots / "dock-01-revealed.png"))

    # Restore the viewport so the run leaves the page where it found it.
    page.set_viewport_size({"width": 1500, "height": 950})
    page.wait_for_timeout(800)
    restored = editor.first.bounding_box()
    report["monaco"] = {
        "width_before": before["width"] if before else None,
        "width_shown": shown["width"] if shown else None,
        "width_after": restored["width"] if restored else None,
    }


def _monaco_followed_its_container(m: object) -> bool:
    """Whether the editor tracked a container change it could not see coming.

    The load-bearing measurement is `width_shown`: the panel was hidden, the
    window was narrowed while it was away, and it was revealed. An editor that
    comes back at `width_before` never re-laid-out — the `renderer: 'always'`
    regression. A non-dict value means the check could not run at all, which is
    a failure too, not a pass.
    """
    if not isinstance(m, dict):
        return False
    before, shown = m.get("width_before"), m.get("width_shown")
    if not before or not shown:
        return False
    return shown != before


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
