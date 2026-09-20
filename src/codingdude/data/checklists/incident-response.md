# Incident response checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-incident-response-commander.md
Use when: defining incident process, severity levels, runbooks, on-call, SLOs, or post-mortems for a system being built.

## Checklist
- [ ] Severity framework defined (SEV1–4) with per-level: response time, update cadence, escalation path.
- [ ] Auto-upgrade triggers documented: impact scope doubles; no root cause within timebox (30 min SEV1 / 2 h SEV2); paying-customer impact ≥ SEV2; any data-integrity concern = SEV1.
- [ ] Explicit roles before troubleshooting: Incident Commander (owns decisions + timeline), Comms Lead, Technical Lead, Scribe.
- [ ] Stakeholder updates at fixed cadence per severity (SEV1: every 15 min), even when the update is "no change".
- [ ] Real-time written timeline in a shared channel — the channel is the source of truth, not memory.
- [ ] Mitigate before root-causing: rollback / scale / failover / feature-flag first; verify recovery via metrics (SLIs back in SLO), then monitor 15–30 min before declaring resolved.
- [ ] Blameless post-mortem within 48 h for every SEV1/SEV2: timeline, impact (users/revenue/error-budget), contributing factors (immediate / underlying / systemic), 5 Whys, what went well/poorly, action items with owners + deadlines — and action items tracked to completion.
- [ ] Runbooks per known failure scenario with: detection signal + false-positive check, diagnosis steps, remediation options (rollback preferred for deploy-related), verification checklist, comms plan, and a "last tested" date. Tested quarterly — untested runbook = false security.
- [ ] SLOs defined on SLIs (availability, latency, correctness) with 30-day windows, error budgets, and multi-window burn-rate alerts (e.g. page at 14.4× over 5m/1h; ticket at 6× over 30m/6h).
- [ ] Error-budget policy has teeth: budget exhausted → feature work freezes for reliability work.
- [ ] On-call: ≥4-person rotation, ≤2 consecutive weeks, business-hours handoff, shadow period for new engineers, alert if >5 pages/engineer/week (noisy-alert signal).
- [ ] Post-mortem patterns feed back: repeat incidents = previous action items not completed; tight error budgets = architectural investment needed.

## Failure modes
- Skipping severity classification → wrong escalation, cadence, and resourcing.
- "Single person's knowledge" — tribal knowledge never written into runbooks (bus factor 1).
- Heroics over preparation; mitigation skipped while everyone root-causes.
- Post-mortem as ritual: findings recorded, action items never completed, same incident repeats quarterly.
- Blame framing → engineers hide problems instead of escalating.

## Rejected
- On-call compensation policy, PagerDuty YAML configs, org-chart coordination — org-scale detail, not build-time checklists.
