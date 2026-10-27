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


def _fake_symbol() -> str:
    """A symbol that is in no tracked file.

    Assembled rather than written out: this test file is itself tracked source, so
    a literal fake symbol would find itself in the corpus the check searches and
    the check would look broken exactly where it is right.
    """
    return "zz_" + "not_a_real" + "_symbol"


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


def test_gitignored_paths_are_not_verifiable_here():
    """A build artefact is absent from a fresh checkout, so asserting on it
    describes the machine that ran the check, not the document.

    Probe for the bug this fixes: a `git worktree` of HEAD, where `frontend/dist/`,
    `node_modules/` and `.scratch/` do not exist, failed 4 of the 7 living docs.
    """
    assert cc.check_paths("See `frontend/node_modules/some-pkg/index.js`.") == []
    assert cc.check_paths("See `src/codingdude/store.py`.") != []


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
    assert cc.check_paths("Per-project overrides live in `.codingdude.toml`.") == []
    assert cc.check_paths("Run artefacts land in `traces/`, `uploads/`, `logs/`.") == []


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
    fake = _fake_symbol()
    assert cc.check_symbols(f"Handled by `{fake}`.") == [
        f"identifier not in tracked source: {fake}"
    ]


def test_known_identifier_passes():
    # `poll_error` lives in the tracked `tools/ui_smoke.py`. A symbol defined only
    # in an untracked file is invisible to the checker until that file is added,
    # which is why the sweep is meaningful at commit time rather than before.
    assert cc.check_symbols("Handled by `poll_error`.") == []


def test_prose_does_not_vouch_for_an_identifier():
    """A symbol named only in a document must fail, not cite that document.

    The corpus was every tracked file's text, documents included, so any invented
    symbol written in `ROADMAP.md` found itself there and passed — a check that
    could not fail, on the exact class of claim it was built for.
    """
    sources = cc._source_files(ROOT)
    assert [name for name in sources if name.endswith(".md")] == []
    assert any(name.endswith(".py") for name in sources)


def test_run_id_fragments_are_not_symbols():
    assert cc.check_symbols("The run `G0SUN1seqSI` failed.") == []


def test_tool_names_are_not_treated_as_symbols():
    assert cc.check_symbols("Runs `pytest` and `vitest`.") == []


def test_run_is_the_single_definition_of_the_check_set():
    """`main` calls `run`, so a check added to one reaches the other."""
    text = "See `src/codingdude/store.py` and `deadbeefdeadbeef`."
    assert cc.run(text) == [
        "path does not exist: src/codingdude/store.py",
        "commit does not exist: deadbeefdeadbeef",
    ]


# --------------------------------------------------------------------------
# the CLI's default: document vs commit message
# --------------------------------------------------------------------------
def test_main_checks_identifiers_in_a_commit_message(tmp_path, capsys):
    msg = tmp_path / "msg.txt"
    msg.write_text(f"Handled by `{_fake_symbol()}`.", encoding="utf-8")
    assert cc.main(["--message-file", str(msg)]) == 1
    assert "identifier not in tracked source" in capsys.readouterr().out


def test_main_skips_identifiers_in_a_document(tmp_path):
    """A doc citing another project's API must not be reported as a defect."""
    doc = tmp_path / "doc.md"
    doc.write_text("The panel API is `DockviewApi`.", encoding="utf-8")
    assert cc.main([str(doc)]) == 0


def test_symbols_flag_forces_the_identifier_check_on_a_document(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(f"Handled by `{_fake_symbol()}`.", encoding="utf-8")
    assert cc.main(["--symbols", str(doc)]) == 1


# --------------------------------------------------------------------------
# failure-mode claims
# --------------------------------------------------------------------------
def test_failure_mode_claim_without_a_probe_is_reported():
    assert cc.check_failure_modes("An unquoted id yields invalid CSS, which is silently dropped.") == [
        "failure-mode claim without a probe: An unquoted id yields invalid CSS,"
        " which is silently dropped."
    ]


def test_failure_mode_claim_with_a_probe_annotation_passes():
    text = (
        "An unquoted id raises SyntaxError [probe: python -c \"from playwright.sync_api"
        " import sync_playwright; ...\"]."
    )
    assert cc.check_failure_modes(text) == []


def test_failure_mode_claim_marked_not_yet_verified_passes():
    text = "The pre-flight hides the server on spawn failure (not yet verified)."
    assert cc.check_failure_modes(text) == []


def test_plain_description_is_not_a_failure_mode_claim():
    assert cc.check_failure_modes("The banner shows the error message from the poll.") == []


def test_run_includes_failure_modes_when_asked():
    text = "`poll_error` can never miss a banner."
    assert cc.run(text, ROOT, symbols=False, failure_modes=True) == [
        "failure-mode claim without a probe: `poll_error` can never miss a banner."
    ]


def test_main_enforces_failure_modes_in_a_commit_message_by_default(tmp_path, capsys):
    msg = tmp_path / "msg.txt"
    msg.write_text("The gate always fails on a 5xx.", encoding="utf-8")
    assert cc.main(["--message-file", str(msg)]) == 1
    assert "failure-mode claim" in capsys.readouterr().out


def test_main_skips_failure_modes_in_a_document_by_default(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("Historically the gate silently dropped the error.", encoding="utf-8")
    assert cc.main([str(doc)]) == 0


def test_failure_modes_flag_forces_the_check_on_a_document(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("The gate silently drops the error.", encoding="utf-8")
    assert cc.main(["--failure-modes", str(doc)]) == 1


def test_no_failure_modes_flag_disables_it_for_a_message(tmp_path):
    msg = tmp_path / "msg.txt"
    msg.write_text("The gate silently drops the error.", encoding="utf-8")
    assert cc.main(["--no-failure-modes", "--message-file", str(msg)]) == 0


def test_empty_probe_annotation_does_not_count(tmp_path):
    """`[probe: ]` names no command, so it must not vouch for the claim."""
    msg = tmp_path / "msg.txt"
    msg.write_text("The gate silently drops the error [probe: ].", encoding="utf-8")
    assert cc.main(["--message-file", str(msg)]) == 1


def test_a_probe_on_a_different_bullet_does_not_vouch(tmp_path):
    """Bullets are separate claims; one line's probe proves nothing about the next."""
    msg = tmp_path / "msg.txt"
    msg.write_text(
        "* the gate silently drops the error\n* [probe: pytest -q tests/test_x.py]\n",
        encoding="utf-8",
    )
    problems = cc.check_failure_modes(msg.read_text(encoding="utf-8"))
    assert problems == [
        "failure-mode claim without a probe: * the gate silently drops the error"
    ]


def test_words_containing_a_verb_fragment_are_not_claims():
    """`pecan never` must not match `can never`; an unbounded substring cried wolf."""
    assert cc.check_failure_modes("The pecan never rots in storage.") == []


def test_a_document_is_not_failure_mode_checked_because_a_message_is_present(tmp_path):
    """Opt-in for documents must not leak from the message-file default."""
    doc = tmp_path / "doc.md"
    doc.write_text("Historically the gate silently dropped the error.", encoding="utf-8")
    msg = tmp_path / "msg.txt"
    msg.write_text("Fine message.", encoding="utf-8")
    assert cc.main([str(doc), "--message-file", str(msg)]) == 0


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
    """A stale count or renamed file in a living doc fails here, not in review.

    Paths, line references, commit references and line counts only. The
    identifier check is deliberately off here and on for commit messages: a
    document names other people's APIs (`DockviewApi`), planned ones
    (`sanitiseLayout`) and library keywords (`wal_checkpoint`) by design, so on
    prose it fires on correct text -- twelve findings on a clean pass, none of
    them a defect. In a commit message the claim being checked is "this symbol is
    mine and I just wrote it", which is the shape it can settle.
    """
    path = ROOT / doc
    if not path.exists():
        pytest.skip(f"{doc} is not in this checkout")
    problems = cc.run(path.read_text(encoding="utf-8", errors="replace"), ROOT, symbols=False)
    assert problems == [], f"{doc}: " + "; ".join(problems)
