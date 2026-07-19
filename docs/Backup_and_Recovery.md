# Backup & Recovery / Disaster Recovery

**Phase:** 3 — Database Architecture · Draft for approval
**Last updated:** 2026-07-15

Database-layer backup, restore, and DR, aligned to **ADR-0010** (cell-per-region, single-writer-per-
tenant) and the recovery objectives **RTO ≤30 min / RPO ≤5 min** (NFR-A05), with no single point of
failure (NFR-A03).

## 1. Backup approach (PostgreSQL)
- **Continuous WAL archiving + periodic base backups** (e.g., pgBackRest / cloud-native equivalent) →
  **Point-In-Time Recovery (PITR)**. This is the primary mechanism (meets RPO via WAL, enables
  restore to any moment).
- **Base backups:** at least daily full + incremental; retained per policy (e.g., 30 days online, longer
  in cold storage for compliance).
- **Logical dumps** (`pg_dump`) taken periodically for portability and per-tenant/table extraction
  (useful for self-host support and selective restore); **not** the primary DR mechanism at scale.
- **Encryption:** backups encrypted at rest (AES-256, NFR-SEC02); stored in a separate failure domain
  (different AZ/region/account).
- **Self-host:** the Helm chart ships a backup CronJob (pgBackRest/`pg_dump`) writing to customer-chosen
  storage; **stays in the customer boundary** (NFR-C05).

## 2. Replication & high availability
- **Intra-region:** synchronous or low-lag streaming replica in a **second AZ** (HA; automatic failover
  via the managed service or Patroni-style controller) — no SPOF (NFR-A03).
- **Cross-region:** **asynchronous** streaming replica in a partner region per cell (ADR-0010), lag
  target < RPO. Home-region single-writer preserves budget-counter atomicity (ADR-0004) — no
  multi-master conflicts.
- **Redis:** HA (primary + replicas, automatic failover), AOF persistence sized to RPO. Budget counters
  are **reconstructable from `usage_ledger`** (ADR-0004), so a total Redis loss is recoverable without
  financial data loss (reconciler rebuild).

## 3. Recovery objectives & how they're met
| Objective | Target | Mechanism |
|-----------|--------|-----------|
| **RPO** (max data loss) | ≤ 5 min | WAL archiving + async replica lag monitoring < 5 min |
| **RTO** (max downtime) | ≤ 30 min | Promote standby (intra-AZ automatic; cross-region documented runbook) |
| Redis loss | ~0 financial loss | Rebuild counters from ledger (reconciler) |
| Corruption/human error | point-in-time | PITR to just-before-incident |

## 4. Restore runbooks (summary)
1. **Single-AZ node failure:** managed HA promotes AZ-b replica automatically; verify, resume. (Minutes.)
2. **Region loss (SaaS):** promote partner-region standby for affected tenants (single-writer moves to
   partner region); repoint the cell's writer; validate budget-counter reconciliation from ledger;
   update global router. Target ≤30 min. (Per-tenant brief read-only window — ADR-0010.)
3. **Logical corruption / bad migration:** PITR the cluster (or restore a copy) to the timestamp before
   the event; replay/repair; reconcile Redis from restored ledger.
4. **Accidental tenant data loss:** selective restore from logical dump / restored copy into a staging
   DB, extract the tenant's rows (RLS-scoped), reinsert.
5. **Self-host:** documented `restore` procedure from the customer's backup target; validate with health
   checks before serving.

Each runbook lists preconditions, steps, verification queries, and rollback. Full runbooks are authored
with the ops content in Phase 12; this document fixes the strategy and objectives.

## 5. Backup verification & drills
- **Automated restore tests:** periodically restore the latest backup into an ephemeral instance and run
  integrity checks (row counts, RLS on, hash-chain verify on `audit_event`, ledger reconciliation).
- **DR game-days (Phase 13 chaos):** exercise region failover against RTO/RPO; verify no budget
  double-spend after promotion (ADR-0004/0010).
- A backup is considered valid only after a **successful test restore** (no untested backups).

## 6. Special integrity considerations
- **`audit_event`** is append-only and hash-chained; after any restore, the chain is **re-verified**
  end-to-end to prove no tampering across the recovery (FR-113/114, NFR-SEC09).
- **`usage_ledger`** is the financial source of truth; restores prioritize its completeness, and Redis
  counters are always rebuilt from it (never the reverse).
- **Partitioned tables** restore efficiently partition-by-partition; archived partitions are restorable
  from cold storage for compliance queries.

## 7. Requirements traceability
NFR-A01/A03/A05 (availability, no SPOF, RTO/RPO), NFR-SEC02 (encrypted backups), NFR-C05 (self-host
in-boundary), ADR-0004 (Redis rebuildable), ADR-0010 (cross-region DR), FR-113/114 (audit integrity
across recovery). Related: [`Data_Retention.md`](Data_Retention.md),
[`Partitioning_Strategy.md`](Partitioning_Strategy.md).
