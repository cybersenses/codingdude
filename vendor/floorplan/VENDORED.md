# Vendored: floorplan

Upstream: <https://github.com/haydenschmitty/floorplan>
Pinned commit: `94f81b463b7617e06d873ac71323ce71644c8399` (2026-11-20, v0.11.0)
Source path in upstream: `skills/floorplan/`
Copied here: 54 files, 2,961,212 bytes.

This directory is a verbatim copy of upstream's `skills/floorplan`, plus
`CHECKSUMS.sha256` and this file. Nothing is edited in place: R103 talks to
these scripts through `src/codingdude/floorplan.py`, which runs them as a
subprocess and reads their `--json` receipts.

## Why it is vendored

An architecture map is a core surface, not an optional add-on. Resolving from a
path and failing soft would mean a fresh install ships a core panel whose only
possible answer is "not available", so the payload ships with the repo and
`floorplan.floorplan_home()` finds it with no configuration.

## Licences

`floorplan` itself is MIT — full text in `LICENSE-floorplan-MIT.txt`.

Three vendored third-party assets carry their own terms, and their licence
files ship alongside them:

| Asset | Licence | File |
| --- | --- | --- |
| elkjs (layout engine), `assets/vendor/` | EPL-2.0 | `assets/vendor/elkjs-LICENSE.md` |
| Inter (font) | OFL-1.1 | `assets/vendor/fonts/inter-LICENSE.txt` |
| JetBrains Mono (font) | OFL-1.1 | `assets/vendor/fonts/jetbrains-mono-LICENSE.txt` |

EPL-2.0 is file-level copyleft: it governs the elk bundle and its
modifications, not the surrounding project. Do not delete these files — an
update that drops them breaks the licence obligation.

## Updating

1. Copy the new `skills/floorplan/` over this directory (do not merge slowly;
   the payload is generated upstream).
2. Regenerate `CHECKSUMS.sha256` — one `sha256  path` line per file, forward
   slashes, no CRLF.
3. Update the pin and byte counts in this file.
4. Re-run `uv run pytest -q tests/test_floorplan.py` — the real-node test
   drives `scan.mjs` and `build.mjs` and fails loudly on a payload change.

`vendor/floorplan/** -text` in `.gitattributes` is part of the pin, not
housekeeping: without it git rewrites these files' line endings on checkout
whenever `core.autocrlf` is on, so the checksums would describe the reader's
git config instead of the payload. That is exactly how the first CI run of
R103 failed — 49 of the 55 text files arrived as CRLF in the runner and every
hash mismatched, while the same commit passed on a checkout with autocrlf off.
Keep the rule when you re-vendor, and regenerate the checksums from the bytes
in this directory rather than from a fresh checkout.

## What it does with a repo

Nothing until asked: these scripts never run at import time, never call a
model, and never make a network request. `scan.mjs` writes a graph of files,
imports, HTTP routes and external packages; `build.mjs` writes a
self-contained `index.html` plus `graph.json`, with ELK and the fonts inlined,
and generates `query.mjs` and `serve.mjs` next to them.
