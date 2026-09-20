# Backend architecture checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-backend-architect.md
Use when: choosing architecture, service boundaries, or reliability patterns for a server-side system.

## Checklist
- [ ] Architecture style (monolith / modular monolith / microservices / serverless) chosen from team size, domain boundaries, operational maturity, and scaling need — microservices only when independent deployment/ownership/scaling justifies the operational cost.
- [ ] Every external call specifies: timeout budget, retry policy with backoff, idempotency requirement.
- [ ] Failure isolation: circuit breakers, graceful degradation, bulkheads, rate limits, dead-letter queues + poison-message handling.
- [ ] Every public and service-to-service API documented in a machine-readable contract (OpenAPI/AsyncAPI/protobuf) with timeout/retry/rate-limit/auth semantics and correlation IDs.
- [ ] Backwards compatibility via versioning + deprecation windows + contract tests.
- [ ] Schema/migration safety: expand-and-contract, planned backfills, dual writes, read fallbacks, rollback strategy, reconciliation checks on migrated data.
- [ ] Caching designed without introducing consistency bugs; invalidation path explicit.
- [ ] AuthZ = least privilege per service and DB role; encryption at rest and in transit.
- [ ] Observability by design: structured logs with request IDs and tenant context, SLIs/SLOs for latency/availability/errors, distributed tracing across the dependency chain.
- [ ] Dashboards alert on user-impacting symptoms (errors, latency), not just infrastructure saturation.
- [ ] Scaling: simplest model that covers current + near-term load, with the documented path to horizontal scaling.

## Failure modes
- Microservices adopted for resume reasons → distributed monolith with no independent deployability.
- Missing timeout/retry budget → one slow dependency cascades into a fleet-wide outage.
- Cache treated as "fast DB" with no invalidation design → consistency bugs.
- Alerting on CPU while users see errors.

## Rejected
- Numeric vanity targets (sub-20ms everywhere), tech-stack name-dropping.
