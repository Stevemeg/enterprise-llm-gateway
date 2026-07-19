# Partitioning Strategy

**Phase:** 3 — Database Architecture · Draft for approval
**Last updated:** 2026-07-15

Partitioning is applied **only where justified** by volume and access pattern. Over-partitioning small
tables adds planning overhead for no gain, so most of the 40 tables are **not** partitioned.

## 1. What is partitioned (and why)

### 1.1 `usage_ledger` — RANGE by `created_at`, monthly
- **Justification:** highest-volume table (~10⁹ rows/month at target scale, NFR-S05). Access is
  overwhelmingly **time-windowed** (current period usage, month-to-date cost, billing periods) and
  **append-only** (ADR-0004). Monthly range partitions give: partition pruning for time-window queries,
  smaller per-partition indexes (faster inserts, NFR-S05), and **cheap archival** by detaching old
  partitions instead of mass `DELETE` ([`Data_Retention.md`](Data_Retention.md)).
- **Key mechanics:** PK is `(id, created_at)` (partition key must be part of PK/unique). Rolling
  partitions are created ahead of time by an automation job (and pre-seeded in `Schema.sql` for
  2026-07/08 as examples). Default partition avoided — inserts must always match a month partition
  (job guarantees future partitions exist).
- **Sub-partitioning:** not needed initially; if a single month is still too large, **hash
  sub-partitioning by `organization_id`** is the escalation (keeps tenant locality).

### 1.2 `audit_event` — RANGE by `created_at`, monthly
- **Justification:** high volume (10⁷–10⁸/month), **append-only + immutable** (ADR-0009), queried by
  **time window** for compliance/export (FR-115), and retained for **long compliance windows** then
  archived. Monthly partitions enable retention-by-partition-detach without mutating immutable data and
  keep compliance queries fast.
- **Key mechanics:** PK `(id, created_at)`; hash chain (`prev_hash`/`entry_hash`) is independent of
  partitioning and remains verifiable across partitions.

## 2. Candidates deliberately NOT partitioned yet (with escalation path)

| Table | Volume | Why not now | Escalation if needed |
|-------|--------|-------------|----------------------|
| `embedding` | 10⁶–10⁸ | HNSW works within one table; ANN + tenant filter sufficient at target | Hash-partition by `organization_id` (tenant locality) or by `embedding_version` |
| `semantic_cache_entry` | 10⁶–10⁷ | TTL prune keeps it bounded | Range by `created_at` if churn grows |
| `reservation` | 10⁷ rolling | Short retention + prune keeps it small | Range by `created_at` monthly |
| `notification`, `background_job`, `webhook_delivery`, `provider_health` | 10⁶–10⁷ rolling | Aggressive prune keeps them small | Range by `created_at` if retention lengthens |

Partitioning these now would add overhead without benefit; each has a documented trigger and path.

## 3. Not partitioned (small / config tables)
All configuration/registry/identity tables (`organization`, `app_user`, `provider`, `model`,
`routing_policy`, `budget`, etc.) are ≤10⁵ rows and are **not** partitioned — a single B-tree is optimal
and partitioning would only hurt planning.

## 4. Partition lifecycle automation
- A scheduled job (Phase 12 ops) **creates next N months** of partitions ahead of time and **detaches +
  archives** partitions older than the online retention window.
- Detached partitions are exported (compressed) to object storage / a cold schema, then dropped from the
  hot cluster — see [`Data_Retention.md`](Data_Retention.md) and [`Backup_and_Recovery.md`](Backup_and_Recovery.md).
- Partition operations are DDL — scheduled in low-traffic windows; `DETACH PARTITION CONCURRENTLY`
  (PG14+) avoids long locks.

## 5. Interaction with RLS
RLS policies are defined on the **partitioned parent** and apply to all partitions (see
[`RLS_Strategy.md`](RLS_Strategy.md)); new partitions inherit enforcement automatically. Tenant-scoped
queries still prune by time first, then RLS filters by `organization_id`.

## 6. Requirements traceability
Partitioning realizes **NFR-S04/S05** (volume/throughput), **NFR-A05** (efficient restore/replay),
**FR-070..073** (durable metering), **FR-113..115** (audit retention/immutability), and enables the
archival in **NFR-C03** (retention/erasure). Decisions recorded in
[`Database_Design.md`](Database_Design.md) DB-DEC-06.
