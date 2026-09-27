"""Tests for the A/B micro-benchmark tool (ticket #160, R47)."""

import textwrap
from pathlib import Path

import pytest

from codingdude.bench import build_bench_toolset, run_bench


def _write_module(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    script = root / "algos.py"
    script.write_text(
        textwrap.dedent(
            """
            def slow():
                return sum(i * i for i in range(3000))


            def fast():
                n = 3000 - 1
                return n * (n + 1) * (2 * n + 1) // 6
            """
        ),
        encoding="utf-8",
    )
    return script


async def test_run_bench_ranks_candidates(tmp_path: Path) -> None:
    _write_module(tmp_path)
    result = await run_bench(
        tmp_path, "algos.py", ["slow", "fast"], repeat=3, inner=20, timeout=120,
    )
    assert "error" not in result
    by_name = {row["entry"]: row for row in result["candidates"]}
    assert set(by_name) == {"slow", "fast"}
    assert by_name["fast"]["best_s"] < by_name["slow"]["best_s"]
    assert result["winner"] == "fast"


async def test_run_bench_missing_file_fails_closed(tmp_path: Path) -> None:
    result = await run_bench(tmp_path, "nope.py", ["a"], timeout=60)
    assert "error" in result
    assert "nope.py" in result["error"]


async def test_run_bench_unknown_entry_fails_closed(tmp_path: Path) -> None:
    _write_module(tmp_path)
    result = await run_bench(tmp_path, "algos.py", ["missing_fn"], timeout=120)
    assert "error" in result
    assert "missing_fn" in result["error"]


async def test_run_bench_path_escape_fails_closed(tmp_path: Path) -> None:
    result = await run_bench(tmp_path, "../outside.py", ["a"], timeout=60)
    assert "error" in result


async def test_toolset_lists_compare_benchmark(tmp_path: Path) -> None:
    toolset = build_bench_toolset(tmp_path)
    assert "compare_benchmark" in toolset.tools


async def test_toolset_model_retry_on_bad_path(tmp_path: Path) -> None:
    from pydantic_ai import ModelRetry

    toolset = build_bench_toolset(tmp_path)
    with pytest.raises(ModelRetry, match="missing.py"):
        await toolset.tools["compare_benchmark"].function(
            path="missing.py", entries=["a"],
        )
