"""UI smoke gate: render the running app and walk every dock tab.

Covers the part of R59 P0 that tests cannot reach — no vitest file imports
App.jsx, so a moved component that renders nothing is invisible to `npm test`.
This drives the real bundle in Chromium and fails on: a render crash reaching
ErrorBoundary, an uncaught page error, an unexpected console error, a missing
dock tab, DOCK_TABS drifting from the list in App.jsx, an unreachable
/api/sessions, any /api/ response with a 5xx status, a tab showing the dock's
"could not load this tab" banner (#231), or — when the workspace has a session —
a tab still showing the "select a session" placeholder (the #228 symptom).
Designed console noise (the auth-cookie 401) is reported, not fatal.

The 5xx and banner checks are what make a broken data tab fail here: a tab that
cannot load renders its own error text, which is neither the placeholder nor a
console error, so neither of those alone would catch it.

It does not judge what a tab says beyond that: `chars` is recorded per tab and
`--shots` writes one screenshot per tab for a human to glance at.

Usage (server must already be running; default http://127.0.0.1:8765):

    uv run python tools/ui_smoke.py
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
PLACEHOLDER = "Select a session to see diffs, files, cost and trace."
# The dock's own error banner (#231): present means the tab's fetch failed.
POLL_ERROR_SELECTOR = "[data-poll-error]"
CRASH_MARKER = "UI crashed"
REPO = Path(__file__).resolve().parents[1]
APP_JSX = REPO / "frontend" / "src" / "App.jsx"
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


def run(base: str, shots: Path | None, workdir: str) -> tuple[dict, int]:
    report: dict = {
        "base": base,
        "workdir": workdir,
        "tabs": {},
        "console_errors": [],
        "page_errors": [],
        "api_5xx": [],
    }
    expected = app_tabs()
    drift = (sorted(set(expected) - set(DOCK_TABS)), sorted(set(DOCK_TABS) - set(expected)))
    if any(drift):
        report["tab_drift"] = {"app_jsx_only": drift[0], "smoke_only": drift[1]}
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

            # The app holds an EventSource open and polls every 3-5s, so
            # "networkidle" is slow and flaky here — wait for the dock itself.
            page.goto(base, wait_until="domcontentloaded", timeout=60_000)
            page.get_by_role("button", name="Diff", exact=True).first.wait_for(timeout=30_000)
            page.wait_for_timeout(1500)  # let the initial session/config fetches settle
            if shots:
                page.screenshot(path=str(shots / "01-boot.png"))

            # The app auto-resumes a session when the workspace has one. With
            # none, every session-scoped tab correctly shows the placeholder,
            # so that check only means something when a session exists.
            sessions = page.request.get(f"{base}/api/sessions?workdir={quote(workdir)}")
            if not sessions.ok:
                report["sessions_error"] = f"GET /api/sessions -> {sessions.status}"
                report["sessions"] = None
            else:
                report["sessions"] = len(sessions.json())

            if CRASH_MARKER in page.content():
                report["crashed"] = "on boot"
                return report, 1

            found = 0
            for name in DOCK_TABS:
                button = page.get_by_role("button", name=name, exact=True)
                if button.count() == 0:
                    report["tabs"][name] = "MISSING"
                    continue
                found += 1
                button.first.click()
                # Tab bodies fetch on mount; /memory is ~800 KB of JSON, so a
                # shorter settle leaves data tabs on "loading…" and the gate
                # would report an empty-looking tab that is merely in flight.
                page.wait_for_timeout(2000)
                crashed = CRASH_MARKER in page.content()
                # The dock is the section that owns the Diff tab button.
                dock = page.locator(
                    "section", has=page.get_by_role("button", name="Diff", exact=True)
                )
                text = dock.first.inner_text() if dock.count() else page.inner_text("body")
                # #231: the tab's own error banner, which the placeholder and
                # console checks both miss.
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
        finally:
            browser.close()

    return report, verdict(report)


def verdict(report: dict) -> int:
    """1 when the run reveals a defect, else 0.

    Extracted from `run()` so the decision can be exercised without a browser:
    a gate whose failure paths are never executed is a gate nobody knows works.
    """
    unexpected = [
        e
        for e in report["console_errors"]
        if not any(b in e for b in BENIGN_CONSOLE) and NETWORK_NOISE not in e
    ]
    report["console_errors_unexpected"] = unexpected
    report["console_errors_network"] = [
        e for e in report["console_errors"] if NETWORK_NOISE in e
    ]
    has_session = bool(report.get("sessions"))
    failed = (
        report.get("crashed") is not None
        or report["page_errors"]
        or unexpected
        or report["api_5xx"]
        or report.get("tab_drift") is not None
        or report.get("sessions_error") is not None
        or report["tab_count"] != len(DOCK_TABS)
        or any(
            isinstance(v, str) or v["crashed"] or v["poll_error"] or (has_session and v["placeholder"])
            for v in report["tabs"].values()
        )
    )
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765", help="running app URL")
    parser.add_argument("--shots", default="", help="directory for screenshots (omit to skip)")
    parser.add_argument(
        "--workdir", default=str(REPO), help="workspace to query sessions for (default: this repo)"
    )
    args = parser.parse_args()

    report, code = run(
        args.base, Path(args.shots) if args.shots else None, str(Path(args.workdir).resolve())
    )
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
