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
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ui_smoke imports playwright at module level; skip rather than error when a
# checkout has not installed it.
pytest.importorskip("playwright.sync_api")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from ui_smoke import DOCK_TABS, verdict  # noqa: E402


def clean(**overrides) -> dict:
    """A passing report; override one key to make exactly one check fail."""
    report = {"tab_count": len(DOCK_TABS), "tabs": {}}
    report.update(overrides)
    return report


def test_clean_report_passes():
    assert verdict(clean()) == 0


def test_tab_count_mismatch_fails():
    assert verdict(clean(tab_count=len(DOCK_TABS) - 1)) == 1


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
    assert verdict(clean(tab_drift={"app_jsx_only": ["X"], "smoke_only": []})) == 1
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
