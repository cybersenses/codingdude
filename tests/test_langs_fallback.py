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
"""R32 #65: tree-sitter-language-pack fallback in spec_for.

Pinned grammars stay authoritative; the pack is a fallback for suffixes with
no pin. Fallback specs are navigation-only (grammar present, no symbol
nodes), so symbol tools degrade gracefully.
"""

from tree_sitter import Parser

from codingdude.langs import spec_for


def test_unknown_suffix_still_returns_none() -> None:
    assert spec_for('.xyzzy123') is None


def test_ruby_resolves_via_pack() -> None:
    spec = spec_for('.rb')
    assert spec is not None
    parser = Parser(spec.grammar)
    tree = parser.parse(b'def foo\n  1\nend\n')
    root = tree.root_node
    assert root.type == 'program'
    assert root.child_count > 0
    assert all(c.type != 'ERROR' for c in root.children)


def test_pinned_python_unchanged() -> None:
    spec = spec_for('.py')
    assert spec is not None
    assert 'function_definition' in spec.function_nodes
    assert spec.navigation_only is False


def test_fallback_is_navigation_only() -> None:
    spec = spec_for('.rb')
    assert spec is not None
    assert spec.navigation_only is True
    assert not spec.function_nodes


def test_pack_unknown_language_returns_none() -> None:
    # A real suffix whose pack name does not exist.
    assert spec_for('.notafilesystems') is None
