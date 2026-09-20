# Database checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-database-optimizer.md, https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-database-reliability-engineer.md
Use when: designing schemas, writing queries/migrations, or setting up backups/HA for any datastore.

## Checklist
- [ ] Every foreign key has an index (joins + cascade deletes).
- [ ] `EXPLAIN ANALYZE` run before shipping non-trivial queries — check for Seq Scans, actual-vs-estimated row drift.
- [ ] No N+1 query patterns in app code — JOIN or batch-load.
- [ ] No `SELECT *`; fetch needed columns only.
- [ ] Composite/partial indexes match real query patterns (e.g. partial index `WHERE status='published'` for the common filter).
- [ ] Migrations reversible: DOWN migration written and tested.
- [ ] Zero-downtime DDL: `CREATE INDEX CONCURRENTLY`; no blocking `ALTER` on hot tables — expand-contract instead: add nullable column → batched backfill → dual-write → `ADD CONSTRAINT ... NOT VALID` + `VALIDATE CONSTRAINT` → contract in a later release.
- [ ] Connection pooling in place (PgBouncer/ProxySQL/managed pooler) with per-service limits; serverless uses transaction pooling. Never open a connection per request.
- [ ] Backups: continuous WAL/binlog archiving (PITR) + periodic base backups + cross-region copy. RPO/RTO defined as business inputs.
- [ ] Restores tested on a schedule into a throwaway instance, RTO measured, alert if the restore fails or exceeds budget. Untested backup = not a backup.
- [ ] Failover: quorum/fencing against split-brain, promote the most-current sync replica (never a lagging async one), app follows a stable endpoint, old primary fenced. Drilled on schedule.
- [ ] Replication lag monitored and treated as correctness: gate read-after-write on lag; block promoting lagging replicas.
- [ ] Destructive/heavy ops (migration, large delete, failover) have a written rollback plan + blast-radius estimate. No git revert on stateful systems.
- [ ] Slow-query monitoring on (pg_stat_statements or equivalent); capacity (storage, IOPS, connections) forecast ahead of demand.

## Failure modes
- The untested backup discovered unrestorable during the first real incident.
- Failover promoting a lagging replica → silent write loss.
- "Quick" ALTER taking an exclusive lock on a hot table, stalling everything behind it.
- Connection-pool exhaustion taking down a healthy database from the app side.
- Reading stale replicas for read-after-write flows.

## Rejected
- Persona voice and per-provider (Supabase/PlanetScale) color. Kept engine-agnostic mechanics.
