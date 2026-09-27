"""Tests for the API fuzzing gate (ticket #159, R47)."""

import textwrap
from pathlib import Path

import pytest

from codingdude.fuzzing import build_fuzz_toolset, fuzz_api

_CLEAN_APP = textwrap.dedent(
    """
    from fastapi import FastAPI

    app = FastAPI()


    @app.post("/echo")
    def echo(payload: dict):
        return {"ok": True}
    """
)

_CRASHY_APP = textwrap.dedent(
    """
    from fastapi import FastAPI

    app = FastAPI()


    @app.post("/divide")
    def divide(payload: dict):
        # 500s whenever the fuzzed body has a non-positive value.
        if any(isinstance(v, int) and v <= 0 for v in payload.values()):
            raise RuntimeError("boom")
        return {"ok": True}
    """
)


async def test_fuzz_api_clean_app_reports_no_crashes(tmp_path: Path) -> None:
    (tmp_path / "api.py").write_text(_CLEAN_APP, encoding="utf-8")
    result = await fuzz_api(tmp_path, "api.py", max_examples=15, timeout=180)
    assert "error" not in result, result
    assert result["routes_fuzzed"] >= 1
    assert result["crashes"] == []


async def test_fuzz_api_finds_crashing_route(tmp_path: Path) -> None:
    (tmp_path / "api.py").write_text(_CRASHY_APP, encoding="utf-8")
    result = await fuzz_api(tmp_path, "api.py", max_examples=25, timeout=180)
    assert "error" not in result, result
    assert any("/divide" in c["route"] for c in result["crashes"])


async def test_fuzz_api_missing_file_fails_closed(tmp_path: Path) -> None:
    result = await fuzz_api(tmp_path, "nope.py", timeout=60)
    assert "error" in result
    assert "nope.py" in result["error"]


async def test_fuzz_api_no_app_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "plain.py").write_text("x = 1\n", encoding="utf-8")
    result = await fuzz_api(tmp_path, "plain.py", timeout=120)
    assert "error" in result
    assert "app" in result["error"]


async def test_toolset_lists_fuzz_api(tmp_path: Path) -> None:
    toolset = build_fuzz_toolset(tmp_path)
    assert "fuzz_api" in toolset.tools


async def test_toolset_model_retry_on_bad_path(tmp_path: Path) -> None:
    from pydantic_ai import ModelRetry

    toolset = build_fuzz_toolset(tmp_path)
    with pytest.raises(ModelRetry, match="missing.py"):
        await toolset.tools["fuzz_api"].function(path="missing.py")
