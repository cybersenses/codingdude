# Business Operations Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — specialized + support divisions (~76 personas reviewed; high-signal subset distilled): customer-service, hr-onboarding, legal-document-review, supply-chain-strategist, pricing-analyst, sales-outreach, loan-officer, grant-writer, support-responders
https://github.com/msitarzewski/agency-agents/tree/main/specialized

Use when: building customer-facing support tooling, workflow/ops software, pricing engines, procurement or document-review systems. Most of the 76 personas are role-play scripts with no software-derivable checks; the invariants below are the durable subset.

## Customer service & support tooling

- [ ] Acknowledge before solving: response templates/agents lead with acknowledgment, never policy.
- [ ] Never a bare "no": every refusal carries the closest genuine alternative.
- [ ] Commitments bounded by capability: only promise what the system verifiably does; broken promises cost more than the original issue.
- [ ] Escalation proactive, framed as benefit — trigger before frustration peaks, not after.
- [ ] Full interaction logging: every commitment, resolution, and escalation persisted so the next handler has complete context.
- [ ] Personalization from real data (name, history, specifics) — never template-visible ticket numbers.

## Procurement / supply chain

- [ ] Critical inputs never single-sourced; verified alternatives mandatory.
- [ ] Safety-stock parameters derived from data, reviewed on a schedule — not guesswork frozen at setup.
- [ ] Supplier qualification steps unskippable under delivery pressure; the deadline is never a reason to skip verification.
- [ ] Every procurement decision documented for traceability/audit.

## Pricing

- [ ] Every price change tied to a stated rationale (cost, elasticity, competitive) and a measurable objective.
- [ ] Pricing experiments: one lever at a time, defined success metric, kill criterion pre-agreed.
- [ ] Discount authority encoded in rules, not vibes — who can discount what by how much is system-enforced.

## Document review / legal-adjacent

- [ ] Review output separates findings (quoted, located) from risk judgments; never paraphrase clause text.
- [ ] Standard-playbook deviations flagged explicitly with the deviation named.
- [ ] Nothing is "approved" — reviews produce findings and recommendations; authority to accept stays with the accountable human.

## HR / onboarding systems

- [ ] Onboarding workflows are checkable state machines with owners per step — not documents.
- [ ] Sensitive-data access in HR tooling is least-privilege and logged like any regulated domain.

## Failure modes (observed in source personas)

- Support agents promising fixes the product can't deliver — trust debt compounding.
- Single-sourced critical supply discovered only at failure.
- Document reviews that paraphrase clauses into false comfort.
- Onboarding checklists living in someone's head/mailbox.

## Rejected

- The remaining ~60 specialized/support personas (resume-tailor, focus-music-architect, study-abroad-advisor, strategy-duel-agent, real-estate scripts…) — human-task roleplay with no extractable software invariants.
