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
import ast
import warnings

from codingdude.pyparse import parse_python


def test_parse_python_suppresses_syntaxwarning():
    src = 'x = "\\s*JOINT\\s+(\\w+)"'  # invalid escape in non-raw string

    with warnings.catch_warnings():
        warnings.simplefilter('error', SyntaxWarning)
        tree = parse_python(src)  # would raise if the warning leaked

    assert isinstance(tree, ast.Module)


def test_parse_python_still_raises_on_syntax_error():
    import pytest

    with pytest.raises(SyntaxError):
        parse_python('def broken(:')
