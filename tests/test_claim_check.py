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
"""Tests for the claim checker (#R60).

`tools/claim_check.py` exists because six consecutive commits carried a written
claim the code did not support, and no gate could contradict prose. A checker
with no tests would be the same defect one level up: a guard nothing has proven
fails. So each check is exercised twice here — once on a claim that must be
caught, once on a near-identical claim that must not be — because the first
version of this tool produced 157 findings, almost all false, and a check that
cries wolf gets ignored.

The last test is the one that matters day to day: it holds the living documents
to zero unsupported claims, so a stale count or a renamed file fails the suite
instead of waiting for a reviewer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import claim_check as cc  # noqa: E402 - after the sys.path insert by design


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------
def test_missing_path_is_reported():
    assert cc.check_paths("See `src/codingdude/store.py` for the writer.") == [
        "path does not exist: src/codingdude/store.py"
    ]


def test_existing_path_passes():
    assert cc.check_paths("See `src/codingdude/db.py` for the writer.") == []


def test_bare_basename_resolves_against_the_tracked_tree():
    """Docs name modules by basename; `tools.py` means `src/codingdude/tools.py`."""
    assert cc.check_paths("The registry lives in `tools.py`.") == []


def test_root_level_file_passes():
    """A root-level file has no "/" before it; the first version missed these."""
    assert cc.check_paths("Configured in `pyproject.toml`.") == []


def test_directory_claim_resolves_by_prefix():
    assert cc.check_paths("Sources live under `docs/`.") == []
    assert cc.check_paths("Sources live under `no-such-dir/`.") == [
        "path does not exist: no-such-dir/"
    ]


def test_removal_marker_silences_a_deliberate_absence():
    """Naming a file that no longer exists is a decision, so it must be markable."""
    text = "Corrected `store.py` (removed) to `db.py`."
    assert cc.check_paths(text) == []


def test_placeholder_paths_are_not_claims():
    assert cc.check_paths("Written to `reference/research/<slug>.md`.") == []


def test_prose_with_a_slash_is_not_a_path_claim():
    assert cc.check_paths("See `resolve_workdir_path/_file` for the shape.") == []


def test_runtime_files_are_exempt():
    """`config.toml` is `~/.codingdude/config.toml`, outside this repo."""
    assert cc.check_paths("Keys live in `config.toml`.") == []


# --------------------------------------------------------------------------
# line references, hashes, line counts
# --------------------------------------------------------------------------
def test_line_reference_past_end_of_file_is_reported():
    target = "tools/claim_check.py"
    total = len((ROOT / target).read_text(encoding="utf-8").splitlines())
    assert cc.check_line_refs(f"See `{target}:{total + 1}`.") == [
        f"line reference past end of file: {target}:{total + 1} ({ROOT / target} has {total} lines)"
    ]


def test_line_reference_inside_the_file_passes():
    assert cc.check_line_refs("See `tools/claim_check.py:1`.") == []


def test_unknown_commit_is_reported():
    assert cc.check_hashes("Fixed in `deadbeefdeadbeef`.") == [
        "commit does not exist: deadbeefdeadbeef"
    ]


def test_known_commit_passes():
    head = cc._git(["rev-parse", "--short=7", "HEAD"], ROOT).stdout.strip()
    assert head, "git rev-parse returned nothing"
    assert cc.check_hashes(f"Fixed in `{head}`.") == []


def test_line_count_mismatch_is_reported(tmp_path):
    subject = tmp_path / "five.py"
    subject.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    problems = cc.check_line_counts("`five.py` is 6 lines.", root=tmp_path)
    assert problems == ["line count for five.py: claimed 6, measured 5"]


def test_matching_line_count_passes(tmp_path):
    subject = tmp_path / "five.py"
    subject.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    assert cc.check_line_counts("`five.py` is 5 lines.", root=tmp_path) == []


def test_historical_line_count_is_not_a_live_claim():
    assert cc.check_line_counts("`frontend/src/App.jsx` was 1337 lines (historical: P0).") == []


# --------------------------------------------------------------------------
# identifiers
# --------------------------------------------------------------------------
def test_unknown_identifier_is_reported():
    # Assembled rather than written out: once this test file is tracked, its own
    # text is part of the searched source, so a literal fake symbol would find
    # itself and the check would look broken when it is right.
    fake = "zz_" + "not_a_real" + "_symbol"
    assert cc.check_symbols(f"Handled by `{fake}`.") == [
        f"identifier not in tracked source: {fake}"
    ]


def test_known_identifier_passes():
    # `poll_error` lives in the tracked `tools/ui_smoke.py`. A symbol defined only
    # in an untracked file is invisible to the checker until that file is added,
    # which is why the sweep is meaningful at commit time rather than before.
    assert cc.check_symbols("Handled by `poll_error`.") == []


def test_tool_names_are_not_treated_as_symbols():
    assert cc.check_symbols("Runs `pytest` and `vitest`.") == []


# --------------------------------------------------------------------------
# the enforcement path
# --------------------------------------------------------------------------
def test_a_false_claim_appended_to_a_real_document_is_caught(tmp_path):
    """Teeth for the living-docs test: the same code path, on a doctored copy."""
    original = (ROOT / "code-design.md").read_text(encoding="utf-8")
    doctored = tmp_path / "code-design.md"
    doctored.write_text(
        original + "\nThe writer lives in `src/codingdude/store.py`.\n",
        encoding="utf-8",
    )
    problems = cc.run(doctored.read_text(encoding="utf-8"), ROOT)
    assert any("store.py" in problem for problem in problems)


@pytest.mark.parametrize("doc", cc.STRICT_DOCS)
def test_living_documents_carry_no_unsupported_claims(doc):
    """A stale count or renamed file in a living doc fails here, not in review."""
    path = ROOT / doc
    if not path.exists():
        pytest.skip(f"{doc} is not in this checkout")
    problems = cc.run(path.read_text(encoding="utf-8", errors="replace"), ROOT)
    assert problems == [], f"{doc}: " + "; ".join(problems)
