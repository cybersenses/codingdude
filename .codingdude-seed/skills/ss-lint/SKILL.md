{"name": "ss-lint", "description": "Quick automated lint \u2014 detects common design system violations in seconds", "triggers": ["ss-lint", "design lint"]}

# Design Lint (Quick Check)
## Registry-first artifact boundary

**Artifact boundary (CodingDude):** a project's compiled method lives in `.styleseed/`. If `.styleseed/project.json` exists, the artifact is `default` (or the registry's single artifact): read `.styleseed/bundles/default.md` and keep `.styleseed/manifests/default.json` as provenance. Otherwise read the legacy pair `.styleseed/effective-rules.md` + `.styleseed/manifest.json`. Never mix the two.

## Canonical executable check

For a reproducible, artifact-bound scan with machine-readable output, use:

```bash
node $HOME/.codingdude/skills`ss-score`/scripts/styleseed-check.mjs scan \
  --project-root . --artifact <artifact-id> --format json
node $HOME/.codingdude/skills`ss-score`/scripts/styleseed-check.mjs scan \
  --project-root . --all --format sarif
```

The checker treats only contract, containment, manifest/hash, malformed-report, and required
coverage failures as hard errors. Detector findings (`SS001`–`SS006`) remain warnings and include a
stable file, line, evidence snippet, severity, and fix. Use `styleseed-check ... verify` to recompute
the bound evidence run; do not turn a string or stale report into a pass.

Read `.styleseed/effective-rules.md` and `.styleseed/manifest.json`; invoke ``ss-resolve`` or
``ss-resolve`` first when they are missing or stale. Lint detects deterministic drift; it must
not flag an exact grammar/recipe/profile/adapter contract as a violation or let an arbitrary lock
value create an exception.

## When NOT to use

- For deeper review of design judgment (composition, hierarchy, rhythm) → use ``ss-review``
- For accessibility specifically → use ``ss-a11y``
- For Nielsen UX heuristics → use ``ss-audit``
- For applying refactors — this only flags violations; use ``ss-review`` to fix

Target: **$ARGUMENTS**

## What This Does

Fast, grep-based scan for common design violations. Runs in seconds (unlike `ss-review` which is a deep manual audit). Run this after every file change.

## Checks

### 1. Hardcoded Colors
Search for hex colors in className strings that should be semantic tokens:
```bash
grep -n '#[0-9a-fA-F]\{3,8\}' [file] | grep -v 'theme.css\|tokens\|\.json'
```
**Violation:** `text-[#3C3C3C]`, `bg-[#3182F6]`
**Fix:** `text-text-primary`, `bg-brand`

### 2. Raw Pixel Values in Tailwind
```bash
grep -n 'p-\[.*px\]\|m-\[.*px\]\|gap-\[.*px\]' [file]
```
**Violation:** `p-[24px]`, `gap-[12px]`
**Fix:** `p-6`, `gap-3`

### 3. Old Width/Height Syntax
```bash
grep -n 'w-[0-9] h-[0-9]\|w-\[.*\] h-\[' [file]
```
**Violation:** `w-4 h-4`
**Fix:** `size-4`

### 4. Physical Properties (LTR-only)
```bash
grep -n ' ml-\| mr-\| pl-\| pr-' [file]
```
**Violation:** `ml-2`, `mr-4`
**Fix:** `ms-2`, `me-4`

### 5. Uncontracted Hard Black
```bash
grep -n 'text-black\|bg-black\|#000000\|#000"' [file]
```
**Violation:** Pure black without an exact structural role in the selected grammar/profile
**Fix:** Use the semantic ink token, or cite the maintained contract that requires hard black

### 6. Missing data-slot
```bash
grep -n 'function [A-Z]' [file] # find components
grep -n 'data-slot' [file]       # check if present
```
**Violation:** Component without `data-slot`
**Fix:** Add `data-slot="component-name"`

### 7. Font Size CSS Variables (CRITICAL — Tailwind v4 conflict)
```bash
grep -n 'text-\[var(--' [file]
grep -n '\-\-text-.*px\|--fs-.*px' [file]
```
**Violation:** `text-[var(--text-sm)]` or `--text-sm: 13px` in theme.css
**Fix:** Use explicit `text-[13px]`. CSS variable font sizes conflict with Tailwind v4's `--text-*` namespace — Tailwind reads them as color, not font-size.

### 8. className Without cn()
```bash
grep -n 'className={`' [file]
```
**Violation:** Template literal className
**Fix:** Use `cn()` for all className composition

### 9. Universal Soft-card Drift
Search for repeated `rounded-2xl`, `shadow-[var(--shadow-card)]`, and `mx-6` in pattern files.
Flag the combination when the selected recipe is not `calm-consumer`.
**Fix:** use `ss-pattern-surface`, `ss-page-gutter`, and the other recipe-aware helper classes.

## Output Format

```
🔴 FAIL  [file:line] Hardcoded hex: text-[#3C3C3C] → use text-text-primary
🔴 FAIL  [file:line] Raw px: p-[24px] → use p-6
🟡 WARN  [file:line] Physical prop: ml-2 → use ms-2
🟡 WARN  [file:line] Missing data-slot on MyComponent
🟢 PASS  No violations found

Total: X errors, Y warnings
```

If errors > 0, list specific fixes for each violation.


## CodingDude notes

- Shell commands run through CodingDude's approval-gated shell tool.
- Known v4.1.0 quirk: right after a successful resolve, `styleseed-check` may still report `SS000 artifact manifest method hash is stale` (platform hash drift). If it appears immediately after a clean resolve, treat it as advisory and rely on the SS001-SS006 detector findings, which are hash-independent.
- Sibling tooling: the `ss-resolve` skill directory sits beside `ss-score`; every load_skill response names the skill directory.
