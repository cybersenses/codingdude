"""tree-sitter language selection for JS/TS files (self-review M14).

`.ts` and `.tsx` get the TypeScript grammar (so TS-only syntax — interfaces,
type annotations, generics — parses correctly); everything else gets the
JavaScript grammar. Missing TypeScript grammar degrades to JavaScript rather
than crashing. Delegates to the langs registry (R26).
"""

from tree_sitter import Language

from .langs import spec_for

__all__ = ['language_for']


def language_for(suffix: str) -> Language:
    """The tree-sitter Language for a file suffix ('.ts'/'.tsx' -> TypeScript).

    Falls back to the JavaScript grammar when TypeScript is unavailable or the
    suffix is unregistered."""
    spec = spec_for(suffix)
    if spec is not None:
        return spec.grammar
    js = spec_for('.js')
    if js is None:  # pragma: no cover - JS grammar is a hard dependency
        raise RuntimeError('JavaScript grammar unavailable')
    return js.grammar
