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
"""R26 #45: grammar batch — C, C++, C#, Rust, Go, Kotlin registry entries.

Seam: `langs.spec_for(suffix)` returns specs with correct node kinds, and
`tsedit.ts_symbol_spans` resolves symbols through them (C/C++ function names
live in a declarator chain, not a direct 'name' field).
"""

import pytest

from codingdude.langs import spec_for
from codingdude.tsedit import ts_symbol_spans

EXPECTED = {
    '.c': 'c',
    '.h': 'c',
    '.cpp': 'cpp',
    '.cc': 'cpp',
    '.cxx': 'cpp',
    '.hpp': 'cpp',
    '.cs': 'c_sharp',
    '.rs': 'rust',
    '.go': 'go',
    '.kt': 'kotlin',
    '.kts': 'kotlin',
}


@pytest.mark.parametrize('suffix', sorted(EXPECTED))
def test_suffix_registered(suffix):
    spec = spec_for(suffix)
    assert spec is not None, suffix
    assert spec.function_nodes or spec.class_nodes


def test_unregistered_still_none():
    # R32 #65: real languages now fall back to tree-sitter-language-pack
    # (e.g. '.pl' resolves Perl navigation-only); only truly unknown
    # suffixes return None.
    assert spec_for('.definitelynotalanguage') is None
    perl = spec_for('.pl')
    assert perl is not None
    assert perl.navigation_only is True


def test_c_function_name_via_declarator_chain():
    spec = spec_for('.c')
    assert spec is not None
    src = b'int add(int a, int b) {\n  return a + b;\n}\n'
    spans = ts_symbol_spans(src, spec)
    assert 'add' in spans


def test_cpp_class_and_method_spans():
    spec = spec_for('.cpp')
    assert spec is not None
    src = b'''
class Widget {
 public:
  int greet() { return 1; }
};
'''
    spans = ts_symbol_spans(src, spec)
    assert 'Widget' in spans
    assert 'Widget.greet' in spans


def test_rust_impl_methods():
    spec = spec_for('.rs')
    assert spec is not None
    src = b'''
fn add(a: i32, b: i32) -> i32 { a + b }
impl Point {
  fn norm(&self) -> i32 { self.x }
}
'''
    spans = ts_symbol_spans(src, spec)
    assert 'add' in spans
    assert 'Point.norm' in spans


def test_go_functions_and_methods():
    spec = spec_for('.go')
    assert spec is not None
    src = b'''
package main

func add(a int, b int) int { return a + b }
'''
    spans = ts_symbol_spans(src, spec)
    assert 'add' in spans


def test_csharp_class_method():
    spec = spec_for('.cs')
    assert spec is not None
    src = b'''
public class Widget {
  public int Add(int a, int b) {
    return a + b;
  }
}
'''
    spans = ts_symbol_spans(src, spec)
    assert 'Widget' in spans
    assert 'Widget.Add' in spans


def test_kotlin_class_method():
    spec = spec_for('.kt')
    assert spec is not None
    src = b'''
class Widget {
  fun greet(name: String): String {
    return "hi " + name
  }
}
'''
    spans = ts_symbol_spans(src, spec)
    assert 'Widget' in spans
    assert 'Widget.greet' in spans
