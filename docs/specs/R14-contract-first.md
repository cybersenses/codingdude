# R14 — Contract-first discipline + mid-run index refresh

Status: implemented (this commit). Roadmap decision #10. Thin slice: no DSL,
no generated stubs, no automatic conformance checking (deferred per roadmap).

## What shipped
1. **Contract convention**: a spec in `docs/specs/*.md` may carry a
   `## Contract` section; each single-word backticked name is a symbol the
   implementation must define and test.
2. **Archlint rules** (soft findings, fix-or-explicit-waive like all others):
   - `spec-contract-missing` — a Contract name with no top-level
     function/class of that name under the workdir.
   - `spec-contract-untested` — the symbol exists but never appears in any
     file under `tests/`.
3. **Mid-run refresh**: after each fix-loop retry iteration, the codegraph
   index is refreshed best-effort (`refresh_codegraph_index`, 120s bound,
   never raises) and `INDEX_REFRESHED` is traced, so long sessions don't
   navigate stale code. arch_lint already runs live per tool call — no
   caching to invalidate.

## Contract
- `codingdude.archlint.ArchLint._spec_contracts`
- `codingdude.codegraph_boot.refresh_codegraph_index`
