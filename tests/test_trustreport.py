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

def test_mutation_evidence_surfaced_when_cache_exists(tmp_path: Path) -> None:
    import sqlite3

    from codingdude.trustreport import build_trust_report

    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "widget.py").write_text("x = 1" + chr(10), encoding="utf-8")
    db = sqlite3.connect(tmp_path / ".mutmut-cache")
    db.executescript(
        'CREATE TABLE "SourceFile" (id INTEGER PRIMARY KEY, filename TEXT, hash TEXT);'
        'CREATE TABLE "Line" (id INTEGER PRIMARY KEY, sourcefile INTEGER, line TEXT, line_number INTEGER);'
        'CREATE TABLE "Mutant" (id INTEGER PRIMARY KEY, line INTEGER, "index" INTEGER, tested_against_hash TEXT, status TEXT);'
    )
    db.execute("INSERT INTO SourceFile VALUES (1, ?, 'h')", ('src' + chr(92) + 'widget.py',))
    db.execute("INSERT INTO Line VALUES (1, 1, 'x = 1', 1)")
    db.execute("INSERT INTO Mutant VALUES (1, 1, 0, 'h', 'bad_survived')")
    db.commit()
    db.close()

    report = build_trust_report(str(tmp_path), "src/widget.py")
    assert report["mutation"]["survived"] == 1


def test_no_mutation_key_without_cache(tmp_path: Path) -> None:
    from codingdude.trustreport import build_trust_report

    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "widget.py").write_text("x = 1" + chr(10), encoding="utf-8")
    report = build_trust_report(str(tmp_path), "src/widget.py")
    assert "mutation" not in report
