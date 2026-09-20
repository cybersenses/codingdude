"""Trust-my-tests report (ticket #103): static evidence tying source files to tests."""
from pathlib import Path

from codingdude.trustreport import build_trust_report


def _mk(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_finds_tests_that_reference_module(tmp_path: Path) -> None:
    _mk(tmp_path, "src/codingdude/widget.py", "def spin(): ...\n")
    _mk(tmp_path, "tests/test_widget.py", "from codingdude.widget import spin\n")
    _mk(tmp_path, "tests/test_other.py", "import codingdude.other  # noqa\n")
    report = build_trust_report(str(tmp_path), "src/codingdude/widget.py")
    assert report["referencing_tests"] == ["tests/test_widget.py"]


def test_flags_property_tests(tmp_path: Path) -> None:
    _mk(tmp_path, "src/codingdude/widget.py", "x = 1\n")
    _mk(
        tmp_path,
        "tests/test_widget.py",
        "from hypothesis import given\nfrom codingdude import widget\n\n\n@given(st.integers())\ndef test_it(n):\n    assert widget.x\n",
    )
    report = build_trust_report(str(tmp_path), "src/codingdude/widget.py")
    assert report["referencing_tests"] == ["tests/test_widget.py"]
    assert report["property_test_files"] == ["tests/test_widget.py"]


def test_no_evidence_reported_honestly(tmp_path: Path) -> None:
    _mk(tmp_path, "src/codingdude/widget.py", "x = 1\n")
    report = build_trust_report(str(tmp_path), "src/codingdude/widget.py")
    assert report["referencing_tests"] == []
    assert report["property_test_files"] == []
