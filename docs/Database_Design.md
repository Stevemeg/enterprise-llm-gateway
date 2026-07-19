# Database Design

**Phase:** 3 — Database Architecture & Data Model · Draft for approval
**Datastore:** PostgreSQL 16 + `pgvector`
**Last updated:** 2026-07-15

This document is the design narrative for the data model. The executable DDL is
[`Schema.sql`](Schema.sql); the entity reference is [`Data_Dictionary.md`](Data_Dictionary.md); the
diagram is [`ERD.md`](ERD.md). Strategy docs: [Indexing](Indexing_Strategy.md),
[Partitioning](Partitioning_Strategy.md), [Migration](Migration_Strategy.md),
[Backup/Recovery](Backup_and_Recovery.md), [Retention](Data_Retention.md), [RLS](RLS_Strategy.md).
Every decision references the approved [ADRs](Architecture_Decision_Log.md),
[FRs](Functional_Requirements.md), and [NFRs](Non_Functional_Requirements.md).

## 1. Objectives & scope

Realize the approved architecture as a production-grade schema supporting multi-tenancy, SaaS +
self-host, RBAC, API keys, organizations, users, projects, providers, models, routing, prompt
templates/versions, semantic cache, embeddings, budgets, reserve/commit ledger, usage metering,
billing, rate limits, audit, provider health, model registry, feature flags, notifications,
background jobs, configuration, secret references, webhooks, sessions, refresh tokens, OAuth
identities, and service accounts. **No application/ORM code** is produced in this phase.

## 2. Design conventions

| Convention | Rule | Rationale |
|-----------|------|-----------|
| Primary keys | `uuid` PK, `default gen_random_uuid()` | Non-guessable, merge-safe across cells/regions (ADR-0010), no cross-tenant enumeration. |
| ID locality | **UUIDv7 recommended app-side** for high-volume append tables (`usage_ledger`, `audit_event`, `reservation`) | Time-ordered UUIDs reduce index fragmentation vs random v4 on hot inserts (NFR-S05). `gen_random_uuid()` is the portable default; UUIDv7 generated in the app where locality matters. |
| Tenancy | `organization_id uuid NOT NULL` on every tenant-owned table + **RLS** | ADR-0002 defense-in-depth isolation (FR-130..132, NFR-SEC07). |
| Timestamps | `timestamptz`; `created_at`/`updated_at` on mutable entities | Correct TZ handling; auditability. |
| Soft delete | `deleted_at timestamptz` on long-lived entities (org, user, project, key) | Preserve history/audit; hard delete via retention jobs. |
| Naming | `snake_case`, singular table names; child tables prefixed by parent domain | Consistency, readability. `user` is reserved → `app_user`. |
| Money | `numeric` (never float) — cost `numeric(18,8)`, amounts `numeric(18,6)`/`(20,6)` | Exact monetary math (SM-T07 cost accuracy). |
| Secrets | Only **references** (`secret_reference`); never values | ADR-0011, NFR-SEC03. |
| Enumerations | Native `ENUM` for small stable sets; **lookup tables** for RBAC (`role`,`permission`) | Stability vs. extensibility (see §7). |

## 3. Domain model (bounded contexts)

The 40 tables group into eight domains:

1. **Tenancy & Identity** — `organization`, `app_user`, `oauth_identity`, `service_account`, `session`, `refresh_token`.
2. **RBAC** — `role`, `permission`, `role_permission`, `membership`.
3. **Projects & Access** — `project`, `project_member`, `api_key`, `api_key_scope`.
4. **Providers & Registry** — `provider`, `model`, `price_table`, `provider_health`.
5. **Routing & Prompts** — `routing_policy`, `routing_policy_rule`, `prompt_template`, `prompt_version`.
6. **Cache & Embeddings** — `embedding`, `semantic_cache_entry`.
7. **Cost, Ledger, Usage, Billing** — `budget`, `reservation`, `usage_ledger`, `usage_rollup`, `billing_account`, `invoice`, `rate_limit_policy`.
8. **Governance & Ops** — `audit_event`, `governance_policy`, `feature_flag`, `notification`, `background_job`, `configuration`, `secret_reference`, `webhook`, `webhook_delivery`.

Full per-table detail (purpose, PK/FK, constraints, indexes, partitioning, growth, volume, retention)
is in [`Data_Dictionary.md`](Data_Dictionary.md).

## 4. Key modeling decisions (DB-DEC)

Each decision cites approved ADRs/FRs/NFRs. Changes are recorded as new ADRs.

### DB-DEC-01 — Organization = tenant; shared schema + RLS
All tenant-owned rows carry `organization_id` and are protected by PostgreSQL **Row-Level Security**
under application scoping. Realizes **ADR-0002** (FR-130..134, NFR-SEC07/S03/S06). Self-host = one
organization; identical code path (NFR-D01). Details: [`RLS_Strategy.md`](RLS_Strategy.md).

### DB-DEC-02 — Organization → Project → API key hierarchy (refines "team")
The approved budget/routing hierarchy was *org → team → key* (ADR-0002/0004). Per Phase-3 direction,
the mid-tier is realized as **`project`**; the scope chain is **organization → project → api_key**.
This is a **naming refinement**, not a semantic change — budget levels, routing scoping, and
most-restrictive-wins enforcement (ADR-0004) are unchanged. `budget.scope` and `rate_limit_policy.scope`
use the enum `('organization','project','api_key')`.

### DB-DEC-03 — Reserve/Commit realized as `reservation` (durable) + `usage_ledger` (double-entry)
Enforcement counters live in Redis for ≤5 ms atomic reserve (**ADR-0004**, NFR-P05); Postgres holds
the **durable `reservation`** mirror (for reconciliation/audit) and the **append-only double-entry
`usage_ledger`** as the system of record (FR-070..073). The reconciler repairs Redis from the ledger
(FR-069). `usage_ledger.entry_type` (`debit`/`credit`) supports double-entry; `total_tokens` is a
`GENERATED` column for integrity.

### DB-DEC-04 — Providers/models are tenant-scoped configuration
`provider`, `model`, `price_table` carry `organization_id`. Rationale: self-host is single-tenant, and
SaaS tenants need their own credentials (referenced), enable/disable state, and pricing. Realizes
**ADR-0003** (FR-020..029). A future global model **catalog** could be layered without changing tenant
isolation (recorded as a future ADR if needed).

### DB-DEC-05 — Semantic cache = `semantic_cache_entry` + normalized `embedding` (pgvector)
Exact key is `request_hash` (SHA-256 of the normalized request, FR-050); the semantic tier links to a
normalized **`embedding`** row (`vector(1024)`, HNSW cosine index). Both tenant-scoped (+RLS) → no
cross-tenant serving (**ADR-0006/0007**, FR-057). Vectors are tagged `embedding_model`/`version`/`dim`
so a model change invalidates via version filtering, never silent space-mixing (FR-058). See §8 pgvector.

### DB-DEC-06 — Audit & usage are append-only and partitioned
`audit_event` (hash-chained, **ADR-0009**, FR-113/114, NFR-SEC09) and `usage_ledger` (FR-070..073) are
**append-only**, **range-partitioned by month**. Immutability is enforced by **role grants** (no
UPDATE/DELETE to app roles) plus RLS; the hash chain makes tampering detectable. See
[`Partitioning_Strategy.md`](Partitioning_Strategy.md) and [`RLS_Strategy.md`](RLS_Strategy.md).

### DB-DEC-07 — Secrets are references only
`secret_reference` stores a **pointer** (`provider` + `reference_path` + `version`) into an external
secrets manager — **never a secret value** (**ADR-0011**, NFR-SEC03). `provider.credential_secret_ref`
and `webhook.secret_ref` point to it. Virtual keys and refresh tokens store only **SHA-256 hashes**
(FR-097).

### DB-DEC-08 — Money as `numeric`, pricing effective-dated
All monetary columns are `numeric` (no float). `price_table` is **effective-dated** (`effective_from`/
`effective_to`) so historical cost is reproducible and current price is a simple lookup (FR-074/075,
SM-T07).

### DB-DEC-09 — Service-account credentials in a dedicated table
Service accounts authenticate via **client credentials**; the identity table holds no secret, so a
dedicated **`service_account_credential`** table stores the hashed secret with `client_id`, `status`,
and rotation timestamps (**ADR-0013**). It mirrors the `api_key` hashing/rotation pattern, supports a
rotation grace window, and is tenant-scoped with RLS. Only the SHA-256 hash is stored (NFR-SEC03).

## 5. Normalization

The schema is **3NF** by default: every non-key attribute depends on the key, the whole key, and
nothing but the key. Deliberate, documented denormalizations:

| Denormalization | Where | Justification |
|-----------------|-------|---------------|
| `usage_rollup` precomputed aggregates | §Cost | Dashboard/analytics performance (FR-086) at billions of ledger rows; derived from `usage_ledger`, refreshed by workers. Source of truth remains the ledger. |
| `organization_id` on child tables (e.g., `project_member`, `api_key_scope`, `routing_policy_rule`) | multiple | Required so **RLS** can filter without a join (ADR-0002); a controlled redundancy that is integrity-checked by the parent FK. |
| `total_tokens` generated column | `usage_ledger` | Stored generated column avoids recomputation and guarantees consistency. |

No repeating groups, no partial/transitive dependencies elsewhere. Polymorphic `budget.scope_id` /
`rate_limit_policy.scope_id` are **intentional** (scope is one of org/project/key); referential
integrity for these is enforced by application logic plus an optional validation trigger (documented
in [`Data_Dictionary.md`](Data_Dictionary.md)), since a single SQL FK cannot target three tables.

## 6. Relationships

### 6.1 Many-to-many (association tables)
| M2M | Association table | Notes |
|-----|-------------------|-------|
| role ↔ permission | `role_permission` | RBAC grants (FR-099/100). |
| (user \| service_account) ↔ organization | `membership` (carries `role_id`) | Org-level role assignment; principal XOR check. |
| user ↔ project | `project_member` (optional `role_id`) | Project scoping (FR-136). |
| api_key ↔ scope | `api_key_scope` | Inference-only scopes (FR-095). |
| routing_policy ↔ model | `routing_policy_rule` (carries priority/weight/condition) | Ordered candidates, fallback/weight/right-sizing (FR-039..041). |

### 6.2 One-to-many (representative)
organization→(everything tenant-scoped); provider→model→price_table; prompt_template→prompt_version;
routing_policy→routing_policy_rule; budget→reservation; billing_account→invoice; webhook→webhook_delivery;
session→refresh_token; semantic_cache_entry→embedding (1:1 optional).

### 6.3 Referential-integrity & delete semantics
- Tenant cascade: deleting an `organization` cascades to its owned rows (`ON DELETE CASCADE`) — used by
  tenant-deletion retention flow (FR-134), gated by retention policy.
- `role` referenced by `membership` uses `ON DELETE RESTRICT` (can't delete a role in use).
- Audit/ledger are **not** cascade-deleted casually — retention jobs handle them (see §archival).

## 7. Enum strategy

Native `ENUM` types are used for **small, stable** domains (status, period, provider type, modality,
etc.) for storage efficiency and validation. **RBAC uses lookup tables** (`role`, `permission`) because
the permission catalog and custom roles must be extensible as data (ADR-0008). Adding an enum value is a
migration (documented in [`Migration_Strategy.md`](Migration_Strategy.md)); adding a permission is a
data insert.

## 8. JSONB usage (every use justified)

JSONB is used **only** for genuinely open/semi-structured attributes that are not queried relationally
on the hot path:

| Column | Why JSONB (not columns) |
|--------|--------------------------|
| `organization.settings`, `configuration.value` | Open key/value config; schema varies per key. |
| `provider.config` | Per-provider timeouts/retries/concurrency (FR-029); provider-specific shape. |
| `model.metadata` | Provider-specific capability metadata; sparse/variable. |
| `routing_policy.constraints`, `routing_policy_rule.condition` | Declarative policy predicates (allowed providers/regions, right-sizing signals) — variable structure (FR-032/039). |
| `semantic_cache_entry.response` | The cached canonical response payload (document-shaped). |
| `prompt_version.variables` | Declared template variables list. |
| `budget.alert_thresholds` (array), `governance_policy.allowed_regions` (array) | Small ordered sets. |
| `audit_event.detail`, `notification.payload`, `background_job.payload`, `webhook_delivery.payload` | Event/document payloads, PII-scrubbed where applicable. |
| `feature_flag.rollout` | Targeting/percentage rules; variable. |

Relationally-important attributes (ids, status, amounts, scopes, timestamps) are **first-class
columns**, never buried in JSONB. GIN indexes on JSONB are added only where a documented query needs
them (see [`Indexing_Strategy.md`](Indexing_Strategy.md)).

## 9. pgvector usage (justified)

The single vector column is `embedding.vector vector(1024)` (**ADR-0006/0007**):
- **Why here:** semantic cache lookup needs approximate-nearest-neighbor search over prompt embeddings
  (FR-054..056), constrained by `organization_id` (isolation, FR-057).
- **Index:** HNSW with `vector_cosine_ops` (`ix_embedding_hnsw`) — meets the ≤40 ms semantic-lookup
  budget (NFR-P03) at expected volumes; HNSW chosen over IVFFlat for better recall/latency without a
  training step (see [`Indexing_Strategy.md`](Indexing_Strategy.md)).
- **Dimension:** `1024` is a placeholder finalized in Phase 8 (ADR-0007); it is model-dependent.
  Changing dimension is a **versioned migration** (new column/table + re-embed), never an in-place
  reinterpretation. `halfvec` is a future storage optimization option (documented, not default).
- **Isolation:** ANN queries always include `WHERE organization_id = :org` (+RLS); vectors carry
  `embedding_model`/`version` so cross-version matches are excluded (FR-058).

## 10. Seed-data strategy

Applied via migrations ([`Migration_Strategy.md`](Migration_Strategy.md)), idempotently:
- **Global reference data:** the `permission` catalog and **system `role`s** (`owner, admin, operator,
  finance, auditor, developer`) with their `role_permission` grants (the ADR-0008 matrix).
- **Per-tenant bootstrap (on org creation):** a default `governance_policy` (PII=redact, logging=hash),
  a default `routing_policy` (lowest_cost), and the org `owner` membership.
- **Self-host bootstrap:** the single organization, an initial admin user/service account, and
  `deployment_mode='self_hosted'`.
- Seed scripts are **environment-agnostic** and re-runnable (upserts keyed on natural keys).

## 11. Archival strategy

- **Hot → warm:** `usage_ledger` and `audit_event` monthly partitions stay hot for the online window
  (e.g., 3–12 months), then partitions are **detached and archived** (compressed export to object
  storage / cold schema) rather than row-deleted — fast, lock-light (see
  [`Partitioning_Strategy.md`](Partitioning_Strategy.md), [`Data_Retention.md`](Data_Retention.md)).
- **Rollups retained longer** than raw ledger (aggregates are small) to preserve analytics after raw
  archival.
- **Transient tables** (`reservation`, `provider_health`, `webhook_delivery`, `session`,
  `refresh_token`) are pruned on short cycles.
- Archived audit remains **immutable and hash-verifiable** for compliance retention windows.

## 12. Disaster-recovery considerations (data layer)

Aligned to **ADR-0010** and NFR-A05 (RTO ≤30 min, RPO ≤5 min):
- **Continuous archiving + PITR** (WAL) and periodic base backups; **cross-region streaming replica**
  per cell (home-region single-writer preserves budget atomicity).
- **RPO ≤5 min** via async replication lag targets; **RTO ≤30 min** via documented standby promotion.
- Partitioned append tables make restore/replay efficient; the Redis budget counters are
  **reconstructable** from `usage_ledger` (ADR-0004), so a Redis loss is recoverable without data loss.
- Full runbook: [`Backup_and_Recovery.md`](Backup_and_Recovery.md).

## 13. Validation summary (this phase)

Automated checks (see Phase-3 validation): every FK target exists and is defined before use (forward
refs resolved via deferred `ALTER TABLE`); no orphan tables (every table reachable from `organization`
or is global reference data — `permission`, global `role`/`feature_flag`/`configuration`, and the
append-only `audit_event` which references org logically); naming consistency (snake_case singular);
RLS enabled+forced on all tenant tables; indexes support documented access paths; partitioning applied
to the two high-volume append tables. Results reported with the phase summary.
