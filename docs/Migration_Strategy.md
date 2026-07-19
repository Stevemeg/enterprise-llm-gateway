# Migration Strategy

**Phase:** 3 — Database Architecture · Draft for approval
**Last updated:** 2026-07-15

How schema changes are versioned, ordered, and rolled out safely across SaaS cells and self-hosted
installs — **one migration path for both modes** (NFR-D01). No ORM/application code is produced here;
this defines the *process* and *ordering* the implementation phases follow.

## 1. Tooling & principles
- **Versioned, forward-only migrations** with an embedded ordering (timestamped/sequential ids),
  applied by a standard migrator (e.g., Alembic or sqlx/dbmate — chosen in Phase 5; the *strategy* is
  tool-agnostic). Each migration is **idempotent-safe to re-run detection** via a `schema_migrations`
  ledger table.
- **Expand → migrate → contract** for all breaking changes (zero-downtime): add new structures, backfill,
  switch reads/writes, then remove old — never a destructive change in one step.
- **Transactional DDL** where possible (PostgreSQL supports transactional DDL); long/locking operations
  (index builds, `ALTER` rewrites) use non-blocking variants.
- **Same migrations run in CI, SaaS, and self-host**; deployment mode differences are data/config, not
  schema forks (ADR-0011).

## 2. Migration ordering (dependency-correct)
Objects must be created in dependency order. The canonical order (matches [`Schema.sql`](Schema.sql)):

1. **Extensions** — `pgcrypto`, `vector`, `pg_stat_statements`, `btree_gin`, `citext`.
2. **Enum types** — all `CREATE TYPE`.
3. **Core tenant root** — `organization`.
4. **Identity** — `app_user`, `oauth_identity`, `service_account`, `session`, `refresh_token`.
5. **RBAC** — `permission`, `role`, `role_permission`, `membership`.
6. **Projects & access** — `project`, `project_member`, `api_key`, `api_key_scope`.
7. **Secrets refs** — `secret_reference` (before `provider` FK is added).
8. **Providers/registry** — `provider`, `model`, `price_table`, `provider_health`.
9. **Deferred FK** — `provider.credential_secret_ref → secret_reference`.
10. **Routing & prompts** — `routing_policy`, `routing_policy_rule`, `prompt_template`, `prompt_version`.
11. **Cache** — `embedding`, `semantic_cache_entry`.
12. **Cost/ledger/billing** — `budget`, `reservation`, `usage_ledger` (+partitions), `usage_rollup`,
    `billing_account`, `invoice`, `rate_limit_policy`.
13. **Governance/ops** — `audit_event` (+partitions), `governance_policy`, `feature_flag`,
    `notification`, `background_job`, `configuration`, `webhook`, `webhook_delivery`.
14. **Indexes** (incl. HNSW) — after tables/data shape settled.
15. **RLS enable/force + policies**.
16. **Grants/roles** — app role (no UPDATE/DELETE on `audit_event`/`usage_ledger`), worker/reconciler
    role, RLS-bypass role for maintenance (see [`RLS_Strategy.md`](RLS_Strategy.md)).
17. **Seed data** (see §4).

> Note: `secret_reference` is created **before** `provider`'s FK to it; the schema file inlines
> `secret_reference` later for readability and resolves the FK via a deferred `ALTER TABLE`, but the
> **migration order creates it before the FK** (step 7/9).

## 3. Partitioned-table migrations
- Creating `usage_ledger` / `audit_event` also creates the **initial + rolling** partitions; the
  partition-automation job (Phase 12) owns ongoing creation/detach.
- Changing a partitioned table's columns uses expand/contract; never rewrite a huge partition in place.
- pgvector **dimension changes** are a *new column/table + re-embed* migration (ADR-0007), never an
  in-place type change.

## 4. Seed-data strategy
Idempotent seed migrations (upsert on natural keys):
- **Global reference:** full `permission` catalog; system `role`s (`owner/admin/operator/finance/
  auditor/developer`) and their `role_permission` grants (ADR-0008 matrix).
- **Per-org bootstrap** (invoked on org creation, not a global migration): default `governance_policy`,
  default `routing_policy`, owner `membership`.
- **Self-host bootstrap:** single `organization` (`deployment_mode='self_hosted'`), initial admin
  user + service account.
- Seeds are re-runnable and environment-agnostic; secrets are **never** seeded (only `secret_reference`
  pointers).

## 5. Zero-downtime patterns
| Change | Pattern |
|--------|---------|
| Add column | Nullable/defaulted add (fast in PG11+), backfill in batches, then constrain |
| Add index | `CREATE INDEX CONCURRENTLY` (outside txn) |
| Rename/replace column | Add new → dual-write/backfill → switch reads → drop old |
| New enum value | `ALTER TYPE ... ADD VALUE` (non-blocking; cannot run in a txn block with use) |
| New table/FK | Additive; safe |
| Drop object | Only in **contract** step after code no longer references it |

## 6. Rollback & safety
- Forward-only philosophy: each migration ships with a tested **down**/compensating step for
  emergencies, but production recovery favors **roll-forward** + PITR (see
  [`Backup_and_Recovery.md`](Backup_and_Recovery.md)) over destructive down-migrations.
- Migrations run in **CI against an ephemeral Postgres** (with `vector`/`citext`) and are gated by the
  Phase-11 pipeline; a migration that fails validation blocks deploy.
- Pre-deploy: snapshot/backup; post-deploy: smoke checks (RLS on, counts, key queries).

## 7. Validation in CI (Phase 11)
- Apply all migrations to an empty DB → assert final schema matches `Schema.sql` (drift check).
- Run **RLS isolation tests** and **referential-integrity checks** (no orphan FKs) on every migration.
- Load a small seed and run smoke queries for each domain.

## 8. Requirements traceability
NFR-D01 (one path both modes), NFR-M05/SM-Q* (CI gates), NFR-A05 (backup before migrate), NFR-SEC03
(no seeded secrets), ADR-0002/0008/0009 (RLS, roles, append-only grants).
