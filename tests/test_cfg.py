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
"""Tests for the static control-flow graph analyzer (cfg.py)."""

from codingdude.cfg import build_cfg, render_mermaid_html


def _blocks(cfg):
    return {b["id"]: b for b in cfg["blocks"]}


def test_linear_code_single_block():
    src = "def f():\n    a = 1\n    b = 2\n    return a + b\n"
    cfg = build_cfg(src)
    assert len(cfg["blocks"]) == 1
    assert cfg["blocks"][0]["reachable"] is True
    assert cfg["edges"] == []


def test_if_creates_branch_and_join():
    src = "def f(x):\n    if x:\n        return 1\n    return 2\n"
    cfg = build_cfg(src)
    assert len(cfg["blocks"]) >= 3
    kinds = {(e["src"], e["kind"]) for e in cfg["edges"]}
    assert any(k == "true" for _, k in kinds)
    assert any(k == "false" for _, k in kinds)


def test_code_after_return_is_unreachable():
    src = "def f():\n    return 1\n    dead = 2\n    return dead\n"
    cfg = build_cfg(src)
    blocks = _blocks(cfg)
    dead = [b for b in blocks.values() if b["reachable"] is False]
    assert dead, "code after return must be flagged unreachable"
    assert any("dead" in ln for b in dead for ln in b["lines"])


def test_loop_back_edge():
    src = "def f():\n    i = 0\n    while i < 3:\n        i += 1\n    return i\n"
    cfg = build_cfg(src)
    back = [e for e in cfg["edges"] if e["kind"] == "back"]
    assert back, "while loop must produce a back edge"


def test_break_targets_after_loop():
    src = (
        "def f(x):\n"
        "    while True:\n"
        "        if x:\n"
        "            break\n"
        "    return 0\n"
    )
    cfg = build_cfg(src)
    assert all(b["reachable"] for b in cfg["blocks"])


def test_raises_are_terminators():
    src = "def f():\n    raise ValueError('x')\n    never = 1\n"
    cfg = build_cfg(src)
    dead = [b for b in cfg["blocks"] if not b["reachable"]]
    assert any(any("never" in ln for ln in b["lines"]) for b in dead)


def test_empty_function_single_empty_block():
    src = "def f():\n    pass\n"
    cfg = build_cfg(src)
    assert len(cfg["blocks"]) >= 1


def test_syntax_error_fails_fast():
    import pytest

    with pytest.raises(SyntaxError):
        build_cfg("def f(:\n")


def test_mermaid_html_colors_blocks():
    src = "def f():\n    return 1\n    dead = 2\n"
    html = render_mermaid_html(src, "demo.py")
    assert "#baf7d0" in html or "#22c55e" in html, "green for reachable"
    assert "#f8d0d0" in html or "#ef4444" in html, "red for dead"
    assert "demo.py" in html
