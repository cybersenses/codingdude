# Security & privacy checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-identity-access-engineer.md, https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-privacy-engineer.md
Use when: building authentication/authorization or handling personal data in any system.

## Checklist

### Identity & access
- [ ] No invented auth primitives: OAuth 2.0 authorization-code + PKCE, Argon2id/bcrypt via vetted libraries. "Simplified OAuth" or custom token formats rejected.
- [ ] OIDC callback validates EVERYTHING: exact-match redirect URI allowlist, `state`, `nonce`, PKCE verifier, issuer + audience pinned, `alg` against an allowlist (`none` is an attack).
- [ ] Access tokens short-lived (minutes, ≤15 min for JWT); refresh tokens rotate on every use — reuse of a rotated token revokes the whole family and alerts.
- [ ] Authorization enforced server-side on EVERY request; UI hiding is UX, not security.
- [ ] Tenant isolation enforced at the data layer (row-level security / query scoping from the authenticated session), never from request parameters and never by developer discipline.
- [ ] JWTs carry identifiers only — no secrets or PII (readable by anyone holding them). Browser storage: `HttpOnly; Secure; SameSite` cookies, never `localStorage`.
- [ ] Recovery flows designed like login: time-limited single-use tokens, no user enumeration, step-up verification for sensitive changes. Recovery is the attacker's favorite door.
- [ ] Every auth event audited (logins, failures, lockouts, resets, permission/SSO changes); users see "invalid credentials", the log sees which credential and how many attempts.
- [ ] Failure paths tested like an attacker: cross-tenant access, token replay, `alg` confusion, redirect manipulation, session fixation, recovery abuse.
- [ ] Enterprise SSO (if applicable): per-tenant IdP config, SAML signature/audience/InResponseTo/clock-skew checks, domain-verified users forced to SSO, SCIM deprovisioning revokes sessions ≤60s, break-glass admin path.

### Privacy
- [ ] Data map exists: field → stores (including logs, traces, caches, search indexes, queues, backups, third parties) → purpose → legal basis → retention → delete path. Regenerated on a schedule.
- [ ] Minimization at collection: every field has a purpose and basis; over-collection is a code-review failure. No purpose → don't collect.
- [ ] Consent enforced at the write/use path — a stored opt-out that doesn't gate the operation is theater. Purpose-scoped, versioned grants.
- [ ] Right-to-be-forgotten pipeline: fan-out deletion to every location in the data map (replicas, warehouse, index, cache, third parties, backup tombstones), idempotent, verified by re-scan, with an audit record.
- [ ] Retention enforced by automated expiry jobs, not memory.
- [ ] "Anonymized" proven, not labeled: removed-name ≠ anonymous (zip + birthdate + gender re-identifies). Use k-anonymity/aggregation/differential privacy and test re-identification risk before the label.
- [ ] Zero unclassified PII in logs/traces/analytics — automated scanning in place.
- [ ] New third-party/cross-border data flows require legal basis + DPA + data-map entry before shipping. Privacy reviewed at design-doc stage, not post-incident.

## Failure modes
- Homegrown token scheme or hand-rolled hashing — the "clever" auth path.
- JWT in localStorage: any XSS becomes full account takeover.
- Deletion that clears one table while the data lives in five systems — a false promise with audit exposure.
- Consent recorded but never checked at the write path.
- False anonymization shipped to a third party.

## Rejected
- Protocol depth (DPoP, PAR, SAML forensics), Zanzibar/OPA guidance, compliance-cert mapping. Kept the checkable core.
