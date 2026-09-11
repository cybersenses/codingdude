"""tree-sitter language selection for JS/TS files (self-review M14).

`.ts` and `.tsx` get the TypeScript grammar (so TS-only syntax — interfaces,
type annotations, generics — parses correctly); everything else gets the
JavaScript grammar. Missing TypeScript grammar degrades to JavaScript rather
than crashing.
"""

from functools import cache

import tree_sitter_javascript as tsjs
from tree_sitter import Language

__all__ = ['language_for']


@cache
def language_for(suffix: str) -> Language:
    """The tree-sitter Language for a file suffix ('.ts'/'.tsx' -> TypeScript)."""
    suffix = (suffix or '').lower()
    if suffix in ('.ts', '.tsx'):
        try:
            import tree_sitter_typescript as tsts

            return Language(
                tsts.language_tsx() if suffix == '.tsx' else tsts.language_typescript()
            )
        except Exception:  # noqa: BLE001 - fall back to the JS grammar
            pass
    return Language(tsjs.language())
