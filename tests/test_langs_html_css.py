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
"""R26 #46: HTML/CSS tier-2 — navigation-only support via the registry.

HTML/CSS get `spec_for` entries marked navigation_only: find_definition /
find_references resolve ids, classes, and selectors; edit_symbol refuses
(graceful degradation to edit_file).
"""

import pytest
from pydantic_ai import ModelRetry


def _tool(workdir, name, **kwargs):
    from codingdude.ast_tools import build_ast_toolset

    return build_ast_toolset(workdir).tools[name].function


def test_html_css_registered_navigation_only():
    from codingdude.langs import spec_for

    for suffix in ('.html', '.css'):
        spec = spec_for(suffix)
        assert spec is not None, suffix
        assert spec.navigation_only


def test_edit_symbol_refuses_html(tmp_path):
    from codingdude.tools import build_toolset

    f = tmp_path / 'index.html'
    f.write_text('<div id="app">hi</div>\n')
    es = build_toolset(tmp_path).tools['edit_symbol'].function
    with pytest.raises(ModelRetry, match='edit_file'):
        es('index.html', 'app', '<b>x</b>')


def test_find_definition_html_id(tmp_path):
    (tmp_path / 'index.html').write_text(
        '<div id="app" class="btn primary">hi</div>\n'
    )
    out = _tool(tmp_path, 'find_definition')('app', path='index.html')
    assert 'index.html:1' in out


def test_find_definition_css_selector(tmp_path):
    (tmp_path / 'style.css').write_text('.btn { color: red; }\n#app {}\n')
    out = _tool(tmp_path, 'find_definition')('btn', path='style.css')
    assert 'style.css:1' in out


def test_find_references_html_css(tmp_path):
    (tmp_path / 'index.html').write_text(
        '<div class="btn">hi</div>\n'
    )
    (tmp_path / 'style.css').write_text('.btn { color: red; }\n')
    out = _tool(tmp_path, 'find_references')('btn', path=str(tmp_path))
    assert 'index.html' in out
    assert 'style.css' in out
