"""Mutation-testing evidence seams (ticket #156, R47)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codingdude.mutation import (
    build_mutation_toolset,
    mutation_cache_evidence,
    run_mutation,
)


@pytest.fixture()
def mut_project(tmp_path: Path) -> Path:
    """A tiny project with one mutant-bearing module and one killing test."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "mod_smoke.py").write_text(
        "def add(a, b):" + chr(10) + "    return a + b" + chr(10),
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_mod_smoke.py").write_text(
        "import sys, os\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))\n"
        "from mod_smoke import add\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
        "    assert add(-1, 1) == 0\n",
        encoding="utf-8",
    )
    return tmp_path


def _seed_cache(workdir: Path, statuses: list[str]) -> None:
    db = sqlite3.connect(workdir / ".mutmut-cache")
    db.executescript(
        'CREATE TABLE "SourceFile" (id INTEGER PRIMARY KEY, filename TEXT, hash TEXT);'
        'CREATE TABLE "Line" (id INTEGER PRIMARY KEY, sourcefile INTEGER, line TEXT, line_number INTEGER);'
        'CREATE TABLE "Mutant" (id INTEGER PRIMARY KEY, line INTEGER, "index" INTEGER, tested_against_hash TEXT, status TEXT);'
    )
    db.execute("INSERT INTO SourceFile VALUES (1, 'mod_smoke.py', 'h')")
    for i, status in enumerate(statuses, start=1):
        db.execute("INSERT INTO Line VALUES (?, 1, 'return a + b', 2)", (i,))
        db.execute("INSERT INTO Mutant VALUES (?, 1, 0, 'h', ?)", (i, status))
    db.commit()
    db.close()


def test_cache_evidence_counts_statuses(tmp_path: Path) -> None:
    _seed_cache(tmp_path, ["ok_killed", "bad_survived", "bad_timeout", "untested"])
    ev = mutation_cache_evidence(tmp_path)
    assert ev["available"] is True
    assert ev["total"] == 4
    assert ev["killed"] == 1
    assert ev["survived"] == 1
    assert ev["timeout"] == 1
    assert ev["untested"] == 1
    assert ev["surviving_locations"] == [
        {"file": "mod_smoke.py", "line": 2, "text": "return a + b"}
    ]


def test_cache_evidence_scopes_to_file(tmp_path: Path) -> None:
    _seed_cache(tmp_path, ["bad_survived"])
    (tmp_path / "mod_smoke.py").write_text("x = 1" + chr(10), encoding="utf-8")
    ev = mutation_cache_evidence(tmp_path, "mod_smoke.py")
    assert ev["available"] is True
    assert ev["survived"] == 1
    missing = mutation_cache_evidence(tmp_path, "nope.py")
    assert missing["available"] is False
    assert "not found" in missing["reason"]


def test_cache_evidence_without_cache(tmp_path: Path) -> None:
    ev = mutation_cache_evidence(tmp_path)
    assert ev["available"] is False


async def test_run_mutation_requires_tests(tmp_path: Path) -> None:
    result = await run_mutation(tmp_path)
    assert "no tests/ directory" in result["error"]


async def call_tool(toolset, name, args):
    tool = toolset.tools[name]
    return await tool.function(**args)


async def test_toolset_reports_survivors(mut_project: Path, monkeypatch) -> None:
    _seed_cache(mut_project, ["bad_survived", "ok_killed"])

    async def fake_run(workdir, rel_path=None, timeout=1800):
        return mutation_cache_evidence(mut_project, rel_path)

    monkeypatch.setattr("codingdude.mutation.run_mutation", fake_run)
    out = await call_tool(
        build_mutation_toolset(mut_project), "run_mutation_suite",
        {"path": "mod_smoke.py"},
    )
    assert "1/2 killed" in out
    assert "survived mod_smoke.py:2" in out


async def test_toolset_retries_on_error(tmp_path: Path) -> None:
    import pydantic_ai

    with pytest.raises(pydantic_ai.ModelRetry):
        await call_tool(
            build_mutation_toolset(tmp_path), "run_mutation_suite", {},
        )
