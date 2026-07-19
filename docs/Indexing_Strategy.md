# Indexing Strategy

**Phase:** 3 — Database Architecture · Draft for approval
**Last updated:** 2026-07-15

Every index in [`Schema.sql`](Schema.sql) is justified by a concrete access path. Principle: index for
the **tenant-scoped read patterns** the application actually issues, keep write amplification low on
hot tables, and prefer **partial** and **covering-leading-column** indexes over broad ones.

## 1. Principles
- **Tenant-leading:** most indexes lead with `organization_id` because RLS + queries always filter by
  tenant (ADR-0002). This also aids locality.
- **Partial indexes** (`WHERE ...`) for "active/enabled/not-deleted" rows to shrink index size and skip
  soft-deleted/inactive rows on the hot path.
- **Descending time** (`created_at DESC`, `effective_from DESC`) for "latest N" and time-window reads.
- **Hot append tables** (`usage_ledger`, `audit_event`, `reservation`) carry the **minimum** indexes
  needed, to protect insert throughput (NFR-S05).
- **UUIDv7 app-side** on hot tables to keep B-tree inserts near-sequential (see Database_Design §2).

## 2. Index catalog & justification

| Index | Table (cols) | Type | Serves | Requirement |
|-------|--------------|------|--------|-------------|
| PKs | all `(id)` / composite on partitioned | B-tree unique | Entity fetch, FK integrity | — |
| `ix_app_user_org` | app_user(org) WHERE not deleted | partial | List/lookup users in a tenant | FR-131 |
| `ix_oauth_identity_user` | oauth_identity(user_id) | B-tree | Resolve SSO → user on login | FR-092 |
| `ix_service_account_org` | service_account(org) partial | partial | List SAs | FR-098 |
| `ix_session_user` | session(user_id) | B-tree | User's sessions | FR-091 |
| `ix_session_expiry` | session(expires_at) | B-tree | Prune expired sessions | retention |
| `ix_refresh_token_session` | refresh_token(session_id) | B-tree | Rotate/revoke tokens in a session | FR-091 |
| unique(token_hash) | refresh_token | unique | O(1) token validation | FR-097 |
| `ix_membership_org` / `_user` | membership | B-tree | Resolve a principal's roles (authz) | FR-098/099 |
| `ix_role_permission_perm` | role_permission(permission_id) | B-tree | "who has permission X" | FR-100 |
| `ix_project_org` | project(org) partial | partial | List projects | FR-135 |
| `ix_project_member_user` | project_member(user_id) | B-tree | User's projects | FR-136 |
| `ix_api_key_org_project` | api_key(org,project) WHERE active | partial | Manage/list active keys | FR-094 |
| unique(key_hash),(key_prefix) | api_key | unique | **Key validation on every inference request** (hot) | FR-097 |
| `ix_api_key_scope_org` | api_key_scope(org) | B-tree | Scope checks | FR-095 |
| `ix_provider_org` | provider(org) WHERE enabled | partial | Registry read for routing | FR-020/028 |
| `ix_model_org` / `_provider` | model | partial/B-tree | Resolve alias→model; provider's models | FR-021/005 |
| `ix_price_table_model_current` | price_table(model, effective_from DESC) | B-tree | **Current price lookup** on cost calc (hot) | FR-071/074 |
| `ix_provider_health_provider` | provider_health(provider, observed_at DESC) | B-tree | Latest health for circuit breaker | FR-037/038 |
| `ix_routing_policy_org` | routing_policy(org) WHERE active | partial | Load active policy | FR-030 |
| `ix_routing_rule_policy` | routing_policy_rule(policy, priority) | B-tree | Ordered candidate evaluation | FR-040 |
| `ix_prompt_template_org` | prompt_template(org) | B-tree | List templates | FR-058 |
| `ix_prompt_version_template` | prompt_version(template, version DESC) | B-tree | Latest/pinned version | FR-058 |
| `ix_semantic_cache_org` | semantic_cache_entry(org) | B-tree | Tenant cache scans/admin | FR-057 |
| unique(org, request_hash) | semantic_cache_entry | unique | **Exact-cache O(1) lookup** (hot) | FR-050 |
| `ix_semantic_cache_expiry` | semantic_cache_entry(expires_at) | B-tree | TTL prune | FR-058 |
| **`ix_embedding_hnsw`** | embedding USING hnsw(vector cosine) | **HNSW** | **Semantic ANN search** | FR-054, NFR-P03 |
| `ix_embedding_org` | embedding(org) | B-tree | Tenant filter pre/post ANN | FR-057 |
| `ix_budget_scope` | budget(org,scope,scope_id) WHERE active | partial | Resolve budgets for reserve | FR-060/062 |
| `ix_reservation_status` | reservation(status, expires_at) | B-tree | Reconciler sweep of open/expired | ADR-0004 |
| `ix_reservation_budget` | reservation(budget_id) | B-tree | Reconcile per budget | ADR-0004 |
| `ix_usage_ledger_org_time` | usage_ledger(org, created_at DESC) | B-tree (per partition) | Tenant usage/time-window queries | FR-070/086 |
| `ix_usage_ledger_request` | usage_ledger(request_id) | B-tree | Trace/reconcile by request | FR-072 |
| `ix_usage_rollup_lookup` | usage_rollup(org, bucket_date DESC) | B-tree | Dashboard aggregates | FR-086 |
| `ix_invoice_account` | invoice(account, period_start DESC) | B-tree | Billing history | billing |
| `ix_rate_limit_scope` | rate_limit_policy(org,scope,scope_id) WHERE active | partial | Load limits | FR-064 |
| `ix_audit_event_org_time` | audit_event(org, created_at DESC) | B-tree (per partition) | Audit browse/export | FR-115 |
| `ix_audit_event_action` | audit_event(org, action, created_at DESC) | B-tree | Filter by action | FR-115 |
| `ix_governance_policy_org` | governance_policy(org) | B-tree | Load policy on request | FR-110 |
| `ix_feature_flag_key` | feature_flag(key) | B-tree | Flag lookup | — |
| `ix_notification_org_status` | notification(org,status) | B-tree | Deliver pending | FR-066 |
| `ix_background_job_poll` | background_job(status,available_at) WHERE queued/failed | partial | **Worker job polling** | ADR-0005 |
| `ix_configuration_org` | configuration(org) | B-tree | Config load | — |
| `ix_secret_reference_org` | secret_reference(org) | B-tree | Resolve credential ref | ADR-0011 |
| `ix_webhook_org` | webhook(org) WHERE active | partial | Dispatch | — |
| `ix_webhook_delivery_hook` | webhook_delivery(webhook, created_at DESC) | B-tree | Delivery history/retry | — |

## 3. Vector index (pgvector) detail
- **`ix_embedding_hnsw`**: HNSW over `vector_cosine_ops`. **HNSW vs IVFFlat:** HNSW gives high recall +
  low latency without a training/`lists` tuning step and handles incremental inserts well — better fit
  for a continuously-populated cache than IVFFlat. Meets NFR-P03 (≤40 ms lookup) at expected volumes.
- **Tenant filtering:** ANN is combined with `organization_id` filtering (and `embedding_version`) —
  see [`RLS_Strategy.md`](RLS_Strategy.md) for how RLS + the `ix_embedding_org` btree bound the search
  to a tenant. If per-tenant vector counts grow very large, partitioning `embedding` by tenant/hash is
  the escalation path ([`Partitioning_Strategy.md`](Partitioning_Strategy.md)).
- **Maintenance:** HNSW build/insert cost is monitored; `maintenance_work_mem` tuned for index build.

## 4. JSONB indexing
No JSONB GIN indexes are created by default (JSONB columns are not queried relationally on the hot
path — Database_Design §8). If a documented query later needs to filter inside a JSONB column (e.g.,
`routing_policy.constraints`), a targeted **GIN** (or expression btree on a specific path) is added in
that phase, with justification appended here.

## 5. Write-amplification guardrails
- Hot append tables kept to ≤2 secondary indexes.
- Partial indexes exclude inactive/deleted rows to shrink hot indexes.
- Composite uniques double as lookup indexes (no redundant single-column duplicates).
- Index additions post-GA use `CREATE INDEX CONCURRENTLY` (see [`Migration_Strategy.md`](Migration_Strategy.md)).

## 6. Review triggers
Re-evaluate with `pg_stat_statements` and index-usage stats after Phase 13 load tests; drop unused
indexes, add covering indexes only where a hot query proves the need.
