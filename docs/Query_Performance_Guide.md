# Query Performance Guide

**Phase:** 3 — Database Architecture (governance artifact) · Draft for approval
**Last updated:** 2026-07-15

Performance expectations and guidance for the database layer. **Documents and strengthens** the
approved schema; **changes nothing**. It defines the query patterns each phase must design to, so the
indexes ([`Indexing_Strategy.md`](Indexing_Strategy.md)) and partitions
([`Partitioning_Strategy.md`](Partitioning_Strategy.md)) are used correctly and the latency budgets
(NFR-P01..P06) hold at large-enterprise scale.

## 1. Hot vs. cold tables

| Class | Tables | Access |
|-------|--------|--------|
| **Hot — read (per request)** | `api_key` (validate), `governance_policy`, `budget`, `provider`/`model`/`price_table` (current), `semantic_cache_entry` (exact), `embedding` (ANN) | Point lookups + ANN on the inference hot path |
| **Hot — write (per request/async)** | `usage_ledger` (append), `reservation` (insert/settle), `audit_event` (append), `provider_health` (upsert) | High-rate inserts; mostly via workers |
| **Warm** | `usage_rollup`, `routing_policy`/`routing_policy_rule`, `prompt_*`, `notification`, `background_job` | Periodic reads/writes |
| **Cold — config/registry** | `organization`, `app_user`, `role`/`permission`/`membership`, `project`, `billing_account`, `invoice`, `rate_limit_policy`, `feature_flag`, `configuration`, `secret_reference`, `webhook` | Infrequent CRUD, cached in app |

Design implication: **hot reads must be O(1)/index-only**; **hot writes must avoid extra indexes and
synchronous cross-table work** (that's why metering is async — ADR-0004/0005).

## 2. Read/write ratio expectations

| Table | R:W (approx) | Notes |
|-------|--------------|-------|
| `api_key` | very read-heavy | 1 indexed read per inference; writes rare (issue/revoke). Cache validated keys in app/Redis. |
| `semantic_cache_entry` | read-heavy | exact lookup per request; writes on population (async). |
| `embedding` | read-heavy | ANN per semantic candidate; inserts async. |
| `usage_ledger` | **write-heavy (append)** | ~1+ insert/request (double-entry), reads for analytics/reconcile. |
| `reservation` | write-heavy churn | insert + settle per request; short-lived. |
| `audit_event` | write-heavy (append) | many inserts; reads on demand (compliance). |
| `budget` | read-heavy | read on reserve; writes on config/period reset. |
| config/registry tables | read-heavy, tiny | app-cached with short TTL + invalidation on change. |

## 3. Expected query patterns (and the index that serves each)

| Pattern | SQL shape | Index | Budget |
|---------|-----------|-------|--------|
| Validate virtual key | `WHERE key_hash = $1` (+ status) | unique(`key_hash`) | ≤2 ms (NFR-P05 path) |
| Exact cache hit | `WHERE organization_id=$1 AND request_hash=$2` | unique(`org`,`request_hash`) | ≤25 ms E2E (NFR-P02) |
| Semantic ANN | `WHERE organization_id=$1 AND embedding_version=$2 ORDER BY vector <=> $q LIMIT k` | `ix_embedding_hnsw` + `ix_embedding_org` | ≤40 ms (NFR-P03) |
| Current price | `WHERE model_id=$1 AND effective_from<=now() ORDER BY effective_from DESC LIMIT 1` | `ix_price_table_model_current` | ≤2 ms |
| Resolve budgets for reserve | `WHERE organization_id=$1 AND scope IN(...) AND scope_id IN(...) AND is_active` | `ix_budget_scope` (partial) | ≤5 ms (enforcement is Redis; DB warms cache) |
| Principal permissions (authz) | join `membership`→`role_permission`→`permission` | `ix_membership_user`, `ix_role_permission_perm` | cached per session |
| Usage over time window | `WHERE organization_id=$1 AND created_at >= $2 [AND < $3]` | partition prune + `ix_usage_ledger_org_time` | analytics (async) |
| Audit browse/export | `WHERE organization_id=$1 [AND action=$2] AND created_at BETWEEN ...` | partition prune + `ix_audit_event_action` | on-demand |
| Worker job poll | `WHERE status IN('queued','failed') AND available_at<=now() ORDER BY available_at` | `ix_background_job_poll` (partial) | frequent, small |

Rule: **every hot query must filter by `organization_id`** (RLS also enforces it) and hit a listed
index. New hot queries require an index justification appended to
[`Indexing_Strategy.md`](Indexing_Strategy.md).

## 4. Expected growth (drives partition/archival)
- `usage_ledger`: ~10⁹ rows/month (billions of tokens → many metered requests) — **monthly partitions +
  archive** (NFR-S04/S05).
- `audit_event`: 10⁷–10⁸/month — monthly partitions, long retention.
- `embedding`/`semantic_cache_entry`: 10⁶–10⁸ vectors / 10⁶–10⁷ entries — bounded by TTL + purge.
- `reservation`, `provider_health`, `notification`, `background_job`, `webhook_delivery`: high churn,
  bounded by short retention/prune.
- Config/registry/identity: ≤10⁵ — negligible growth.
Full figures: [`Data_Dictionary.md`](Data_Dictionary.md).

## 5. Index strategy (summary)
Tenant-leading, partial for active/enabled/not-deleted, descending-time for latest-N, minimal indexes
on hot append tables, HNSW for vectors. Full rationale per index:
[`Indexing_Strategy.md`](Indexing_Strategy.md).

## 6. Pagination strategy
- **Keyset (seek) pagination** is the default for large/append lists (`usage_ledger`, `audit_event`,
  usage views): `WHERE (created_at, id) < ($cursor_ts, $cursor_id) ORDER BY created_at DESC, id DESC
  LIMIT $n`. Stable under inserts, O(n) not O(offset).
- **OFFSET/LIMIT is disallowed** on hot/large tables (deep offsets scan). Small config lists may use it.
- API responses return an **opaque cursor** (encodes `created_at`+`id`); documented in Phase 4 OpenAPI.

## 7. Full-text search strategy
- Not on the hot path. Where admin search is needed (e.g., searching prompts/templates or audit
  actions), use PostgreSQL **`tsvector` + GIN** on the specific column, added in the owning phase with
  justification — **not** created by default. Semantic similarity over prompts is handled by the
  **vector** path, not FTS.

## 8. Vector search strategy (pgvector) — ADR-0006/0007
- **HNSW, cosine** (`ix_embedding_hnsw`). Query: tenant + version filter, then `ORDER BY vector <=> $q
  LIMIT k`, then apply the per-policy similarity threshold in app (record score — FR-056).
- **Tenant isolation:** ANN always runs under RLS + `organization_id` filter — no cross-tenant search
  (FR-057).
- **Tuning knobs:** `hnsw.ef_search` (recall/latency trade-off) set per query class; index build uses
  raised `maintenance_work_mem`. Monitor recall + p99 against NFR-P03.
- **Scale escalation:** if per-tenant vector volume threatens the budget, hash-partition `embedding` by
  `organization_id` (or move to a dedicated vector store behind the cache port — ADR-0006 review note).
- **Dimension** fixed at `vector(1024)` (placeholder, ADR-0007); changes are versioned re-embeds.

## 9. Join strategy
- **Keep hot-path joins shallow.** The inference path does mostly **point lookups**, not multi-join
  queries; registry/policy/budget data is small and **app-cached** to avoid per-request joins.
- Multi-table joins live in **admin/analytics** paths (warm/cold), where planner cost is acceptable and
  read replicas absorb load.
- Join keys are always **indexed FKs**; tenant filter first to shrink the working set (helped by
  tenant-leading indexes).
- Avoid joining across the huge `usage_ledger` at request time — analytics reads use `usage_rollup`.

## 10. Transaction boundaries
- **One transaction per request use-case**, kept **short**; the tenant context is `SET LOCAL` inside it
  (RLS — [`RLS_Strategy.md`](RLS_Strategy.md)).
- **No provider/network call inside a DB transaction** — the provider call happens **outside** any open
  transaction to avoid holding locks/connections during multi-hundred-ms model latency.
- **Reserve/commit** deliberately spans **two** short units: sync reserve (Redis, ≤5 ms) and async
  commit (worker writes ledger) — never one long transaction around the provider call (ADR-0004).
- Workers process events in **idempotent, per-event** transactions (dedupe by id) so retries are safe.
- Batch writes (rollups, ledger flush) use **bounded batch sizes** to cap lock duration and WAL spikes.

## 11. Locking considerations
- Append tables (`usage_ledger`, `audit_event`) are **insert-only** → no row-update contention; UUIDv7
  keys keep index inserts local (less page contention).
- **Budget enforcement contention is offloaded to Redis** (atomic Lua) — the DB is not the concurrency
  point for reserve (ADR-0004), avoiding hot-row lock storms on popular tenants (RISK-T03).
- Config updates are low-frequency; use normal row locks. Avoid `SELECT ... FOR UPDATE` on hot paths.
- DDL (partitions, indexes) uses **`CONCURRENTLY`/`DETACH ... CONCURRENTLY`** and low-traffic windows to
  avoid long `ACCESS EXCLUSIVE` locks ([`Migration_Strategy.md`](Migration_Strategy.md)).
- `autovacuum` tuned for high-churn tables (`reservation`, `provider_health`, `background_job`) to
  control bloat.

## 12. Connection pooling assumptions
- App connects through a **pooler** (PgBouncer or equivalent), **transaction-pooling** mode — matches
  the short-transaction model and the `SET LOCAL` tenant context (safe because it resets per
  transaction).
- Implication: **no session-level state** relied upon across transactions (no `SET` without `LOCAL`, no
  server-side prepared-statement assumptions incompatible with transaction pooling — driver configured
  accordingly).
- Pool sizing: sized to `max_connections` with headroom for workers, reconciler, and replicas; API and
  worker pools are **separate** so batch jobs can't starve the request path.
- Read replicas serve analytics/rollup/audit-export reads to protect the primary's write throughput.

## 13. Future optimization opportunities
- **Sub-partition** `usage_ledger` by `organization_id` (hash) if a single month is too large.
- **`halfvec`** storage for embeddings to cut vector storage/memory (ADR-0007 note) once dimension is
  finalized.
- **Materialized views** for common dashboard aggregates if `usage_rollup` grows heavy.
- **Partial/covering indexes** added only where Phase-13 `pg_stat_statements` proves a hot query needs
  them; drop unused indexes.
- **Table compression / columnar** (e.g., TimescaleDB or native) for archived usage if analytical scan
  volume justifies it.
- **Dedicated vector store** behind the cache port only if pgvector misses NFR-P03 at production scale.
- **Read-replica routing** per query class as read volume grows.

## 14. Verification (Phase 13)
Load tests validate: key-validation & cache-hit latency (NFR-P02/P05), ANN latency/recall (NFR-P03),
ledger insert throughput (NFR-S05), keyset pagination stability, and that no hot query does a seq scan
or deep offset. Results feed back into [`Indexing_Strategy.md`](Indexing_Strategy.md).
