# Healthcare & Regulated-Domain Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — healthcare division (clinical-evidence-agent, innovation-strategist, sovereign-health-systems-agent) + regulated-adjacent specialized personas (medical-billing-coding, healthcare-marketing-compliance, healthcare-customer-service)
https://github.com/msitarzewski/agency-agents/tree/main/healthcare

Use when: building anything touching health data, clinical claims, or other regulated/high-stakes domains (legal, financial advice) where wrong output causes real harm.

## Checklist

- [ ] No outcomes claim without a cited data source or validated reference; extrapolations labeled as extrapolations, never presented as findings.
- [ ] AI features positioned as decision support only — never diagnostic/decision authority; the human professional owns the call, and the UI must say so.
- [ ] Write for scrutiny: peer-review register, hedged language, uncertainty stated numerically where possible.
- [ ] Distinguish established evidence from emerging research from opinion in every artifact; label each.
- [ ] Regulatory posture decided before build (HIPAA/GDPR-health/local sovereign rules): data residency, consent model, audit trail, retention.
- [ ] PHI minimization: collect/keep only what the feature demonstrably needs; pseudonymize by default.
- [ ] Every access to patient/regulated data is logged with who/what/when (audit trail is a feature, not overhead).
- [ ] Coding/billing claims (ICD/CPT-style) validated against current code sets with version pinning — stale code sets cause rejections and compliance exposure.
- [ ] Marketing/comms in regulated domains reviewed against claim-substantiation rules before publication.
- [ ] Degrade honestly: when data is missing or the model is uncertain, say so rather than producing confident filler.

## Failure modes (observed in source personas)

- Confident AI prose stating an outcome the source data doesn't support.
- "Decision support" tools drifting into de-facto diagnostic authority through UI framing.
- Consent captured once at onboarding and treated as permanent.

## Rejected

- Country-specific health-system implementation guides (kept the invariants; local rules belong in per-project compliance work).
- Caregiver/companion persona content — not software guidance.

## Generalizes

- The evidence-labeling and decision-support framing applies to legal-document review, financial advice, and tax tooling — any domain where output is acted on with real consequences.
