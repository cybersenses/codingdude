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
"""Tests for describe_ast_change (R22 #41)."""

from codingdude.astdiff import describe_ast_change


def test_no_change_returns_empty():
    src = 'def f():\n    return 1\n'
    assert describe_ast_change(src, src) == ''


def test_added_symbol():
    before = 'def f():\n    return 1\n'
    after = before + 'def g(x):\n    return x\n'
    out = describe_ast_change(before, after)
    assert 'added g' in out
    assert 'def g(x)' in out


def test_removed_symbol():
    before = 'def f():\n    return 1\n\n\ndef g():\n    return 2\n'
    after = 'def f():\n    return 1\n'
    assert 'removed g' in describe_ast_change(before, after)


def test_signature_change_reported():
    before = 'def f(a):\n    return a\n'
    after = 'def f(a, b=1):\n    return a\n'
    out = describe_ast_change(before, after)
    assert 'changed f' in out
    assert 'def f(a, b=1)' in out


def test_body_only_change():
    before = 'def f():\n    return 1\n'
    after = 'def f():\n    return 2\n'
    assert 'changed body of f' in describe_ast_change(before, after)


def test_nested_method_change():
    before = 'class C:\n    def m(self):\n        return 1\n'
    after = 'class C:\n    def m(self):\n        return 2\n'
    assert 'changed body of C.m' in describe_ast_change(before, after)


def test_unparseable_after_reports_it():
    assert describe_ast_change('def f():\n    pass\n', 'def f(:\n') == (
        '(file no longer parses as Python)'
    )
