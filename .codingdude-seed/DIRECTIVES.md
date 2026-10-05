# CodingDude Global Directives

## Before coding
- Read the target area first. Reuse existing helpers over new ones; one source of truth per behavior. Name what you reuse.
- If a matching skill exists (tdd, diagnosing-bugs, ss-*, code-review...), load it and follow it before improvising.
- Non-trivial work gets a plan (propose_plan). Trivial work just gets done.
- Stay in scope: no unrequested refactors, no speculative abstractions, no features the task didn't ask for.

## Code
- Match the codebase's existing style, naming, and structure exactly; use the project's CONTEXT.md vocabulary.
- Fail fast: guard clauses, early returns, flat logic. Deep nesting (>2 levels) and very long functions are a smell — split with intent (deep modules, not line-count rules).
- Strict typing where the language supports it; validate external inputs at the boundary.
- No silent catches: every except handles, logs with context, or propagates. At tool boundaries, return readable error messages; in core logic, raise.
- No hardcoded secrets, no eval, no placeholders or TODOs — deliver complete, runnable code.
- Never gues APIs. Always refer to documentation
- Before claiming a performance fix, benchmark before/after with compare_bench

## Testing
- Behavior changes ship with tests at pre-agreed seams (load the tdd skill).
- Mock only true system boundaries (third-party APIs, time); prefer real test databases over mocks for your own persistence layer.

## Verification — evidence before done
- Never claim work is complete, fixed, or passing without running the verification command in this session and reading its output. Cite: test count, exit code.
- Python tests/linters are venv-scoped, NOT on global PATH: run them as `uv run pytest -q`, `uv run ruff check src tests`, `uv run mypy` from the project root (or `gates.bat` for all three). Before declaring any tool "missing", check `.venv/Scripts/` first — "not recognized" in a bare shell does not mean absent.
- Python changes: `uv run pytest -q` plus ruff and mypy clean. Frontend changes: `npm run build`.

## Security & safety
- Never touch `~/.codingdude` unless this is for codingdude devlopment and optimisation purposes and then it is read only, never restart or kill the server, never run destructive OS operations outside the approved gate flow.
- Never print or log secrets; treat environment values as write-only.

## Architectural awareness
- Alway do upstream and downstream check on any code changes and evaluate impact on all callers and called function when udateing any code

## Efficiancy
 - always use codegraph then navigating code

## Ressolution of logic or understanding
- If you are unsure always as the user for clarity. Do not guess or asume anything
- Always enforce your understanding of what the user really wants and use grilling skills and documentation to drive understanding

## Documentation
- Always document everything before you execute.
- Keep the documentation terse and relevant

## Development Process
- usual process: spec → ticket → tests → implement → gates → review → commit/push → roadmap
