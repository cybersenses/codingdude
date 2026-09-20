# Product Management Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — product division (product-manager, product-feedback-synthesizer, product-sprint-prioritizer, product-trend-researcher, product-behavioral-nudge-engine)
https://github.com/msitarzewski/agency-agents/tree/main/product

Use when: turning user requests into specs, prioritizing work, designing feedback loops or in-product nudges. Directly shapes how agent requests (like ours) should be triaged.

## Checklist

- [ ] Lead with the problem, not the solution — never accept a feature request at face value; find the underlying user pain or business goal before evaluating approaches.
- [ ] Write the press release before the PRD: if the user value can't be articulated in one clear paragraph, requirements aren't ready.
- [ ] No roadmap item without an owner, a success metric, and a time horizon. "Someday/maybe" is not a roadmap item.
- [ ] Every feature is a hypothesis: validate before build (interviews, behavioral data, support signal, competitive pressure); measure after ship. No green-lighting significant scope on evidence-free intuition.
- [ ] Every change request documented and evaluated against current goals — accept, defer, or reject explicitly. Never silently absorb scope (aligns with our Minimal Change Engineer adoption).
- [ ] Prioritization is comparative: rank against what the effort displaces; every yes is an explicit no.
- [ ] Feedback synthesis separates signal from volume: one request from ten users ≠ ten requests; tag by user segment and severity.
- [ ] Nudges/UX persuasion: define the intended behavior change and how to detect backfire (annoyance, dark-pattern perception) before shipping.
- [ ] Alignment ≠ agreement: the requirement is that everyone understands the decision, reasoning, and their role — not unanimity.
- [ ] Surprises are failures: delays, scope changes, and missed metrics are communicated before discovery, not after.
- [ ] Trend research: distinguish fad from durable shift with adoption-curve evidence; a trend justifies experiments, not roadmap commitments.

## Failure modes (observed in source personas)

- Solution-forward requests that skip problem definition — builds the wrong thing efficiently.
- Vague roadmap items that produce vague outcomes and no accountability.
- Feedback volumes treated as democratic votes; loud segments override severe pain.
- Silent scope absorption until the sprint is dead.

## Rejected

- Sprint-ceremony templates and RICE-scoring spreadsheets — the invariants above outlive any specific framework.
- Behavioral-nudge "growth tactic" catalogs without ethics/backfire checks.
