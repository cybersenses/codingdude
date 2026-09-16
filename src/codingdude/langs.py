"""Language registry (R26): file suffix -> tree-sitter grammar + symbol info.

Tier model:
- Tier 3 (full symbol tools): registered here with function/class node kinds.
- Suffixes without a registry entry degrade gracefully at callers (they must
  handle `spec_for` returning None).

Python is included so callers can branch on capability instead of hardcoding
suffix sets; Python-specific AST work keeps its stdlib-ast path at call sites.
"""

from dataclasses import dataclass, field
from functools import cache

from tree_sitter import Language

__all__ = ['NAV_SUFFIXES', 'LanguageSpec', 'language_for', 'spec_for']


@dataclass(frozen=True)
class LanguageSpec:
    """Registry entry: grammar plus the node kinds that define symbols."""

    grammar: Language
    function_nodes: frozenset[str] = field(default_factory=frozenset)
    class_nodes: frozenset[str] = field(default_factory=frozenset)
    name_field: str = 'name'
    # Navigation-only languages (HTML/CSS): no structural editing via
    # edit_symbol, but ids/classes/selectors are navigable symbols.
    navigation_only: bool = False
    symbol_nodes: frozenset[str] = field(default_factory=frozenset)


_JS_NODES = frozenset({'function_declaration', 'function_definition', 'method_definition'})
_JS_CLASSES = frozenset({'class_declaration', 'class_definition'})


def _js_spec(suffix: str) -> LanguageSpec:
    import tree_sitter_javascript as tsjs

    return LanguageSpec(
        grammar=Language(tsjs.language()),
        function_nodes=_JS_NODES,
        class_nodes=_JS_CLASSES,
    )


def _ts_spec(suffix: str) -> LanguageSpec:
    import tree_sitter_typescript as tsts

    return LanguageSpec(
        grammar=Language(
            tsts.language_tsx() if suffix == '.tsx' else tsts.language_typescript()
        ),
        function_nodes=_JS_NODES,
        class_nodes=_JS_CLASSES,
    )


def _python_spec() -> LanguageSpec:
    import tree_sitter_python as tsp

    return LanguageSpec(
        grammar=Language(tsp.language()),
        function_nodes=frozenset({'function_definition'}),
        class_nodes=frozenset({'class_definition'}),
    )


def _c_spec() -> LanguageSpec:
    import tree_sitter_c as tsc

    return LanguageSpec(
        grammar=Language(tsc.language()),
        function_nodes=frozenset({'function_definition'}),
        class_nodes=frozenset(
            {'struct_specifier', 'union_specifier', 'enum_specifier'}
        ),
    )


_CPP_CLASSES = frozenset({'class_specifier', 'struct_specifier'})


def _cpp_spec() -> LanguageSpec:
    import tree_sitter_cpp as tscpp

    return LanguageSpec(
        grammar=Language(tscpp.language()),
        function_nodes=frozenset({'function_definition'}),
        class_nodes=_CPP_CLASSES,
    )


def _csharp_spec() -> LanguageSpec:
    import tree_sitter_c_sharp as tscs

    return LanguageSpec(
        grammar=Language(tscs.language()),
        function_nodes=frozenset(
            {'method_declaration', 'constructor_declaration'}
        ),
        class_nodes=frozenset(
            {
                'class_declaration',
                'interface_declaration',
                'struct_declaration',
                'record_declaration',
            }
        ),
    )


def _rust_spec() -> LanguageSpec:
    import tree_sitter_rust as tsr

    return LanguageSpec(
        grammar=Language(tsr.language()),
        function_nodes=frozenset({'function_item'}),
        # impl_item acts as a class container so methods resolve as Type.method.
        class_nodes=frozenset(
            {'struct_item', 'enum_item', 'impl_item', 'trait_item'}
        ),
    )


def _go_spec() -> LanguageSpec:
    import tree_sitter_go as tsg

    return LanguageSpec(
        grammar=Language(tsg.language()),
        function_nodes=frozenset({'function_declaration', 'method_declaration'}),
        class_nodes=frozenset(),
    )


def _kotlin_spec() -> LanguageSpec:
    import tree_sitter_kotlin as tsk

    return LanguageSpec(
        grammar=Language(tsk.language()),
        function_nodes=frozenset({'function_declaration'}),
        class_nodes=frozenset(
            {'class_declaration', 'object_declaration'}
        ),
    )


def _html_spec() -> LanguageSpec:
    import tree_sitter_html as tsh

    return LanguageSpec(
        grammar=Language(tsh.language()),
        navigation_only=True,
        # id/class attribute values are the navigable symbols.
        symbol_nodes=frozenset({'attribute_value'}),
    )


def _css_spec() -> LanguageSpec:
    import tree_sitter_css as tsc

    return LanguageSpec(
        grammar=Language(tsc.language()),
        navigation_only=True,
        symbol_nodes=frozenset({'class_name', 'id_name'}),
    )


@cache
def spec_for(suffix: str) -> LanguageSpec | None:
    """The LanguageSpec for a file suffix, or None if unregistered."""
    suffix = (suffix or '').lower()
    try:
        if suffix in ('.ts', '.tsx'):
            return _ts_spec(suffix)
        if suffix in ('.js', '.jsx', '.mjs'):
            return _js_spec(suffix)
        if suffix == '.py':
            return _python_spec()
        if suffix in ('.c', '.h'):
            return _c_spec()
        if suffix in ('.cpp', '.cc', '.cxx', '.hpp', '.hh'):
            return _cpp_spec()
        if suffix == '.cs':
            return _csharp_spec()
        if suffix == '.rs':
            return _rust_spec()
        if suffix == '.go':
            return _go_spec()
        if suffix in ('.kt', '.kts'):
            return _kotlin_spec()
        if suffix in ('.html', '.htm'):
            return _html_spec()
        if suffix == '.css':
            return _css_spec()
    except ImportError:
        return None
    return None


# Suffixes with navigation-only registry support (HTML/CSS tier 2).
NAV_SUFFIXES = frozenset({'.html', '.htm', '.css'})


def language_for(suffix: str) -> Language:
    """Backward-compatible grammar lookup (jslang migration path)."""
    spec = spec_for(suffix)
    if spec is None:
        raise ValueError(f'No grammar registered for suffix {suffix!r}')
    return spec.grammar
