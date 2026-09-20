# QA & Testing Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — testing division (test-automation-engineer, api-tester, performance-benchmarker, accessibility-auditor, reality-checker, evidence-collector, workflow-optimizer; 9 personas reviewed)
https://github.com/msitarzewski/agency-agents/tree/main/testing

Use when: building test suites, verifying agent/AI output, performance work, or accessibility gates. Heavily aligned with our existing verification-before-completion discipline.

## Checklist

- [ ] Default status is "NEEDS WORK" until overwhelming proof says otherwise — certification of "done/production-ready" requires captured evidence (screenshots, test output), not reports.
- [ ] Treat perfect scores or "zero issues found" from a prior pass as a red flag, not a green light; cross-check claims against actual artifacts.
- [ ] Test at the contract boundary for APIs: schema validation, status-code matrix (not just 200), auth negative cases, idempotency of retries.
- [ ] Performance numbers without a baseline and environment spec are noise: record hardware, dataset size, concurrency, and warm/cold state with every measurement.
- [ ] Regression suites run in CI on every change; a test that only runs when someone remembers is not a test.
- [ ] Flaky tests quarantined same-day with an owner — a red suite everyone ignores is worse than no suite.
- [ ] Accessibility: keyboard-only path through every flow, contrast ≥ WCAG AA, screen-reader labels on interactive elements — checked per feature, not at project end.
- [ ] Test data is representative (edge sizes, unicode, empty, concurrent) — happy-path fixtures validate nothing.
- [ ] Every bug fix adds the regression test that would have caught it (red→green).
- [ ] Coverage gaps named explicitly: "files inspected vs not inspected" honesty in test reports (matches our caveman-explore adoption).

## Failure modes (observed in source personas)

- Report-at-face-value verification: trusting an upstream agent's summary instead of the artifact.
- Benchmarks run on the dev rig against toy data, then cited as production capacity.
- Accessibility deferred to a "phase 2" that never arrives.
- Green CI treated as proof of correctness when the new code shipped with no new tests.

## Rejected

- Tool-evaluation matrices and workflow-optimizer process diagrams — meta-work, not invariants.
- "Luxury/premium quality" scoring rubrics without implementation evidence.
