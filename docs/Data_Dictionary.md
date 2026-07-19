# Data Dictionary

**Phase:** 3 — Database Architecture · Draft for approval
**Last updated:** 2026-07-15

Per-table reference for all **41 tables**. For each: **Purpose · Relationships · PK · FK · Unique ·
Check · Indexes · Partition · Growth · Est. row volume · Retention**. Volumes assume large-enterprise
scale (thousands RPS, billions tokens/month, hundreds of tenants — NFR-S01..S05). Canonical DDL:
[`Schema.sql`](Schema.sql). Growth = qualitative trend; volume = steady-state order of magnitude.

Legend for Partition/Retention detail: see [`Partitioning_Strategy.md`](Partitioning_Strategy.md) and
[`Data_Retention.md`](Data_Retention.md).

---

## Domain 1 — Tenancy & Identity

### organization
- **Purpose:** Tenant / customer org; top-level isolation boundary (ADR-0002, FR-130).
- **Relationships:** Parent of virtually all tenant-owned tables (1→many).
- **PK:** `id`. **FK:** none. **Unique:** `slug`. **Check:** `slug` format regex.
- **Indexes:** PK; unique(slug). **Partition:** none.
- **Growth:** slow. **Volume:** 10²–10³ (hundreds of tenants). **Retention:** life of customer; soft-delete then purge per contract.

### app_user
- **Purpose:** Human user, scoped to one org (FR-090/131).
- **Relationships:** org 1→many; parent of `oauth_identity`, `session`, `membership`, `project_member`.
- **PK:** `id`. **FK:** `organization_id`→organization. **Unique:** (`organization_id`,`email`). **Check:** —.
- **Indexes:** `ix_app_user_org` (partial, not deleted). **Partition:** none.
- **Growth:** moderate. **Volume:** 10⁴–10⁵. **Retention:** life of account; soft-delete + purge (GDPR, NFR-C03).

### oauth_identity
- **Purpose:** Federated SSO identity → user (FR-092).
- **Relationships:** user 1→many.
- **PK:** `id`. **FK:** `organization_id`, `user_id`. **Unique:** (`provider`,`subject`). **Check:** —.
- **Indexes:** `ix_oauth_identity_user`. **Partition:** none.
- **Growth:** with users. **Volume:** 10⁴–10⁵. **Retention:** with user.

### oidc_login_state
- **Purpose:** Single-use OIDC login state (`state`/`nonce`/PKCE) held between /authorize and /callback (ADR-0015, FR-090/092).
- **Relationships:** org 1→many. No child tables; rows are transient.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** `state_hash`. **Check:** —.
- **Security:** `state_hash`/`nonce_hash` are SHA-256 — raw `state`/`nonce` are **never** stored. `code_verifier` is the only plaintext value (PKCE requires the original at token exchange); it is single-use, TTL-bounded, deleted on consume, and must never appear in logs/audit/metrics.
- **Consume semantics:** `DELETE ... RETURNING` — atomic single-use, so concurrent callbacks yield exactly one winner (replay detection).
- **Lifecycle:** `created_at`, `expires_at` (**TTL = 5 minutes**). Expired rows are treated as absent (fail closed) and swept every minute.
- **Indexes:** `ix_oidc_login_state_expires` (expiry sweep), unique `state_hash` (consume lookup). **Partition:** none.
- **Growth:** high churn, tiny steady state. **Volume:** ~concurrent logins. **Retention:** minutes — never long-lived.

### service_account_credential
- **Purpose:** Hashed client-credential for a service account; rotatable (ADR-0013, FR-098/097).
- **Relationships:** service_account 1→many.
- **PK:** `id`. **FK:** `organization_id`, `service_account_id`, `created_by`/`revoked_by`(→app_user). **Unique:** `client_id`. **Check:** —.
- **Lifecycle fields:** `created_at`,`updated_at`,`last_used_at`,`last_rotated_at`,`expires_at`,`revoked_at`,`rotation_reason` (audit/hygiene/compliance).
- **Indexes:** `ix_sa_credential_account` (partial active). **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of credential; keep revoked for audit.

### service_account
- **Purpose:** Machine principal for automation; RBAC-assignable (FR-098).
- **Relationships:** org 1→many; referenced by `membership`.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** (`organization_id`,`name`). **Check:** —.
- **Indexes:** `ix_service_account_org` (partial). **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of account.

### session
- **Purpose:** Authenticated admin session (FR-091).
- **Relationships:** user 1→many; parent of `refresh_token`.
- **PK:** `id`. **FK:** `organization_id`,`user_id`. **Unique:** —. **Check:** `expires_at > created_at`.
- **Indexes:** `ix_session_user`, `ix_session_expiry`. **Partition:** none (pruned).
- **Growth:** churns. **Volume:** 10⁴–10⁵ live. **Retention:** short — prune expired (e.g., 30 days).

### refresh_token
- **Purpose:** Rotating refresh token; only SHA-256 hash (FR-097, NFR-SEC03).
- **Relationships:** session 1→many; self-ref `rotated_to`.
- **PK:** `id`. **FK:** `organization_id`,`session_id`,`rotated_to`(self). **Unique:** `token_hash`. **Check:** —.
- **Indexes:** `ix_refresh_token_session`; unique(token_hash). **Partition:** none.
- **Growth:** churns. **Volume:** 10⁴–10⁵ live. **Retention:** until expiry+grace; prune.

## Domain 2 — RBAC

### role
- **Purpose:** Named RBAC role; system (NULL org) or custom (ADR-0008, FR-098).
- **Relationships:** →`role_permission`, →`membership`, →`project_member`.
- **PK:** `id`. **FK:** `organization_id` (nullable). **Unique:** (`organization_id`,`key`). **Check:** —.
- **Indexes:** PK; unique. **Partition:** none.
- **Growth:** static+. **Volume:** 10¹–10³. **Retention:** permanent (reference).

### permission
- **Purpose:** Fine-grained permission catalog (global reference).
- **Relationships:** →`role_permission`.
- **PK:** `id`. **FK:** none. **Unique:** `key`. **Check:** —.
- **Indexes:** PK; unique(key). **Partition:** none.
- **Growth:** static. **Volume:** 10¹–10². **Retention:** permanent.

### role_permission
- **Purpose:** M2M role↔permission (FR-099/100).
- **Relationships:** associative.
- **PK:** (`role_id`,`permission_id`). **FK:** both. **Unique:** PK. **Check:** —.
- **Indexes:** PK; `ix_role_permission_perm`. **Partition:** none.
- **Growth:** static+. **Volume:** 10²–10³. **Retention:** permanent.

### membership
- **Purpose:** Org-level role for user/service_account (FR-098).
- **Relationships:** org/user/sa/role.
- **PK:** `id`. **FK:** `organization_id`,`user_id`,`service_account_id`,`role_id`(RESTRICT). **Unique:** (org,user,role),(org,sa,role). **Check:** exactly-one-principal.
- **Indexes:** `ix_membership_org`, `ix_membership_user`. **Partition:** none.
- **Growth:** with users. **Volume:** 10⁴–10⁵. **Retention:** life of membership.

## Domain 3 — Projects & Access

### project
- **Purpose:** Mid-tier grouping (org→project→key) (DB-DEC-02, FR-135).
- **Relationships:** org 1→many; →`project_member`,`api_key`,`routing_policy`,`budget` scope.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** (`organization_id`,`slug`). **Check:** —.
- **Indexes:** `ix_project_org` (partial). **Partition:** none.
- **Growth:** moderate. **Volume:** 10³–10⁴. **Retention:** life of project; soft-delete.

### project_member
- **Purpose:** M2M user↔project (FR-136).
- **Relationships:** associative.
- **PK:** (`project_id`,`user_id`). **FK:** project,user,role,organization. **Unique:** PK. **Check:** —.
- **Indexes:** PK; `ix_project_member_user`. **Partition:** none.
- **Growth:** with users. **Volume:** 10⁴–10⁵. **Retention:** with membership.

### api_key
- **Purpose:** Virtual key for inference; SHA-256 hash only (FR-094..097).
- **Relationships:** org/project 1→many; →`api_key_scope`,`reservation`.
- **PK:** `id`. **FK:** `organization_id`,`project_id`,`created_by`. **Unique:** `key_hash`,`key_prefix`. **Check:** —.
- **Indexes:** `ix_api_key_org_project` (partial active). **Partition:** none.
- **Growth:** moderate. **Volume:** 10⁴–10⁵. **Retention:** until revoked+audit window.

### api_key_scope
- **Purpose:** M2M key↔scope; inference-only (FR-095).
- **Relationships:** associative.
- **PK:** (`api_key_id`,`scope`). **FK:** api_key,organization. **Unique:** PK. **Check:** —.
- **Indexes:** PK; `ix_api_key_scope_org`. **Partition:** none.
- **Growth:** with keys. **Volume:** 10⁴–10⁵. **Retention:** with key.

## Domain 4 — Providers, Models, Registry

### provider
- **Purpose:** Per-org provider config; credentials referenced (ADR-0003/0011, FR-020/022).
- **Relationships:** org 1→many; →`model`,`provider_health`; →`secret_reference`.
- **PK:** `id`. **FK:** `organization_id`,`credential_secret_ref`(deferred). **Unique:** (`organization_id`,`name`). **Check:** —.
- **Indexes:** `ix_provider_org` (partial enabled). **Partition:** none.
- **Growth:** slow. **Volume:** 10²–10³. **Retention:** life of config.

### model
- **Purpose:** Model registry entry; capability/tier; runtime enable (FR-021/028).
- **Relationships:** provider 1→many; →`price_table`,`routing_policy_rule`,`semantic_cache_entry`.
- **PK:** `id`. **FK:** `organization_id`,`provider_id`. **Unique:** (`provider_id`,`name`),(`organization_id`,`alias`). **Check:** —.
- **Indexes:** `ix_model_org`(partial), `ix_model_provider`. **Partition:** none.
- **Growth:** slow. **Volume:** 10³. **Retention:** life of config.

### price_table
- **Purpose:** Effective-dated pricing per model (FR-074/075, SM-T07).
- **Relationships:** model 1→many.
- **PK:** `id`. **FK:** `organization_id`,`model_id`. **Unique:** (`model_id`,`effective_from`). **Check:** non-negative prices; effective range.
- **Indexes:** `ix_price_table_model_current` (model_id, effective_from DESC). **Partition:** none.
- **Growth:** slow (append on price change). **Volume:** 10³–10⁴. **Retention:** permanent (historical cost).

### provider_health
- **Purpose:** Health/circuit-breaker snapshots (FR-037/038).
- **Relationships:** provider/model 1→many.
- **PK:** `id`. **FK:** `organization_id`,`provider_id`,`model_id`. **Unique:** —. **Check:** success_rate 0..1.
- **Indexes:** `ix_provider_health_provider` (provider_id, observed_at DESC). **Partition:** none (rolling prune).
- **Growth:** high churn. **Volume:** 10⁶ rolling. **Retention:** short (e.g., 7–30 days).

## Domain 5 — Routing & Prompts

### routing_policy
- **Purpose:** Declarative routing policy per org/project (ADR-0012, FR-030).
- **Relationships:** org/project 1→many; →`routing_policy_rule`.
- **PK:** `id`. **FK:** `organization_id`,`project_id`. **Unique:** (`organization_id`,`name`). **Check:** —.
- **Indexes:** `ix_routing_policy_org` (partial active). **Partition:** none.
- **Growth:** slow. **Volume:** 10²–10³. **Retention:** life of config.

### routing_policy_rule
- **Purpose:** Ordered candidates (fallback/weight/right-sizing) (FR-039..041).
- **Relationships:** policy 1→many; model ref (M2M policy↔model).
- **PK:** `id`. **FK:** `organization_id`,`routing_policy_id`,`model_id`. **Unique:** (`routing_policy_id`,`priority`). **Check:** weight ≥ 0.
- **Indexes:** `ix_routing_rule_policy` (policy, priority). **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of config.

### prompt_template
- **Purpose:** Named server-side template; versions feed cache keys (FR-058).
- **Relationships:** org/project 1→many; →`prompt_version`.
- **PK:** `id`. **FK:** `organization_id`,`project_id`,`created_by`. **Unique:** (`organization_id`,`name`). **Check:** —.
- **Indexes:** `ix_prompt_template_org`. **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of template.

### prompt_version
- **Purpose:** Immutable versioned prompt content (FR-058).
- **Relationships:** template 1→many.
- **PK:** `id`. **FK:** `organization_id`,`prompt_template_id`,`created_by`. **Unique:** (`prompt_template_id`,`version`). **Check:** —.
- **Indexes:** `ix_prompt_version_template` (template, version DESC). **Partition:** none.
- **Growth:** moderate (append). **Volume:** 10⁴–10⁵. **Retention:** permanent (audit/repro).

## Domain 6 — Cache & Embeddings

### embedding
- **Purpose:** Tenant-scoped vectors for semantic cache (ADR-0006/0007, FR-054).
- **Relationships:** org 1→many; 1→1 optional with `semantic_cache_entry`.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** —. **Check:** —.
- **Indexes:** `ix_embedding_hnsw` (HNSW cosine), `ix_embedding_org`. **Partition:** none (candidate for future per-tenant/model partition — see Partitioning_Strategy).
- **Growth:** high. **Volume:** 10⁶–10⁸ vectors. **Retention:** tied to cache entry / TTL / model version.

### semantic_cache_entry
- **Purpose:** Exact+semantic cache (FR-050..058).
- **Relationships:** org/project 1→many; →`embedding`(optional),`model`.
- **PK:** `id`. **FK:** `organization_id`,`project_id`,`model_id`,`embedding_id`. **Unique:** (`organization_id`,`request_hash`). **Check:** —.
- **Indexes:** `ix_semantic_cache_org`, `ix_semantic_cache_expiry`. **Partition:** none (TTL prune).
- **Growth:** high. **Volume:** 10⁶–10⁷. **Retention:** TTL/policy (FR-058); prune expired.

## Domain 7 — Cost, Ledger, Usage, Billing

### budget
- **Purpose:** Hierarchical budget org/project/key (ADR-0004, FR-060..067).
- **Relationships:** org 1→many; →`reservation`.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** (org,scope,scope_id,period,period_start). **Check:** amount ≥ 0; period order.
- **Indexes:** `ix_budget_scope` (partial active). **Partition:** none.
- **Growth:** moderate. **Volume:** 10³–10⁴. **Retention:** current + history for reporting.

### reservation
- **Purpose:** Durable mirror of Redis reserve for reconciliation (ADR-0004, DB-DEC-03).
- **Relationships:** budget/api_key 1→many; →`usage_ledger`.
- **PK:** `id`. **FK:** `organization_id`,`budget_id`,`api_key_id`. **Unique:** `request_id`. **Check:** costs ≥ 0.
- **Indexes:** `ix_reservation_status` (status,expires_at), `ix_reservation_budget`. **Partition:** none (high churn; short retention).
- **Growth:** very high churn. **Volume:** 10⁷ rolling. **Retention:** short — settle+reconcile then prune (e.g., 7–30 days).

### usage_ledger  ⟨PARTITIONED monthly⟩
- **Purpose:** Append-only double-entry usage/cost system of record (FR-070..073, NFR-S05).
- **Relationships:** org 1→many; refs project/api_key/provider/model/reservation (soft, no cascade).
- **PK:** (`id`,`created_at`). **FK:** `organization_id`. **Unique:** PK. **Check:** tokens ≥ 0; cost ≥ 0.
- **Indexes:** `ix_usage_ledger_org_time`, `ix_usage_ledger_request`. **Partition:** RANGE(`created_at`) monthly (justified: NFR-S05 volume, time-window queries, cheap archival).
- **Growth:** very high (hot). **Volume:** ~10⁹/month (billions). **Retention:** hot 3–12 months → archive partitions; rollups retained longer.

### usage_rollup
- **Purpose:** Denormalized daily aggregates for analytics (FR-086).
- **Relationships:** org 1→many (derived from ledger).
- **PK:** `id`. **FK:** `organization_id`. **Unique:** (org,project,model,bucket_date). **Check:** —.
- **Indexes:** `ix_usage_rollup_lookup` (org, bucket_date DESC). **Partition:** none (small).
- **Growth:** moderate. **Volume:** 10⁶–10⁷. **Retention:** long (analytics), longer than raw ledger.

### billing_account
- **Purpose:** Billing linkage; external ref only, no card/PAN (v1 billing external).
- **Relationships:** org 1→1; →`invoice`.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** `organization_id`. **Check:** —.
- **Indexes:** PK; unique(org). **Partition:** none.
- **Growth:** slow. **Volume:** 10²–10³. **Retention:** life of customer.

### invoice
- **Purpose:** Periodic invoice from rollups.
- **Relationships:** billing_account 1→many.
- **PK:** `id`. **FK:** `organization_id`,`billing_account_id`. **Unique:** (account,period_start,period_end). **Check:** period order.
- **Indexes:** `ix_invoice_account` (account, period_start DESC). **Partition:** none.
- **Growth:** slow. **Volume:** 10⁴–10⁵. **Retention:** long (financial records, e.g., 7 yrs).

### rate_limit_policy
- **Purpose:** Per-scope rate/quota config of record (FR-064/065).
- **Relationships:** org 1→many.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** (org,scope,scope_id,period). **Check:** non-negative limits.
- **Indexes:** `ix_rate_limit_scope` (partial active). **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of config.

## Domain 8 — Governance & Ops

### audit_event  ⟨PARTITIONED monthly, append-only, hash-chained⟩
- **Purpose:** Immutable audit log (ADR-0009, FR-113/114, NFR-SEC09).
- **Relationships:** org (logical FK).
- **PK:** (`id`,`created_at`). **FK:** none enforced (append-only; org logical). **Unique:** PK. **Check:** —.
- **Indexes:** `ix_audit_event_org_time`, `ix_audit_event_action`. **Partition:** RANGE(`created_at`) monthly (justified: volume + time-window compliance queries + archival).
- **Growth:** high. **Volume:** 10⁷–10⁸/month. **Retention:** long compliance window (e.g., 1–7 yrs) then archive; never mutate.

### governance_policy
- **Purpose:** Per-org/project PII/residency/logging/cache toggle (FR-110..118).
- **Relationships:** org/project 1→many.
- **PK:** `id`. **FK:** `organization_id`,`project_id`. **Unique:** (`organization_id`,`project_id`). **Check:** —.
- **Indexes:** `ix_governance_policy_org`. **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of config.

### feature_flag
- **Purpose:** Flags, global (NULL org) or per-org.
- **Relationships:** org (nullable) 1→many.
- **PK:** `id`. **FK:** `organization_id` (nullable). **Unique:** (`organization_id`,`key`). **Check:** —.
- **Indexes:** `ix_feature_flag_key`. **Partition:** none.
- **Growth:** slow. **Volume:** 10²–10³. **Retention:** life of feature.

### notification
- **Purpose:** Outbound notifications w/ status (FR-066/085).
- **Relationships:** org 1→many.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** —. **Check:** —.
- **Indexes:** `ix_notification_org_status`. **Partition:** none (prune).
- **Growth:** moderate. **Volume:** 10⁶ rolling. **Retention:** short (e.g., 90 days).

### background_job
- **Purpose:** Durable worker-job tracking w/ retries/DLQ (ADR-0005).
- **Relationships:** org (nullable) 1→many.
- **PK:** `id`. **FK:** `organization_id` (nullable). **Unique:** —. **Check:** attempts ≤ max_attempts.
- **Indexes:** `ix_background_job_poll` (partial queued/failed). **Partition:** none (prune succeeded).
- **Growth:** high churn. **Volume:** 10⁶–10⁷ rolling. **Retention:** short for succeeded; keep dead_letter longer.

### configuration
- **Purpose:** Typed config (org or global); non-secret.
- **Relationships:** org (nullable) 1→many.
- **PK:** `id`. **FK:** `organization_id` (nullable),`updated_by`. **Unique:** (`organization_id`,`key`). **Check:** —.
- **Indexes:** `ix_configuration_org`. **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of config.

### secret_reference
- **Purpose:** Pointer to external secret; **no values** (ADR-0011, NFR-SEC03).
- **Relationships:** org 1→many; referenced by `provider`,`webhook`.
- **PK:** `id`. **FK:** `organization_id`. **Unique:** (`organization_id`,`name`). **Check:** path length guard.
- **Indexes:** `ix_secret_reference_org`. **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of secret; audit on rotation.

### webhook
- **Purpose:** Outbound webhook subscription; signing secret referenced (ADR-0011).
- **Relationships:** org 1→many; →`webhook_delivery`; →`secret_reference`.
- **PK:** `id`. **FK:** `organization_id`,`secret_ref`. **Unique:** —. **Check:** URL is https.
- **Indexes:** `ix_webhook_org` (partial active). **Partition:** none.
- **Growth:** slow. **Volume:** 10³–10⁴. **Retention:** life of subscription.

### webhook_delivery
- **Purpose:** Per-attempt delivery record w/ retry/DLQ.
- **Relationships:** webhook 1→many.
- **PK:** `id`. **FK:** `organization_id`,`webhook_id`. **Unique:** —. **Check:** attempts ≥ 0.
- **Indexes:** `ix_webhook_delivery_hook` (webhook, created_at DESC). **Partition:** none (prune; candidate for partition if volume grows).
- **Growth:** high churn. **Volume:** 10⁶–10⁷ rolling. **Retention:** short (e.g., 30–90 days).

---

## Coverage
All 41 tables from [`Schema.sql`](Schema.sql) are documented above. Every table has a defined PK; every
FK targets an existing table (forward ref `provider.credential_secret_ref` resolved via deferred
`ALTER TABLE`); tenant-owned tables carry `organization_id` with RLS
([`RLS_Strategy.md`](RLS_Strategy.md)). Global reference tables (`permission`, system `role`, NULL-org
`feature_flag`/`configuration`) and the append-only `audit_event` are the documented exceptions to
tenant FK cascade.
