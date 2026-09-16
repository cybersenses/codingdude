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

__all__ = ['LanguageSpec', 'language_for', 'spec_for']


@dataclass(frozen=True)
class LanguageSpec:
    """Registry entry: grammar plus the node kinds that define symbols."""

    grammar: Language
    function_nodes: frozenset[str] = field(default_factory=frozenset)
    class_nodes: frozenset[str] = field(default_factory=frozenset)
    name_field: str = 'name'


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
    except ImportError:
        return None
    return None


def language_for(suffix: str) -> Language:
    """Backward-compatible grammar lookup (jslang migration path)."""
    spec = spec_for(suffix)
    if spec is None:
        raise ValueError(f'No grammar registered for suffix {suffix!r}')
    return spec.grammar
