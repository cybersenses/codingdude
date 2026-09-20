# API design checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-api-platform-engineer.md
Use when: designing, versioning, or exposing any API consumed by other code (public, partner, or internal).

## Checklist
- [ ] Contract-first: OpenAPI/gRPC/protobuf spec written and reviewed BEFORE implementation; spec is the source of truth.
- [ ] Naming consistent to the point of boredom: one casing convention (snake_case or camelCase), ISO 8601 dates, one pagination style, one ID format, one error shape — identical across every endpoint.
- [ ] One error shape everywhere: stable machine-readable `code`, human-readable `message`, contextual `details`, `request_id` for support tracing. Correct HTTP status semantics — a 200 with `{"error": ...}` is a bug.
- [ ] Every write operation idempotent: idempotency keys on creates; retry semantics defined.
- [ ] Rate limits communicated: `X-RateLimit-Limit/Remaining/Reset` headers on responses; breach → `429` + `Retry-After`, never a silent drop or ambush mid-integration.
- [ ] Breaking vs additive classified per change. Additive (new optional field/endpoint/param/error code, relaxed validation) ships in-place; breaking (remove/rename field, change type, tighten validation, change error structure) requires a new major version + migration path.
- [ ] Automated spec-diff/compatibility check in CI blocks silent breaking changes.
- [ ] Deprecation runway, never a cliff: announce + migration guide → `Deprecation`/`Sunset` headers → 6–12+ month window → monitor remaining usage per consumer → sunset only near-zero.
- [ ] SDKs + docs generated from the spec in CI so they cannot drift; five-minute quickstart with working auth exists.
- [ ] Pagination: cursors for append-heavy/large datasets (offset breaks under inserts); cursor stability documented.

## Failure modes
- Retrofitting a spec onto shipped code — every inconsistency gets baked in.
- Silent breaking change to a field a consumer's code depends on.
- Deprecation cliff: endpoint pulled with no runway; partners blindsided.
- Inconsistent naming across endpoints (`created_at` vs `dateCreated`) → integrator 2am bugs and support load.
- String-matching error prose because no stable error `code` exists.

## Rejected
- Protocol-choice essays (gRPC vs GraphQL), portal analytics, gateway productization.
