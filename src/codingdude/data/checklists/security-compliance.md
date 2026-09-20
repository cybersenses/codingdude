# Security & Compliance Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — security division (appsec-engineer, penetration-tester, secrets-credential-engineer, compliance-auditor, cloud-security-architect, incident-responder, ai-generated-code-auditor, threat-detection, blockchain auditor; 11 personas reviewed). Complements checklists/security-privacy.md (identity/privacy-by-design).
https://github.com/msitarzewski/agency-agents/tree/main/security

Use when: reviewing code for security findings, handling credentials, passing compliance audits, or responding to incidents. Especially relevant for auditing AI-generated code.

## Secrets & credentials

- [ ] Secret scanning at the earliest gate: pre-commit block + CI fail, so a secret never reaches the default branch.
- [ ] Distinguish publishable/anon keys from real secrets so scanners never cry wolf (muted scanners are worse than none).
- [ ] Vault/broker, never hardcode; least-privilege, short-lived credentials by default.
- [ ] Rotation must be non-breaking: overlap old and new credentials during cutover so rotation never becomes an outage.
- [ ] A leak is resolved only when the exposed credential is **revoked at the provider** and replaced — code removal is necessary but never sufficient (value lives in history, clones, logs).
- [ ] Measure success by a secret's blast radius (time-to-revoke), not by how well it's hidden.

## Finding quality (appsec / AI-code audit / pen-test)

- [ ] Evidence over assertion: every finding ships with the exploit path AND the concrete fix beside it — never "possible secret detected".
- [ ] A fix claim is only closed by a rescan proving the finding gone; unverified fixes are worse than known gaps.
- [ ] Prefer false negatives to false positives on heuristic checks (taint, prompt-injection): ambiguous flow gets silence, not a guess.
- [ ] AI-generated code gets the same (not more, not less) scrutiny — audit for the model's characteristic failures: plausible-but-wrong auth checks, hallucinated API usage, copied-in insecure snippets.
- [ ] Scope every pen-test in writing; findings beyond scope are noted, not exploited.

## Cloud & architecture

- [ ] Least privilege per service identity; no shared admin credentials between environments.
- [ ] Environment isolation enforced at the network/IAM layer, not by convention.
- [ ] Every data store's encryption-at-rest and -in-transit state written down.

## Incident response

- [ ] IR plan names roles, escalation paths, and communication templates before the incident.
- [ ] Timeline preservation first: capture logs/state before remediation mutates the scene.
- [ ] Post-incident review is blameless and produces owned action items with dates (matches our post-mortem standard in diagnosing-bugs).

## Compliance

- [ ] Controls mapped to named requirements (SOC 2 / ISO 27001 / FedRAMP as applicable) with evidence pointers — "we comply" is not a control.
- [ ] Evidence collection automated where possible; manual screenshots rot.

## Failure modes (observed in source personas)

- Leak "resolved" by deleting the line from the repo while the key stays live.
- Scanner muted after false positives; next real leak sails through.
- Perfect scores trusted without evidence — "zero issues found" is a red flag, not a green light.
- Long-lived static credentials nobody dares rotate because rotation is breaking.

## Rejected

- Tool catalogs (Burp/Nessus/Wiz), blockchain-audit specifics, threat-intel feed lists — domain docs cover these; invariants travel.
