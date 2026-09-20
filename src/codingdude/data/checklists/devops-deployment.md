# DevOps & deployment checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-devops-automator.md
Use when: setting up CI/CD, infrastructure-as-code, deployment, or monitoring for a system.

## Checklist
- [ ] Infrastructure defined as code (Terraform/CloudFormation/CDK), version-controlled, reproducible.
- [ ] CI pipeline stages: security scan → tests (unit + integration) → build → deploy; dependency + container vulnerability scanning with a fail threshold.
- [ ] Zero-downtime deploy strategy chosen (blue-green / canary / rolling) with automated health checks gating traffic switch.
- [ ] Automated rollback: trigger + process defined and tested, not manual heroics.
- [ ] Secrets management: no secrets in repo/pipeline logs; rotation automated.
- [ ] Monitoring: application + infrastructure metrics scraped (Prometheus/Grafana/Datadog); alert rules for error rate and p95/p99 latency with `for:` durations to avoid flapping.
- [ ] Log aggregation + (for microservices) distributed tracing set up.
- [ ] Multi-environment (dev/staging/prod) with promotion flow; auto-scaling + load balancing configured.
- [ ] Backup/disaster-recovery automation exists and is exercised.
- [ ] On-call/notification routing: severity levels → channels (Slack/PagerDuty) with escalation policy.

## Failure modes
- Manual deploy steps that only one person knows ("works on my machine" infra).
- Health check missing → traffic switched to a broken deploy.
- Alerts without `for:`/aggregation → flapping pages train engineers to ignore them.
- Security scanning bolted on after the pipeline instead of gating it.

## Rejected
- Tool-specific YAML boilerplate and marketing metrics ("multiple deploys/day"). Kept the gate structure.
