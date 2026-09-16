"""R27 #54: aider-style layered matching for edit_file.

Seam 1: editmatch.replace_most_similar_chunk — pure function, returns the
        whole file with part replaced, or None if no strategy matches.
Seam 2: edit_file via build_toolset — did-you-mean feedback on no-match.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelRetry

from codingdude.editmatch import replace_most_similar_chunk
from codingdude.tools import build_toolset


def _tool(toolset, name):
    return toolset.tools[name].function


class TestExactMatch:
    def test_perfect_match_replaces_once(self):
        whole = 'a = 1\nb = 2\nc = 3\n'
        out = replace_most_similar_chunk(whole, 'b = 2\n', 'b = 20\n')
        assert out == 'a = 1\nb = 20\nc = 3\n'

    def test_no_match_returns_none(self):
        assert replace_most_similar_chunk('x = 1\n', 'y = 2\n', 'y = 3\n') is None

    def test_ambiguous_match_returns_none(self):
        whole = 'foo()\nbar()\nfoo()\n'
        assert replace_most_similar_chunk(whole, 'foo()\n', 'baz()\n') is None


class TestWhitespaceFlexible:
    def test_uniform_indent_difference_is_matched_and_fixed(self):
        # Model wrote the SEARCH block dedented; file has it indented.
        whole = 'def f():\n    return 1\n    return 2\n'
        out = replace_most_similar_chunk(
            whole, 'return 1\nreturn 2\n', 'return 42\nreturn 2\n'
        )
        assert out == 'def f():\n    return 42\n    return 2\n'


class TestLeadingBlankLine:
    def test_spurious_leading_blank_in_part_is_tolerated(self):
        whole = 'a = 1\nb = 2\nc = 3\n'
        out = replace_most_similar_chunk(whole, '\nb = 2\nc = 3\n', 'b = 20\nc = 3\n')
        assert out == 'a = 1\nb = 20\nc = 3\n'


class TestDotDotDot:
    def test_elided_middle_is_preserved(self):
        whole = 'def f():\n    a = 1\n    b = 2\n    c = 3\n'
        part = 'def f():\n...\n    c = 3\n'
        replace = 'def f():\n...\n    c = 30\n'
        out = replace_most_similar_chunk(whole, part, replace)
        assert out == 'def f():\n    a = 1\n    b = 2\n    c = 30\n'


class TestCRLF:
    def test_crlf_whole_with_lf_part_matches(self):
        whole = 'a = 1\r\nb = 2\r\n'
        out = replace_most_similar_chunk(whole, 'b = 2\n', 'b = 20\n')
        assert out == 'a = 1\r\nb = 20\r\n'


class TestEditFileFeedback:
    @pytest.fixture()
    def tmp_project(self, tmp_path: Path) -> Path:
        (tmp_path / 'mod.py').write_text(
            'def greet():\n    print("hello there")\n    return 0\n',
            encoding='utf-8',
        )
        return tmp_path

    def test_no_match_error_includes_did_you_mean(self, tmp_project: Path):
        edit = _tool(build_toolset(tmp_project), 'edit_file')
        with pytest.raises(ModelRetry) as exc:
            edit('mod.py', 'print("hello word")\n', 'print("hi")\n')
        msg = str(exc.value)
        assert 'old_text not found' in msg
        assert 'hello there' in msg  # the closest real lines

    def test_whitespace_flexible_edit_applies(self, tmp_project: Path):
        edit = _tool(build_toolset(tmp_project), 'edit_file')
        # Dedented search block, file content is indented.
        result = edit(
            'mod.py', 'return 0\n', 'return 1\n'
        )
        assert 'edited mod.py' in result
        assert '    return 1' in (tmp_project / 'mod.py').read_text('utf-8')
