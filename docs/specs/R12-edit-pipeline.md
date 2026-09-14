# R12 — Deterministic file-edit pipeline

## Problem
`edit_file` corrupted files in 3+ recorded incidents (duplicated lines, silent
revert, rewritten Notes component). Root cause diagnosed in
`src/codingdude/tools.py:edit_file`:

1. **Lossy read**: `read_text(errors='replace')` turns non-UTF-8 bytes into
   U+FFFD; the subsequent write persists the damage.
2. **Newline translation**: universal-newline text round-trip converts LF
   files to CRLF under Windows Python — mixed endings = "subtly corrupted".
3. **No atomicity / staleness**: concurrent writers are last-writer-wins,
   observed as "silent revert".

## Design (decision #8)
Repair `edit_file` in place; no second mechanism.

- **Strict read**: decode with `errors='strict'`; on `UnicodeDecodeError`
  raise `ModelRetry` ("file is not valid UTF-8; refusing to edit").
- **Byte-faithful round-trip**: read/write with `newline=''` so existing
  line endings survive untouched. `old_text` matching tries the text as
  given, then normalised (`\r\n`→`\n`) matching with endings restored on
  replace — the model can't be expected to reproduce CRLF.
- **Atomic write**: write to a temp file in the same directory, `os.replace`
  onto the target.
- **Verify + rollback**: re-read after write; if content ≠ expected `after`,
  restore the original bytes and raise.
- **Staleness guard**: `build_toolset` keeps an mtime+size record per path
  updated by `read_file`/`edit_file`/`write_file`; an edit to a file changed
  since last observation raises `ModelRetry` ("file changed since last read —
  re-read it").
- `write_file` shares the same atomic-write + verify primitive (create-only,
  no replace semantics).

## Tests (FunctionToolset seam, `tests/test_tools.py`)
1. **Non-UTF-8 file** → edit raises `ModelRetry`, file bytes unchanged.
2. **LF file edit** → file still pure LF after edit (no CRLF introduced);
   CRLF file edit → stays CRLF; `\n`-style old_text matches CRLF file.
3. **Staleness**: edit → external touch with new content → second edit
   raises retryable error naming the path.
4. **Atomicity/verify**: normal edit leaves exactly one replacement (already
   covered by uniqueness); verification rollback exercised by simulating a
   post-write mismatch (monkeypatched writer).
5. `write_file` → creates parents, atomic, LF preserved.

## Acceptance
- All five scenarios green; full gates clean (pytest, ruff, mypy).
- HANDOFF watch item "edit_file mangles lines" closed with evidence.
