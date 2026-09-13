# R8 Tracer — Architecture guardrails (`archlint`)

Thin vertical slice: a deterministic architecture linter the agent runs before
finishing, with fix-or-explicitly-waive semantics (soft-block per ratified
plan; a waiver is recorded as a design decision).

## Design

New `src/codingdude/archlint.py`:

### Rules (AST-based, stdlib only, workdir `src/` tree)
1. `private-access` — seam leak: a module in the package imports a sibling
   module and references a `_private` attribute of it
   (`module._helper(...)` / `module._CONST`). Deep-module vocabulary: the
   private surface is not a seam.
2. `duplicate-body` — two function defs (any files, `ast`-normalized: args
   order-insensitive, docstrings/comments stripped) with identical normalized
   bodies. One finding per duplicated group, naming file:line of each copy.

### Findings
`{'rule', 'fingerprint' (stable short hash), 'message', 'locations'}`.

### Waivers
`ArchLint.check(workdir)` returns active findings. A finding with a recorded
waiver is suppressed and reported as `waived`. `waive(fingerprint, reason)`
records a design decision titled `ARCH-WAIVER <fingerprint>` via the existing
workdir-scoped `RoadmapStore.create_decision` — one source of truth for
decisions, per plan decision #5.

### Agent tools (`build_archlint_toolset(workdir, store)`)
- `arch_lint()` → human-readable findings report (or "clean"; waived findings
  listed separately). The tool description says: fix the finding or waive it
  explicitly — never ignore it.
- `waive_finding(fingerprint, reason)` → records the waiver decision.

Non-goals (later thickening): import-layer rules, config drift, contract-first
codegen, ADR-contradiction detection against code changes.

## Tests (`tests/test_archlint.py`)
Seams: `ArchLint` over real temp files; toolset function calls. No mocks.
1. private-access: sibling module touching `_secret` is flagged; own-module use is not
2. duplicate-body: identical functions in two files flagged with both locations; near-identical (different body) not flagged
3. fingerprint stable across runs
4. waive suppresses the finding and reports it as waived; recorded as a design decision
5. clean tree → "clean" report
6. toolset: arch_lint + waive_finding round-trip
