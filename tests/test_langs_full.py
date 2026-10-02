"""Full-language rollout: list_languages, generic tree-sitter CFG, and
language-wide find_dead_code."""

from textwrap import dedent

import pytest

from codingdude.cfg import ts_build_cfg
from codingdude.deadcode import _ts_dead_code
from codingdude.langs import pack_language_name, spec_for, supported_languages

# --- Phase 1: language exposure ----------------------------------------------

def test_supported_languages_shape():
    info = supported_languages()
    assert '.py' in info['full']
    assert '.html' in info['navigation_only']
    assert isinstance(info['pack_manifest_total'], int)
    assert info['pack_manifest_total'] > len(info['pack_languages']) or info['pack_languages']


def test_pack_language_name():
    assert pack_language_name('.rb') == 'ruby'
    assert pack_language_name('.RB') == 'ruby'
    assert pack_language_name('.definitely_not_a_lang') is None


def test_list_languages_tool(tmp_path):
    from codingdude.ast_tools import build_ast_toolset

    toolset = build_ast_toolset(tmp_path)
    names = set(toolset.tools)
    assert 'list_languages' in names


# --- Phase 2: generic tree-sitter CFG ----------------------------------------

def _cfg_of(lang_suffix: str, source: str, function=None):
    return ts_build_cfg(source.encode(), spec_for(lang_suffix), function)


C_IF_ELSE = dedent("""\
    int f(int x) {
        if (x > 0) {
            return 1;
        } else {
            return 2;
        }
    }

    int deadend(int x) {
        return 1;
        return 2;
    }
    """)


def test_c_if_else_join():
    cfg = _cfg_of('.c', C_IF_ELSE, 'f')
    kinds = {(e['src'], e['kind']) for e in cfg['edges']}
    assert any(k == 'true' for _, k in kinds)
    assert any(k == 'false' for _, k in kinds)
    # all blocks reachable in the balanced branch
    assert all(b['reachable'] for b in cfg['blocks'])


def test_c_unreachable_after_return():
    cfg = _cfg_of('.c', C_IF_ELSE, 'deadend')
    dead = [b for b in cfg['blocks'] if not b['reachable']]
    assert len(dead) == 1
    assert 'return 2;' in dead[0]['lines'][0]


GO_LOOP = dedent("""\
    package main

    func dead(x int) int {
        for i := 0; i < 3; i++ {
            if i > 1 {
                break
            }
            continue
        }
        return x
    }
    """)


def test_go_loop_break_continue():
    cfg = _cfg_of('.go', GO_LOOP, 'dead')
    kinds = [e['kind'] for e in cfg['edges']]
    assert 'back' in kinds       # loop head back-edge and/or continue
    assert 'true' in kinds and 'false' in kinds
    assert cfg['function'] == 'dead'


RUBY_METHOD = dedent("""\
    def f(x)
      if x
        return 1
      else
        next
      end
    end
    """)


def test_ruby_pack_language_cfg():
    cfg = _cfg_of('.rb', RUBY_METHOD, 'f')
    assert cfg['function'] == 'f'
    kinds = [e['kind'] for e in cfg['edges']]
    assert 'true' in kinds and 'false' in kinds


RUST_IF = dedent("""\
    fn f(x: i32) -> i32 {
        if x > 0 {
            return 1;
        }
        2
    }
    """)


def test_rust_if_cfg():
    cfg = _cfg_of('.rs', RUST_IF, 'f')
    assert cfg['function'] == 'f'
    assert any(e['kind'] == 'true' for e in cfg['edges'])


def test_function_not_found():
    with pytest.raises(ValueError):
        _cfg_of('.c', C_IF_ELSE, 'no_such_fn')


def test_analyze_control_flow_generic(tmp_path):
    """The tool routes non-Python files through the generic builder."""
    import asyncio

    from codingdude.cfg import build_cfg_toolset

    (tmp_path / 'm.c').write_text(C_IF_ELSE)
    toolset = build_cfg_toolset(tmp_path)
    tool = toolset.tools['analyze_control_flow']
    out = asyncio.run(tool.function(path='m.c', function='deadend'))
    assert 'unreachable' in out
    assert 'best-effort' in out


def test_analyze_control_flow_unsupported_suffix(tmp_path):
    import asyncio

    from codingdude.cfg import build_cfg_toolset

    (tmp_path / 'x.txt').write_text('hello')
    toolset = build_cfg_toolset(tmp_path)
    tool = toolset.tools['analyze_control_flow']
    from pydantic_ai import ModelRetry

    with pytest.raises(ModelRetry):
        asyncio.run(tool.function(path='x.txt'))


def test_analyze_control_flow_python_unchanged(tmp_path):
    import asyncio

    from codingdude.cfg import build_cfg_toolset

    (tmp_path / 'm.py').write_text(
        'def f():\n    return 1\n    return 2\n'
    )
    toolset = build_cfg_toolset(tmp_path)
    tool = toolset.tools['analyze_control_flow']
    out = asyncio.run(tool.function(path='m.py'))
    assert 'unreachable' in out
    assert 'best-effort' not in out


# --- Phase 3: find_dead_code across languages --------------------------------

def test_ts_dead_code_finds_unused_c_function(tmp_path):
    (tmp_path / 'm.c').write_text(
        'int used(void) { return 1; }\n'
        'int unused(void) { return 2; }\n'
    )
    out = _ts_dead_code(tmp_path, '.', 60)
    # Identifier-level scan: neither symbol is ever referenced.
    assert 'm.c:2: unused' in out
    assert 'm.c:1: used' in out





def test_ts_dead_code_ignores_python_and_nav(tmp_path):
    (tmp_path / 'm.py').write_text('def orphan():\n    pass\n')
    (tmp_path / 's.json').write_text('{"key": 1}')
    out = _ts_dead_code(tmp_path, '.', 60)
    assert out == ''
