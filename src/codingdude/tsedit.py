"""Tree-sitter symbol editing support (R26 #44).

Registry-driven: works for any suffix with a `langs.LanguageSpec`. Provides
qualified-symbol byte spans (for edit_symbol) and before/after structural
diff summaries (for astdiff dispatch) from the same tree-sitter parse.
"""

from dataclasses import dataclass

from codingdude.langs import LanguageSpec

__all__ = ['SymbolInfo', 'describe_ts_change', 'ts_symbol_spans']

_WRAP_NODES = frozenset({'export_statement'})


@dataclass(frozen=True)
class SymbolInfo:
    """A located symbol: byte span plus rendered signature."""

    start_byte: int
    end_byte: int
    signature: str


def _unwrap(node):
    """Declarations nested in export/declare wrappers: keep the inner span."""
    while node.type in _WRAP_NODES:
        inner = [c for c in node.named_children if c.type != 'export']
        if len(inner) != 1:
            break
        node = inner[0]
    return node


def _signature_text(node, source: bytes) -> str:
    """Header text before the body block, e.g. 'function f(a: number): number'."""
    for child in node.named_children:
        if child.type in ('statement_block', 'class_body', 'function_body'):
            header = source[node.start_byte : child.start_byte]
            return header.decode('utf-8', 'replace').strip()
    return source[node.start_byte : node.end_byte].decode(
        'utf-8', 'replace'
    ).strip()


def _is_symbol(node, spec: LanguageSpec) -> bool:
    return node.type in spec.function_nodes or node.type in spec.class_nodes


def _node_name(node, spec: LanguageSpec) -> str | None:
    field = node.child_by_field_name(spec.name_field)
    return field.text.decode('utf-8', 'replace') if field else None


def _collect(source: bytes, spec: LanguageSpec) -> dict[str, SymbolInfo]:
    from tree_sitter import Parser

    tree = Parser(spec.grammar).parse(source)
    found: dict[str, SymbolInfo] = {}
    for child in tree.root_node.named_children:
        node = _unwrap(child)
        if not _is_symbol(node, spec):
            continue
        name = _node_name(node, spec)
        if name is None:
            continue
        found[name] = SymbolInfo(
            node.start_byte,
            node.end_byte,
            _signature_text(node, source),
        )
        if node.type in spec.class_nodes:
            body = node.child_by_field_name('body')
            if body is None:
                continue
            for member in body.named_children:
                if not _is_symbol(member, spec):
                    continue
                member_name = _node_name(member, spec)
                if member_name:
                    found[f'{name}.{member_name}'] = SymbolInfo(
                        member.start_byte,
                        member.end_byte,
                        _signature_text(member, source),
                    )
    return found


def ts_symbol_spans(
    source: bytes, spec: LanguageSpec
) -> dict[str, tuple[int, int]]:
    """Qualified symbol name -> (start_byte, end_byte), top level + methods."""
    return {
        name: (info.start_byte, info.end_byte)
        for name, info in _collect(source, spec).items()
    }


def describe_ts_change(
    before: bytes, after: bytes, spec: LanguageSpec
) -> str:
    """One line per structural change, or '' when nothing structural changed."""
    old = _collect(before, spec)
    new = _collect(after, spec)

    changes: list[str] = []
    for name in sorted(set(old) - set(new)):
        changes.append(f'removed {name}')
    for name in sorted(set(new) - set(old)):
        changes.append(f'added {name} ({new[name].signature})')
    for name in sorted(set(old) & set(new)):
        old_text = before[old[name].start_byte : old[name].end_byte]
        new_text = after[new[name].start_byte : new[name].end_byte]
        if old_text == new_text:
            continue
        if old[name].signature != new[name].signature:
            changes.append(
                f'changed {name}: {old[name].signature} -> {new[name].signature}'
            )
        else:
            changes.append(f'changed body of {name}')
    return '; '.join(changes)
