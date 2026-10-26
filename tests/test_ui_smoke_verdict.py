# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""The smoke gate's verdict, exercised without a browser (#233).

`tools/` is outside the ruff/mypy/pytest scope, so a gate that silently stopped
failing would not be noticed by anything else. These tests are the only proof
that each failure branch actually returns 1 — and they run in milliseconds,
unlike the live gate, which needs a server, Chromium and ~40 seconds.

Nothing here needs Playwright: `ui_smoke` imports it inside `run()`, so these
run on a checkout with no dev extra. Importing it at `ui_smoke`'s module level
made this whole file skip — exit 0, every branch unproven — which is the silent
loss of proof the tests exist to prevent.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from ui_smoke import (  # noqa: E402
    DOCK_PANELS,
    _no_readme_reason,
    _panel_banner_selector,
    catalogue_panels,
    verdict,
)


def test_panel_banner_selector_matches_the_root_and_nested_shapes():
    """Under `?layout=dock` the panel's banner *is* the panel root, not a child.

    `Locator.locator()` matches descendants only, so the scoped search that
    looked correct matched zero against `DiffTabPanel`'s failure state — where
    `data-panel` and `data-poll-error` sit on the same div — and the gate
    reported a failing panel as clean. Pins both alternatives so that form
    cannot quietly come back.

    The nested alternative is the live shape — every store-backed panel
    (`TopicPanel` in workspace/panels.jsx) renders its banner inside the
    `data-panel` root — and the root shape remains for panels whose banner is
    the whole body. Both are pinned.

    This pins the selector *string*; it does not run a browser. What it does
    guarantee is that the attribute is not retyped here: the halves are built
    from `POLL_ERROR_SELECTOR`.
    """
    sel = _panel_banner_selector("diff")
    assert sel == (
        '[data-panel="diff"][data-poll-error], [data-panel="diff"] [data-poll-error]'
    )
    # Every comma-separated alternative is scoped; a lone attribute would match
    # every panel at once, which is the over-report this replaced.
    for part in sel.split(","):
        assert part.strip().startswith('[data-panel="diff"]')


def test_panel_banner_selector_quotes_every_id():
    """Every panel id is quoted — a convention, and the reason is not validity.

    `[data-panel=diff]` is valid CSS and matches: the ids are plain identifiers,
    so quoting changes nothing for them. Probed rather than assumed, and the
    assumed failure mode was wrong twice over: an unparsable selector makes
    `Locator.count` raise a `SyntaxError`, it does not quietly return 0 — the
    silent zero was the root-vs-descendant bug, a different failure entirely.

    What quoting buys is an id that needs escaping. `[data-panel=a b]` is a
    descendant selector, so a future id containing a space would change what the
    selector means while still parsing, and this gate would then read the wrong
    element. Keeping every id quoted means that cannot happen quietly.
    """
    for panel_id in DOCK_PANELS:
        sel = _panel_banner_selector(panel_id)
        assert sel.count(f'[data-panel="{panel_id}"]') == 2


def test_no_readme_reason_names_the_actual_cause():
    """No session, no tree, no README are different facts; say which one."""
    assert "no sessions" in _no_readme_reason({"sessions": 0})
    assert "no file tree" in _no_readme_reason({"sessions": 2, "tree_ready": False})
    assert "README.md not in the explorer" in _no_readme_reason(
        {"sessions": 2, "tree_ready": True}
    )


def test_no_readme_reason_does_not_call_a_failed_fetch_no_sessions():
    """`_record_sessions` stores `sessions: None` when GET /api/sessions fails.

    That is not the same fact as an empty workspace, and `not None` is truthy
    here, so without its own branch a server error is reported as "the workspace
    has no sessions" — a claim about the workspace made from a failed request.
    """
    reason = _no_readme_reason(
        {"sessions": None, "sessions_error": "GET /api/sessions -> 500"}
    )
    assert "GET /api/sessions -> 500" in reason
    assert "no sessions" not in reason


def clean(**overrides) -> dict:
    """A passing report; override one key to make exactly one check fail."""
    report = {"tab_count": len(DOCK_PANELS), "tabs": {}}
    report.update(overrides)
    return report


def test_clean_report_passes():
    assert verdict(clean()) == 0


def test_tab_count_mismatch_fails():
    assert verdict(clean(tab_count=len(DOCK_PANELS) - 1)) == 1


def test_missing_tab_count_fails():
    # A report with no count means the walk never finished.
    assert verdict({"tabs": {}}) == 1


def test_api_5xx_fails():
    # The hole #233 closed: a tab that 500s renders its own error text, which is
    # neither the placeholder nor a console error.
    assert verdict(clean(api_5xx=[{"url": "/api/x", "status": 500}])) == 1


def test_poll_error_banner_fails():
    tab = {"crashed": False, "placeholder": False, "poll_error": "could not load this tab: boom"}
    assert verdict(clean(tabs={"Cost": tab})) == 1


def test_crashed_tab_fails():
    tab = {"crashed": True, "placeholder": False, "poll_error": None}
    assert verdict(clean(tabs={"Graph": tab})) == 1


def test_missing_tab_fails():
    assert verdict(clean(tabs={"Diff": "MISSING"})) == 1


def test_placeholder_fails_only_with_a_session():
    tab = {"crashed": False, "placeholder": True, "poll_error": None}
    assert verdict(clean(tabs={"Diff": tab}, sessions=2)) == 1
    # No session: every session-scoped tab legitimately shows the placeholder.
    assert verdict(clean(tabs={"Diff": tab}, sessions=0)) == 0


def test_drift_and_boot_crash_fail():
    assert verdict(clean(tab_drift={"smoke_only": ["X"]})) == 1
    assert verdict(clean(crashed="on boot")) == 1


def test_benign_console_error_passes_but_a_real_one_fails():
    benign = "the server responded with a status of 401"
    noise = "Failed to load resource: the server responded with a status of 500"
    assert verdict(clean(console_errors=[benign, noise])) == 0
    assert verdict(clean(console_errors=["TypeError: x is undefined"])) == 1


def test_page_error_and_sessions_error_fail():
    assert verdict(clean(page_errors=["ReferenceError: x is not defined"])) == 1
    assert verdict(clean(sessions_error="GET /api/sessions -> 500")) == 1


def test_partial_report_does_not_raise():
    # Every key is read with a default, so a hand-built report reaches a verdict
    # instead of raising KeyError (the #233 version did).
    assert verdict({}) == 1
    assert verdict({"api_5xx": [{"status": 503}]}) == 1


# --- R59: the dock shell's checks --------------------------------------------


def dock_report(**overrides) -> dict:
    """A passing dock report: five visible preset panels, monaco reflow."""
    panels = {
        title: {"crashed": False, "placeholder": False, "poll_error": None, "chars": 40, "visible": True}
        for title in ("Projects & sessions", "Explorer", "Editor", "Chat", "Diff")
    }
    report = {
        "expected_entries": 5,
        "tab_count": 5,
        "tabs": panels,
        "monaco": {"width_before": 634, "width_narrowed": 460, "width_restored": 634},
    }
    report.update(overrides)
    return report


def test_dock_report_passes():
    assert verdict(dock_report()) == 0


def test_dock_expected_count_comes_from_the_report():
    # The count check must follow the walk's own report, not a hardcoded list.
    assert verdict(dock_report(tab_count=4)) == 1
    assert verdict(dock_report(expected_entries=4)) == 1


def test_dock_missing_or_invisible_panel_fails():
    missing = dock_report()
    missing["tabs"]["Diff"] = "MISSING"
    assert verdict(missing) == 1
    hidden = dock_report()
    hidden["tabs"]["Chat"] = {
        "crashed": False, "placeholder": False, "poll_error": None, "chars": 0, "visible": False,
    }
    assert verdict(hidden) == 1


def test_panel_drift_fails():
    drift = {"nav": {"smoke": "Projects & sessions", "catalogue": "Projects"}}
    assert verdict(dock_report(panel_drift=drift)) == 1


def test_monaco_that_never_reflows_fails():
    # An editor that keeps the width it had while its container narrows. What
    # makes the real check go red is dropping `automaticLayout` from Monaco's
    # options — not `renderer: 'always'`, which only matters for a hidden panel
    # and no hide happens here.
    stale = {"width_before": 634, "width_narrowed": 634, "width_restored": 634}
    assert verdict(dock_report(monaco=stale)) == 1
    # Reflowing once and then sticking is the same failure one step later: the
    # restore never happened. This is what the two-direction assertion buys.
    stuck = {"width_before": 634, "width_narrowed": 460, "width_restored": 460}
    assert verdict(dock_report(monaco=stuck)) == 1
    # A measurement that did not happen is not a pass either.
    assert verdict(dock_report(monaco={"width_before": 634, "width_narrowed": None})) == 1
    # A string means the check could not run at all — that is not a pass.
    assert verdict(dock_report(monaco="the editor never mounted")) == 1


def test_catalogue_is_readable_so_the_count_has_a_source():
    # The panel list is duplicated: TS declares what the shell builds, this file
    # declares what the gate walks. If the regex stops matching `catalogue.ts`
    # the walk is compared against a catalogue it cannot read, so the parse seam
    # is asserted here. (The failure is not silent: an unreadable catalogue sets
    # `panel_drift`, which `verdict` fails on.)
    assert set(catalogue_panels()) == set(DOCK_PANELS)


def test_visible_key_absence_does_not_fail_a_tab():
    # `visible` is absent from a bare tab report; absent must not read as
    # False, or every hand-built report would fail. The tab entry is what
    # makes this a test rather than a repeat of `test_clean_report_passes`:
    # without one, the `visible` branch is never reached and the assertion
    # cannot fail.
    bare_tab = {"crashed": False, "placeholder": False, "poll_error": None, "chars": 40}
    assert verdict(clean(tabs={"Diff": bare_tab})) == 0
