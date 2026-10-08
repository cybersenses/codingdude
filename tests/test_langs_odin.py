"""Odin language support (R48): pinned full-support spec, symbol tools,
generic CFG, and dead-code detection over `Name :: ...` declarations."""

from textwrap import dedent

from codingdude.cfg import ts_build_cfg
from codingdude.deadcode import _ts_dead_code
from codingdude.langs import PINNED_FULL_SUFFIXES, spec_for
from codingdude.tsedit import describe_ts_change, ts_symbol_spans

ODIN_SOURCE = dedent("""\
    package main

    Entity :: struct {
        pos: [2]f32,
    }

    Color :: enum { RED, GREEN }

    Shape :: union { a: Circle, b: Square }

    add :: proc(a, b: int) -> int {
        return a + b
    }

    @(private) helper :: proc "c" (x: f32) {
        return
    }
    """)


def test_odin_spec_is_full_support():
    spec = spec_for('.odin')
    assert spec is not None
    assert not spec.navigation_only
    assert '.odin' in PINNED_FULL_SUFFIXES


def test_odin_symbol_collection():
    spans = ts_symbol_spans(ODIN_SOURCE.encode(), spec_for('.odin'))
    assert set(spans) == {'Entity', 'Color', 'Shape', 'add', 'helper'}
    # Procedure spans exclude nothing structural; start at the declaration.
    assert ODIN_SOURCE.encode()[spans['add'][0]:].startswith(b'add')


ODIN_CFG = dedent("""\
    classify :: proc(x: int) -> int {
        if x > 0 {
            return 1
        } else {
            return -1
        }
    }

    spin :: proc(n: int) {
        for i := 0; i < n; i += 1 {
            continue
        }
    }
    """)


def test_odin_cfg_if_else():
    cfg = ts_build_cfg(ODIN_CFG.encode(), spec_for('.odin'), 'classify')
    assert cfg['function'] == 'classify'
    kinds = [e['kind'] for e in cfg['edges']]
    assert 'true' in kinds and 'false' in kinds


def test_odin_cfg_loop_back_edge():
    cfg = ts_build_cfg(ODIN_CFG.encode(), spec_for('.odin'), 'spin')
    assert any(e['kind'] == 'back' for e in cfg['edges'])


def test_odin_cfg_unreachable_after_terminating_if():
    cfg = ts_build_cfg(
        dedent("""\
            f :: proc(x: int) -> int {
                if x > 0 { return 1 } else { return 2 }
                return 3
            }
            """).encode(),
        spec_for('.odin'),
        'f',
    )
    dead = [b for b in cfg['blocks'] if not b['reachable']]
    assert any('return 3' in line for b in dead for line in b['lines'])


def test_odin_structural_diff():
    before = ODIN_SOURCE.encode()
    after = before.replace(
        b'\n@(private) helper :: proc "c" (x: f32) {\n    return\n}\n',
        b'',
    )
    summary = describe_ts_change(before, after, spec_for('.odin'))
    assert 'removed helper' in summary
    assert 'changed add' not in summary


def test_odin_dead_code(tmp_path):
    (tmp_path / 'm.odin').write_text(
        'used :: proc() -> int { return 1 }\n'
        'unused :: proc() -> int { return 2 }\n'
    )
    out = _ts_dead_code(tmp_path, '.', 60)
    assert 'm.odin:2: unused' in out


def test_odin_cfg_loop_inside_if_is_reachable():
    """Regression: a loop directly inside an if-branch used to be flagged
    unreachable — the branch emitted its true edge to the body's exit block
    instead of its entry. Observed on real stdlib code (core/bytes
    index_byte, 15 false-dead blocks)."""
    cfg = ts_build_cfg(
        dedent("""            f :: proc(s: []byte) -> int {
                if len(s) > 0 {
                    for i in 0 ..< len(s) {
                        if s[i] == 0 { return i }
                    }
                }
                return -1
            }
            """).encode(),
        spec_for('.odin'),
        'f',
    )
    dead = [b for b in cfg['blocks'] if not b.get('reachable')]
    assert dead == []


def test_odin_cfg_cstyle_loop_inside_if_is_reachable():
    cfg = ts_build_cfg(
        dedent("""            f :: proc(s: []byte, c: byte) -> int {
                i, l := 0, len(s)
                if l < 16 {
                    for /**/; i < l; i += 1 {
                        if s[i] == c { return i }
                    }
                    return -1
                }
                return -2
            }
            """).encode(),
        spec_for('.odin'),
        'f',
    )
    dead = [b for b in cfg['blocks'] if not b.get('reachable')]
    assert dead == []
