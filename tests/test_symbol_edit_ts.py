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
"""R26 #44: multi-language edit_symbol — TypeScript tracer (tree-sitter path).

Seam: same `edit_symbol(path, symbol, new_body)` tool; .ts/.tsx files go
through a registry-driven tree-sitter span search instead of stdlib ast.
"""

import pytest
from pydantic_ai import ModelRetry


def _tool(workdir, name, **kwargs):
    from codingdude.tools import build_toolset

    return build_toolset(workdir, **kwargs).tools[name].function


MODULE = '''import os from "os";

export function alpha(a: number): number {
  return a + 1;
}

class Widget {
  prefix = "hi";

  greet(name: string): string {
    return this.prefix + " " + name;
  }
}

function tail(): void {
  return;
}
'''


def test_edit_symbol_replaces_ts_function(tmp_path):
    f = tmp_path / 'mod.ts'
    f.write_text(MODULE)
    new = 'function alpha(a: number): number {\n  return a + 2;\n}'
    out = _tool(tmp_path, 'edit_symbol')('mod.ts', 'alpha', new)
    assert 'edited' in out
    text = f.read_text()
    assert 'a + 2' in text and 'a + 1' not in text
    assert 'export function alpha' in text  # export keyword preserved


def test_edit_symbol_replaces_ts_method(tmp_path):
    f = tmp_path / 'mod.ts'
    f.write_text(MODULE)
    new = "greet(name: string): string {\n    return `hey ${name}`;\n  }"
    _tool(tmp_path, 'edit_symbol')('mod.ts', 'Widget.greet', new)
    text = f.read_text()
    assert 'hey ${name}' in text
    assert 'class Widget' in text  # method stayed inside the class
    assert 'greet' in text


def test_edit_symbol_ts_summary_reported(tmp_path):
    f = tmp_path / 'mod.ts'
    f.write_text(MODULE)
    out = _tool(tmp_path, 'edit_symbol')(
        'mod.ts', 'tail', 'function tail(): void {\n  return 1;\n}'
    )
    assert 'changed body of tail' in out


def test_edit_symbol_ts_bare_name_ambiguous(tmp_path):
    text = MODULE + '''class Other {
  greet(name: string): string {
    return name;
  }
}
'''
    f = tmp_path / 'mod.ts'
    f.write_text(text)
    with pytest.raises(ModelRetry, match='ambiguous'):
        _tool(tmp_path, 'edit_symbol')('mod.ts', 'greet', 'greet() {}')


def test_edit_symbol_ts_exact_qualified_match_wins(tmp_path):
    text = MODULE + '''class Other {
  greet(name: string): string {
    return name;
  }
}
'''
    f = tmp_path / 'mod2.ts'
    f.write_text(text)
    with pytest.raises(ModelRetry, match='ambiguous'):
        _tool(tmp_path, 'edit_symbol')('mod2.ts', 'greet', 'greet() {}')
    new = "greet(name: string): string {\n    return 'ok';\n  }"
    _tool(tmp_path, 'edit_symbol')('mod2.ts', 'Widget.greet', new)
    assert "'ok'" in f.read_text()


def test_edit_symbol_ts_not_found_lists_symbols(tmp_path):
    f = tmp_path / 'mod.ts'
    f.write_text(MODULE)
    with pytest.raises(ModelRetry, match='alpha'):
        _tool(tmp_path, 'edit_symbol')('mod.ts', 'nope', 'function nope() {}')


def test_edit_symbol_unsupported_suffix_degrades(tmp_path):
    f = tmp_path / 'mod.rb'
    f.write_text('def a; end\n')
    with pytest.raises(ModelRetry, match='edit_file'):
        _tool(tmp_path, 'edit_symbol')('mod.rb', 'a', 'def a; end')


def test_tsx_files_use_tsx_grammar(tmp_path):
    f = tmp_path / 'comp.tsx'
    f.write_text(
        'export function Btn(): JSX.Element {\n  return <b>hi</b>;\n}\n'
    )
    _tool(tmp_path, 'edit_symbol')(
        'comp.tsx', 'Btn', 'function Btn(): JSX.Element {\n  return <i>bye</i>;\n}'
    )
    assert '<i>bye</i>' in f.read_text()
