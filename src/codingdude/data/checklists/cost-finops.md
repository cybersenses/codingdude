# Cloud cost (FinOps) checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-finops-engineer.md
Use when: a built system runs on billable cloud infra and spend needs visibility or reduction.

## Checklist
- [ ] Mandatory tags enforced at provisioning (team / service / environment / cost-center); untagged spend driven toward zero (>95% allocated target).
- [ ] Optimization levers applied IN ORDER: (1) kill idle/orphaned resources, (2) schedule non-prod stop/start (~65% of non-prod cost), (3) rightsize with SLO headroom preserved, (4) storage tiering + snapshot lifecycle, (5) egress paths (VPC endpoints, CDN, locality), (6) commitments last.
- [ ] Commitments (RI/savings plans) only on proven stable baselines: 30–90 day floor (not peaks), roadmap confirmed with the owning team (no pending migration/refactor), ~70–85% coverage target leaving on-demand headroom.
- [ ] Commitment utilization AND coverage tracked monthly — an unused commitment is a discount you paid for.
- [ ] Hidden costs traced: cross-AZ/cross-region traffic, NAT processing, internet egress, snapshot sprawl, forgotten dev environments.
- [ ] Unit economics measured: cost per customer/request/transaction trended — flat-or-falling unit cost with rising total = scaling efficiently.
- [ ] Anomaly alerts on daily spend (catch runaways in hours, not at month-end); budget-vs-forecast view.
- [ ] Every optimization owned by the team controlling the resource, with dollars-saved and reliability-risk quantified.
- [ ] Reliability is a constraint, not a variable: no rightsizing that breaches SLO headroom, no savings that risk an outage.

## Failure modes
- Discounting garbage: buying a savings plan on top of idle spend instead of eliminating it first.
- Committing 1–3 years ahead of a refactor/migration → stranded commitment.
- Optimizing an unallocated bill — you can't attribute, so you can't act.
- Rightsizing away burst headroom → outage that costs more than the saving.

## Rejected
- Org-program maturity models, chargeback politics, multi-cloud billing pipelines.
