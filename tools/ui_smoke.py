"""UI smoke gate: render the running app and walk every dock tab.

Covers the part of R59 P0 that tests cannot reach — no vitest file imports
App.jsx, so a moved component that renders nothing is invisible to `npm test`.
This drives the real bundle in Chromium and fails on: a render crash reaching
ErrorBoundary, an uncaught page error, a missing/empty dock tab, or a tab that
still shows the "select a session" placeholder (the #228 symptom).

Usage (server must already be running; default http://127.0.0.1:8765):

    uv run python tools/ui_smoke.py
    uv run python tools/ui_smoke.py --base http://127.0.0.1:8765 --shots .scratch/shots

Exit code 0 = every tab rendered. 1 = at least one check failed. Requires the
`playwright` dev dependency and `playwright install chromium`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCK_TABS = [
    "Diff", "Graph", "Planning", "Artifacts", "Notes", "Renders", "Terminal",
    "Processes", "Output", "Waterfall", "Trace", "Cost", "Memory", "MCP",
    "Config", "Standards",
]
PLACEHOLDER = "Select a session to see diffs, files, cost and trace."
CRASH_MARKER = "UI crashed"


def run(base: str, shots: Path | None) -> tuple[dict, int]:
    report: dict = {"base": base, "tabs": {}, "console_errors": [], "page_errors": []}
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.on(
            "console",
            lambda m: report["console_errors"].append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: report["page_errors"].append(str(e)))

        page.goto(base, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(1500)  # let the initial session/config fetches settle
        if shots:
            page.screenshot(path=str(shots / "01-boot.png"))

        if CRASH_MARKER in page.content():
            report["crashed"] = "on boot"
            browser.close()
            return report, 1

        found = 0
        for name in DOCK_TABS:
            button = page.get_by_role("button", name=name, exact=True)
            if button.count() == 0:
                report["tabs"][name] = "MISSING"
                continue
            found += 1
            button.first.click()
            page.wait_for_timeout(900)
            crashed = CRASH_MARKER in page.content()
            # The dock is the section that owns the Diff tab button.
            dock = page.locator("section", has=page.get_by_role("button", name="Diff", exact=True))
            text = dock.first.inner_text() if dock.count() else page.inner_text("body")
            report["tabs"][name] = {
                "crashed": crashed,
                "placeholder": PLACEHOLDER in text,
                "chars": len(text),
            }
            if shots:
                page.screenshot(path=str(shots / f"tab-{name}.png"))
            if crashed:
                break

        report["tab_count"] = found
        browser.close()

    failed = (
        report.get("crashed") is not None
        or report["page_errors"]
        or report["tab_count"] != len(DOCK_TABS)
        or any(
            isinstance(v, str) or v["crashed"] or v["placeholder"]
            for v in report["tabs"].values()
        )
    )
    return report, 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765", help="running app URL")
    parser.add_argument("--shots", default="", help="directory for screenshots (omit to skip)")
    args = parser.parse_args()

    report, code = run(args.base, Path(args.shots) if args.shots else None)
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
