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
"""Tests for the language registry (R26 #43).

Seam: `langs.spec_for(suffix)` returns a `LanguageSpec` (grammar, function
node kinds, class node kinds, name field) or None for unknown suffixes.
`langs.language_for(suffix)` stays as the backward-compatible grammar lookup.
"""

from tree_sitter import Language

from codingdude.langs import language_for, spec_for


def test_python_spec_has_grammar_and_node_kinds():
    spec = spec_for('.py')
    assert spec is not None
    assert isinstance(spec.grammar, Language)
    assert 'function_definition' in spec.function_nodes
    assert 'class_definition' in spec.class_nodes
    assert spec.name_field == 'name'


def test_typescript_and_tsx_get_typescript_grammar():
    ts = spec_for('.ts')
    tsx = spec_for('.tsx')
    assert ts is not None and tsx is not None
    assert 'function_declaration' in ts.function_nodes
    assert 'class_declaration' in ts.class_nodes
    assert ts.name_field == 'name'


def test_javascript_and_js_variants_get_js_grammar():
    for suffix in ('.js', '.jsx', '.mjs'):
        spec = spec_for(suffix)
        assert spec is not None, suffix
        assert 'function_declaration' in spec.function_nodes
        assert 'class_declaration' in spec.class_nodes


def test_unknown_suffix_returns_none():
    assert spec_for('.xyz') is None
    assert spec_for('') is None


def test_suffix_matching_is_case_insensitive():
    assert spec_for('.TS') is not None
    assert spec_for('.Py') is not None


def test_language_for_backward_compat():
    assert isinstance(language_for('.ts'), Language)
    assert isinstance(language_for('.js'), Language)
    assert isinstance(language_for('.py'), Language)
