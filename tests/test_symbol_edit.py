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
"""R22 #40: symbol-based edit tool (edit_symbol).

The tool takes (path, symbol, new_body), locates the def/class byte span via
stdlib ast, and replaces it verbatim through the same R12 pipeline as
edit_file (verbatim read, staleness check, atomic write, verification).
"""

import pytest
from pydantic_ai import ModelRetry


def _tool(workdir, name, **kwargs):
    from codingdude.tools import build_toolset

    return build_toolset(workdir, **kwargs).tools[name].function


MODULE = '''import os


def helper(x):
    return x + 1


class Greeter:
    prefix = 'hi'

    def greet(self, name):
        return f"{self.prefix} {name}"


def tail():
    return None
'''


def test_edit_symbol_replaces_function(tmp_path):
    f = tmp_path / 'mod.py'
    f.write_text(MODULE)
    out = _tool(tmp_path, 'edit_symbol')(
        'mod.py', 'helper', 'def helper(x):\n    return x * 2\n'
    )
    assert 'edited' in out
    text = f.read_text()
    assert 'return x * 2' in text
    assert 'return x + 1' not in text
    assert 'class Greeter:' in text and 'def tail():' in text  # rest untouched
    assert 'import os' in text


def test_edit_symbol_replaces_method(tmp_path):
    f = tmp_path / 'mod.py'
    f.write_text(MODULE)
    _tool(tmp_path, 'edit_symbol')(
        'mod.py', 'Greeter.greet', '    def greet(self, name):\n        return name\n'
    )
    text = f.read_text()
    assert '        return name\n' in text
    assert 'self.prefix} {name}' not in text
    assert "prefix = 'hi'" in text  # class body intact


def test_edit_symbol_preserves_line_endings_and_indent_context(tmp_path):
    crlf = tmp_path / 'crlf.py'
    crlf.write_bytes(b'def a():\r\n    return 1\r\n\r\ndef b():\r\n    return 2\r\n')
    _tool(tmp_path, 'edit_symbol')('crlf.py', 'a', 'def a():\r\n    return 9\r\n')
    data = crlf.read_bytes()
    assert b'\n' not in data.replace(b'\r\n', b'')  # CRLF stays CRLF
    assert b'return 9' in data and b'return 2' in data


def test_edit_symbol_not_found_retries(tmp_path):
    f = tmp_path / 'mod.py'
    f.write_text(MODULE)
    with pytest.raises(ModelRetry, match='not found'):
        _tool(tmp_path, 'edit_symbol')('mod.py', 'nope', 'x = 1\n')
    assert f.read_text() == MODULE  # untouched


def test_edit_symbol_ambiguous_name_retries(tmp_path):
    f = tmp_path / 'mod.py'
    f.write_text('def dup():\n    return 1\n\n\nclass C:\n\n    def dup(self):\n        return 2\n')
    with pytest.raises(ModelRetry, match='ambiguous|more than one'):
        _tool(tmp_path, 'edit_symbol')('mod.py', 'dup', 'def dup():\n    return 3\n')
    assert 'return 1' in f.read_text()  # untouched


def test_edit_symbol_non_python_refuses(tmp_path):
    f = tmp_path / 'notes.txt'
    f.write_text('just text')
    with pytest.raises(ModelRetry, match='edit_file'):
        _tool(tmp_path, 'edit_symbol')('notes.txt', 'x', 'y')
    assert f.read_text() == 'just text'


def test_edit_symbol_non_utf8_refuses(tmp_path):
    f = tmp_path / 'blob.py'
    f.write_bytes(b'def a():\n    return "\xff"\n')
    with pytest.raises(ModelRetry, match='UTF-8'):
        _tool(tmp_path, 'edit_symbol')('blob.py', 'a', 'def a():\n    return 1\n')


def test_edit_symbol_reuses_staleness_check(tmp_path):
    from codingdude.tools import build_toolset

    f = tmp_path / 'x.py'
    f.write_text('def a():\n    return 1\n')
    ts = build_toolset(tmp_path)
    ts.tools['read_file'].function('x.py')  # observe
    f.write_text('def a():\n    return 999\n')  # external writer
    with pytest.raises(ModelRetry, match='changed since'):
        ts.tools['edit_symbol'].function('x.py', 'a', 'def a():\n    return 2\n')
    assert 'return 999' in f.read_text()  # external change intact


def test_stale_retry_includes_fresh_content(tmp_path):
    """Gate diff-scope: the staleness retry carries the fresh bytes so the
    model can re-edit in one attempt instead of a separate read round-trip."""
    from codingdude.tools import build_toolset

    f = tmp_path / 'x.py'
    f.write_text('def a():\n    return 1\n')
    ts = build_toolset(tmp_path)
    ts.tools['read_file'].function('x.py')  # observe
    f.write_text('def a():\n    return FRESH_MARK\n')  # external writer
    with pytest.raises(ModelRetry, match='FRESH_MARK'):
        ts.tools['edit_file'].function('x.py', 'return 1', 'return 2\n')


def test_edit_symbol_strips_common_indentation(tmp_path):
    """New body pasted with extra indentation is dedented to column 0."""
    f = tmp_path / 'mod.py'
    f.write_text(MODULE)
    _tool(tmp_path, 'edit_symbol')(
        'mod.py', 'helper', '    def helper(x):\n        return x + 5\n'
    )
    assert 'return x + 5' in f.read_text()
