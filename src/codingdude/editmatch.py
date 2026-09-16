"""R27 #54: aider-style layered search/replace matching for edit_file.

Strategies, in order (ported from aider's editblock_coder, adapted):
  1. exact line-tuple match (must be unique)
  2. whitespace-flexible match (uniform leading-indent difference is fixed)
  3. spurious leading blank line in SEARCH tolerated
  4. `...` elision (model elides unchanged code)
Aider's fuzzy edit-distance fallback is deliberately NOT ported (aider itself
disabled it). No match, or an ambiguous one, returns None — the caller decides
how to report it.
"""

from __future__ import annotations

from difflib import SequenceMatcher

__all__ = ['replace_most_similar_chunk', 'find_similar_lines']

_SIMILAR_THRESHOLD = 0.6


def _split_lf(text: str) -> list[str]:
    return text.replace('\r\n', '\n').splitlines(keepends=True)


def _has_crlf(text: str) -> bool:
    return '\r\n' in text


def _restore_eol(text: str) -> str:
    return text.replace('\n', '\r\n')


def _count_tuple_matches(whole_lines: list[str], part_lines: list[str]) -> int:
    part_tup = tuple(part_lines)
    part_len = len(part_lines)
    return sum(
        1
        for i in range(len(whole_lines) - part_len + 1)
        if tuple(whole_lines[i : i + part_len]) == part_tup
    )


def _match_but_for_leading_whitespace(
    whole_lines: list[str], part_lines: list[str]
) -> str | None:
    """Return the common indent to add, or None if these lines don't match
    apart from a uniform leading-whitespace difference."""
    if not all(
        whole_lines[i].lstrip() == part_lines[i].lstrip()
        for i in range(len(part_lines))
    ):
        return None
    offsets = {
        whole_lines[i][: len(whole_lines[i]) - len(part_lines[i])]
        for i in range(len(part_lines))
        if part_lines[i].strip()
    }
    if len(offsets) != 1:
        return None
    return offsets.pop()


def _whitespace_flexible(
    whole_lines: list[str], part_lines: list[str], replace_lines: list[str]
) -> str | None:
    """Match ignoring leading whitespace; re-indent the replacement to fit."""
    # Outdent part and replace by the largest shared indent.
    leading = [len(p) - len(p.lstrip()) for p in part_lines if p.strip()] + [
        len(r) - len(r.lstrip()) for r in replace_lines if r.strip()
    ]
    if leading:
        num_leading = min(leading)
        if num_leading:
            part_lines = [p[num_leading:] if p.strip() else p for p in part_lines]
            replace_lines = [r[num_leading:] if r.strip() else r for r in replace_lines]

    n = len(part_lines)
    hits: list[tuple[int, str]] = []
    for i in range(len(whole_lines) - n + 1):
        add = _match_but_for_leading_whitespace(whole_lines[i : i + n], part_lines)
        if add is not None:
            hits.append((i, add))
    if len(hits) > 1:
        return None  # ambiguous — caller must not guess
    if not hits:
        return None
    i, add = hits[0]
    new_replace = [add + r if r.strip() else r for r in replace_lines]
    return ''.join(whole_lines[:i] + new_replace + whole_lines[i + n :])


def _try_dotdotdots(
    whole: str, part: str, replace: str
) -> str | None:
    """Handle SEARCH/REPLACE blocks that elide code with `...` lines."""
    part_pieces = _split_on_dots(whole, part)
    replace_pieces = _split_on_dots(whole, replace)
    if len(part_pieces) != len(replace_pieces):
        return None
    if len(part_pieces) == 1:
        return None  # no dots — not this strategy
    # Literal separator pieces must agree between SEARCH and REPLACE.
    if any(
        part_pieces[i] != replace_pieces[i] for i in range(0, len(part_pieces), 2)
    ):
        return None
    result = whole
    for p, r in zip(part_pieces[1::2], replace_pieces[1::2], strict=False):
        if not p and not r:
            continue
        count = result.count(p)
        if count != 1:
            return None
        result = result.replace(p, r, 1)
    return result


def _split_on_dots(whole: str, text: str) -> list[str]:
    """Split `text` on `...` lines, keeping separators at even indices and
    content chunks at odd ones (leading empty string first)."""
    import re

    pieces: list[str] = ['']
    buf: list[str] = []
    for line in text.replace('\r\n', '\n').splitlines(keepends=True):
        if re.match(r'^\s*\.\.\.\n$', line):
            pieces.append(''.join(buf))
            buf = []
            pieces.append(line)
        else:
            buf.append(line)
    pieces.append(''.join(buf))
    return pieces


def replace_most_similar_chunk(whole: str, part: str, replace: str) -> str | None:
    """Best-effort locate `part` in `whole` and swap in `replace`.

    Returns the full updated file text (original EOLs preserved), or None if
    the part cannot be matched unambiguously by any strategy.
    """
    if not part.strip():
        return None
    crlf = _has_crlf(whole)
    whole_lf = whole.replace('\r\n', '\n')
    if not whole_lf.endswith('\n'):
        whole_lf += '\n'
    part_lf = part.replace('\r\n', '\n')
    replace_lf = replace.replace('\r\n', '\n')
    if not part_lf.endswith('\n'):
        part_lf += '\n'
    if not replace_lf.endswith('\n'):
        replace_lf += '\n'

    whole_lines = whole_lf.splitlines(keepends=True)
    part_lines = part_lf.splitlines(keepends=True)
    replace_lines = replace_lf.splitlines(keepends=True)

    def done(result: str | None) -> str | None:
        return _restore_eol(result) if crlf and result is not None else result

    # 1. Exact match (unique only).
    if _count_tuple_matches(whole_lines, part_lines) == 1:
        out = whole_lf.replace(part_lf, replace_lf, 1)
        return done(out)
    if _count_tuple_matches(whole_lines, part_lines) > 1:
        return None  # ambiguous

    # 2. Whitespace-flexible.
    res = _whitespace_flexible(whole_lines, part_lines, replace_lines)
    if res is not None:
        return done(res)

    # 3. Spurious leading blank line in SEARCH.
    if len(part_lines) > 2 and not part_lines[0].strip():
        trimmed = part_lines[1:]
        if _count_tuple_matches(whole_lines, trimmed) == 1:
            return done(
                whole_lf.replace(''.join(trimmed), replace_lf, 1)
            )

    # 4. `...` elision.
    try:
        res = _try_dotdotdots(whole_lf, part_lf, replace_lf)
    except ValueError:
        res = None
    if res is not None:
        return done(res)

    return None


def find_similar_lines(search: str, content: str, threshold: float = 0.6) -> str:
    """The lines in `content` most similar to `search`, for did-you-mean
    feedback (aider's find_similar_lines)."""
    search_lines = search.replace('\r\n', '\n').splitlines()
    content_lines = content.replace('\r\n', '\n').splitlines()
    if not search_lines or not content_lines:
        return ''
    best_ratio = 0.0
    best_match: list[str] = []
    best_match_i = 0
    for i in range(len(content_lines) - len(search_lines) + 1):
        chunk = content_lines[i : i + len(search_lines)]
        ratio = SequenceMatcher(
            None, '\n'.join(search_lines), '\n'.join(chunk)
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = chunk
            best_match_i = i
    if best_ratio < threshold:
        return ''
    if best_match and best_match[0] == search_lines[0] and best_match[-1] == search_lines[-1]:
        return '\n'.join(best_match)
    n = 5
    end = min(len(content_lines), best_match_i + len(search_lines) + n)
    start = max(0, best_match_i - n)
    return '\n'.join(content_lines[start:end])
