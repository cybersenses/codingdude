"""Single seam for parsing untrusted/user Python source.

User workdirs contain third-party files with pre-3.12 idioms (e.g. non-raw
"\\s" regex strings) that emit SyntaxWarning on every parse. Those warnings
are noise from our tooling, not actionable here — suppress them. Parse
failures still raise SyntaxError to callers.
"""

import ast
import warnings


def parse_python(source: str) -> ast.Module:
    """Parse Python source with SyntaxWarning suppressed."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', SyntaxWarning)
        return ast.parse(source)
