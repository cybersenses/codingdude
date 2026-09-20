# Data engineering checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-data-engineer.md
Use when: building data pipelines, ETL/ELT, lakehouse layers, or streaming ingestion for a system.

## Checklist
- [ ] Every pipeline idempotent — rerunning produces the same result, never duplicates.
- [ ] Explicit schema contracts between producers and consumers; schema drift alerts, never silently corrupts.
- [ ] Medallion layering if lakehouse: Bronze = raw/immutable/append-only with ingestion metadata (source, timestamp); Silver = cleansed/deduplicated/conformed; Gold = business-ready aggregations with SLAs. Gold consumers never read Bronze/Silver directly.
- [ ] Deduplication by primary key + event/ingestion timestamp (latest wins) before conforming.
- [ ] Null handling deliberate per field: impute, flag, or reject — no implicit null propagation into semantic layers.
- [ ] Audit columns everywhere: `created_at`, `updated_at`, `deleted_at` (soft deletes), `source_system`.
- [ ] Data quality tests enforced in the transformation layer (not_null/unique/relationships/range/recency tests; contracts enforced).
- [ ] Freshness SLAs defined per table and monitored; pipeline failure alerts within minutes, with a runbook and a named owner per pipeline.
- [ ] Incremental/CDC over full refresh where possible (cost + freshness); full-refresh vs incremental cost quantified.
- [ ] Streaming (if used): checkpointing, late-arriving data handling, exactly-once or documented at-least-once semantics with idempotent sinks.
- [ ] Partitioning/clustering aligned to query patterns; unbounded full-table scans eliminated.
- [ ] Lineage tracked: every gold row traceable to its source; catalog documents owners + SLAs.

## Failure modes
- Silent schema drift corrupting downstream models until someone notices a wrong report.
- Null-rate spike after an upstream API change, unnoticed for weeks.
- Unbounded full-table scans → cost explosion.
- Business decisions made on stale data because freshness was never an SLA.

## Rejected
- Cloud-vendor catalog (Fabric/Synapse/Databricks features), Spark tuning depth, NPS metrics.
