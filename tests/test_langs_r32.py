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
"""R32 #64: Java, PHP, Bash (functions) + JSON/YAML/TOML tier-2 nav keys.

Seams: `langs.spec_for` (registry entries), `langs.NAV_SUFFIXES`,
`tsedit.ts_symbol_spans` (structural symbols), `tsedit.nav_symbols`
(navigation keys for config languages), `edit_symbol` refusal for
navigation-only suffixes.
"""

from codingdude.langs import NAV_SUFFIXES, spec_for
from codingdude.tsedit import nav_symbols, ts_symbol_spans


def test_java_spec_tier3():
    spec = spec_for('.java')
    assert spec is not None
    assert not spec.navigation_only
    assert 'method_declaration' in spec.function_nodes
    assert 'class_declaration' in spec.class_nodes


def test_php_spec_tier3():
    spec = spec_for('.php')
    assert spec is not None
    assert not spec.navigation_only
    assert 'function_definition' in spec.function_nodes
    assert 'method_declaration' in spec.function_nodes
    assert 'class_declaration' in spec.class_nodes


def test_bash_spec_functions_only():
    spec = spec_for('.sh')
    assert spec is not None
    assert not spec.navigation_only
    assert 'function_definition' in spec.function_nodes
    assert not spec.class_nodes


def test_config_languages_navigation_only():
    for suffix in ('.json', '.yaml', '.yml', '.toml'):
        spec = spec_for(suffix)
        assert spec is not None, suffix
        assert spec.navigation_only, suffix
    assert {'.json', '.yaml', '.yml', '.toml'} <= NAV_SUFFIXES


def test_java_symbol_spans():
    src = b'class Foo { int bar(int x) { return x; } }'
    spans = ts_symbol_spans(src, spec_for('.java'))
    assert set(spans) == {'Foo', 'Foo.bar'}


def test_php_symbol_spans():
    src = b'<?php class Foo { public function bar() { return 1; } }'
    spans = ts_symbol_spans(src, spec_for('.php'))
    assert set(spans) == {'Foo', 'Foo.bar'}


def test_bash_function_span():
    src = b'hello() { echo hi; }'
    spans = ts_symbol_spans(src, spec_for('.sh'))
    assert set(spans) == {'hello'}


def test_nav_symbols_config_keys():
    json_keys = nav_symbols(b'{"name": "app", "v": 1}', spec_for('.json'))
    assert json_keys == [('name', 1), ('v', 1)]

    yaml_keys = nav_symbols(b'name: app\nversion: 1\n', spec_for('.yaml'))
    assert ('name', 1) in yaml_keys and ('version', 2) in yaml_keys

    toml_keys = nav_symbols(b'[pkg]\nname = "x"\n', spec_for('.toml'))
    assert ('name', 2) in toml_keys


def test_edit_symbol_refuses_json(tmp_path):
    import pytest
    from pydantic_ai import ModelRetry

    from codingdude.tools import build_toolset

    (tmp_path / 'cfg.json').write_text('{"a": 1}\n')
    es = build_toolset(tmp_path).tools['edit_symbol'].function
    with pytest.raises(ModelRetry, match='edit_file'):
        es('cfg.json', 'a', '2')
