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


_BODY_TYPES = frozenset(
    {
        'statement_block',
        'class_body',
        'function_body',
        'block',
        'compound_statement',
        'field_declaration_list',
        'declaration_list',
    }
)


def _body_container(node):
    """The node holding a class/impl's members, across grammar conventions."""
    for field in ('body', 'declaration_list'):
        child = node.child_by_field_name(field)
        if child is not None:
            return child
    for child in node.named_children:
        if child.type in _BODY_TYPES:
            return child
    return None


def _signature_text(node, source: bytes) -> str:
    """Header text before the body block, e.g. 'function f(a: number): number'."""
    for child in node.named_children:
        if child.type in _BODY_TYPES:
            header = source[node.start_byte : child.start_byte]
            return header.decode('utf-8', 'replace').strip()
    return source[node.start_byte : node.end_byte].decode(
        'utf-8', 'replace'
    ).strip()


def _is_symbol(node, spec: LanguageSpec) -> bool:
    return node.type in spec.function_nodes or node.type in spec.class_nodes


def _name_node(node, spec):
    """The node holding the symbol's name, per grammar conventions."""
    field = node.child_by_field_name(spec.name_field)
    if field is not None:
        return field
    # C/C++ function_definition: the name sits at the end of a declarator
    # chain (declarator -> function_declarator/pointer_declarator -> name).
    # Must run before the 'type' fallback — C/C++ use 'type' for the return
    # type, not the symbol name.
    declarator = node.child_by_field_name('declarator')
    while declarator is not None:
        if declarator.type in ('identifier', 'field_identifier'):
            return declarator
        declarator = declarator.child_by_field_name('declarator')
    # Rust impl_item: the type lives in the 'type' field.
    type_field = node.child_by_field_name('type')
    if type_field is not None:
        return type_field
    # Odin-style declarations (`name :: proc...`, `name :: struct...`): the
    # symbol name is the first `identifier` named child (after optional
    # attributes). Runs last so fielded grammars are unaffected.
    for child in node.named_children:
        if child.type == 'identifier':
            return child
    return None


def _node_name(node, spec: LanguageSpec) -> str | None:
    name = _name_node(node, spec)
    if name is None or name.text is None:
        return None
    return name.text.decode('utf-8', 'replace')


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
            body = _body_container(node)
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


def nav_symbols(
    source: bytes, spec: LanguageSpec
) -> list[tuple[str, int]]:
    """Navigable symbols for navigation-only languages: (name, 1-based line)."""
    from tree_sitter import Parser

    tree = Parser(spec.grammar).parse(source)
    found: list[tuple[str, int]] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in spec.symbol_nodes and _is_nav_symbol(node):
            raw = node.text
            text = (
                raw.decode('utf-8', 'replace').strip()
                if raw is not None
                else ''
            )
            if text:
                found.append((text, node.start_point[0] + 1))
        if spec.nav_keys and node.type.endswith('pair'):
            key_node = node.child_by_field_name('key')
            if key_node is None and node.named_children:
                # TOML grammar has no field names; the pair's first named
                # child is the key.
                key_node = node.named_children[0]
            if key_node is not None and key_node.text:
                # JSON keys are string literals: strip surrounding quotes.
                key = key_node.text.decode('utf-8', 'replace').strip().strip(
                    '"\''
                )
                if key:
                    found.append((key, key_node.start_point[0] + 1))
        stack.extend(reversed(node.children))
    return found


def _is_nav_symbol(node) -> bool:
    """HTML ids/classes only: attribute_value under an id/class attribute."""
    if node.type != 'attribute_value':
        return True
    parent = node.parent
    while parent is not None:
        if parent.type == 'attribute':
            name_node = parent.child_by_field_name('name') or (
                parent.named_children[0]
                if parent.named_children
                else None
            )
            if name_node is None:
                return False
            return name_node.text.decode('utf-8', 'replace').lower() in (
                'id',
                'class',
            )
        parent = parent.parent
    return False


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
