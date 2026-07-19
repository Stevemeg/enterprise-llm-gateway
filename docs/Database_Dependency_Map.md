# Database Dependency Map

**Phase:** 3 — Database Architecture (governance artifact) · Draft for approval
**Last updated:** 2026-07-15

Maps **every one of the 40 tables** to its ADRs, requirements, owning subsystem, parent/child tables,
referencing APIs, future backend modules, retention, RLS policy, and audit requirements. This is the
**implementation roadmap for the database layer** — it documents the approved schema and **changes
nothing**. Topology (parents/children) is derived from the FK graph in [`Schema.sql`](Schema.sql).

## Legend
- **Parents** = tables this one references (FK out). **Children** = tables that reference this one (FK in).
- **APIs** = surfaces that read/write it (see [`System_Context.md`](System_Context.md) §8; `/v1/*` =
  public inference, `/admin/...` = control plane, `/auth/*`, `ops`).
- **Future module** = backend package that will own it (Phases 5–9; see
  [`Architecture_Implementation_Map.md`](Architecture_Implementation_Map.md)).
- **Retention** = class from [`Data_Retention.md`](Data_Retention.md).
- **RLS** = policy from [`RLS_Strategy.md`](RLS_Strategy.md) (`<table>_tenant_isolation`, or *global* /
  *logical*).
- **Audit** = what must be written to `audit_event`: *config-change* (admin CRUD audited),
  *security* (auth/keys/permissions), *none-runtime* (hot-path data, not itself audited), *self* (the
  audit log).

---

## Domain 1 — Tenancy & Identity  (subsystem: Multi-Tenancy / Authentication; ADR-0002/0008)

| Table | ADRs | FR | NFR | Parents | Children | APIs | Future module | Retention | RLS | Audit |
|-------|------|----|-----|---------|----------|------|---------------|-----------|-----|-------|
| organization | 0002,0010,0011 | 130-134 | SEC07,S03,D01 | — | (all tenant tables) | /admin/tenants | tenancy | Permanent | *root* (owns context) | config-change |
| app_user | 0008 | 090,131 | SEC05 | organization | oauth_identity, session, membership, project_member, prompt_template, prompt_version, configuration | /admin/members,/auth | identity | Permanent (erasable) | app_user_tenant_isolation | security |
| oauth_identity | 0008 | 092 | SEC01 | app_user, organization | — | /auth | identity | with user | oauth_identity_tenant_isolation | security |
| service_account | 0008 | 098 | SEC05 | organization | membership | /admin/service-accounts | identity | Permanent | service_account_tenant_isolation | security |
| service_account_credential | 0013, 0008 | 098, 097 | SEC03, SEC05 | organization, service_account | — | /admin/service-accounts/{id}/credentials | auth/keys | Permanent | service_account_credential_tenant_isolation | security |
| session | 0008 | 091 | SEC01 | app_user, organization | refresh_token | /auth | identity | Transient(30d) | session_tenant_isolation | security |
| refresh_token | 0008 | 091,097 | SEC03 | session, organization | — | /auth | identity | Transient | refresh_token_tenant_isolation | security |

## Domain 2 — RBAC  (subsystem: Authorization; ADR-0008)

| Table | ADRs | FR | NFR | Parents | Children | APIs | Future module | Retention | RLS | Audit |
|-------|------|----|-----|---------|----------|------|---------------|-----------|-----|-------|
| role | 0008 | 098 | SEC05 | organization* | role_permission, membership, project_member | /admin/roles | authz | Permanent | *global+per-org* | config-change |
| permission | 0008 | 099,100 | SEC05 | — | role_permission | ops (read) | authz | Permanent | *global reference* | none-runtime |
| role_permission | 0008 | 099,100 | SEC05 | role, permission | — | /admin/roles | authz | Permanent | *global reference* | config-change |
| membership | 0008 | 098,135 | SEC05 | app_user, service_account, organization, role | — | /admin/members | authz | Permanent | membership_tenant_isolation | security |

\* `role.organization_id` is nullable (NULL = system role); global rows are reference data.

## Domain 3 — Projects & Access  (subsystem: Multi-Tenancy / Auth; ADR-0002/0008)

| Table | ADRs | FR | NFR | Parents | Children | APIs | Future module | Retention | RLS | Audit |
|-------|------|----|-----|---------|----------|------|---------------|-----------|-----|-------|
| project | 0004,0002 | 135 | S06 | organization | project_member, api_key, routing_policy, prompt_template, governance_policy, semantic_cache_entry | /admin/projects | tenancy | Permanent | project_tenant_isolation | config-change |
| project_member | 0008 | 136 | SEC05 | app_user, organization, project, role | — | /admin/projects | authz | with membership | project_member_tenant_isolation | security |
| api_key | 0008 | 094-097 | SEC03 | organization, project | api_key_scope, reservation | /admin/keys, /v1/* (validate) | auth/keys | until revoke+audit | api_key_tenant_isolation | security |
| api_key_scope | 0008 | 095 | SEC05 | api_key, organization | — | /admin/keys | auth/keys | with key | api_key_scope_tenant_isolation | security |

## Domain 4 — Providers, Models, Registry  (subsystem: Provider Abstraction / Model Registry; ADR-0003)

| Table | ADRs | FR | NFR | Parents | Children | APIs | Future module | Retention | RLS | Audit |
|-------|------|----|-----|---------|----------|------|---------------|-----------|-----|-------|
| provider | 0003,0011 | 020-029 | M02,P01 | organization, secret_reference | model, provider_health | /admin/providers | adapters/providers | Permanent | provider_tenant_isolation | config-change |
| model | 0003 | 021,028 | M02 | organization, provider | price_table, provider_health, routing_policy_rule, semantic_cache_entry | /admin/models, /v1/models | registry | Permanent | model_tenant_isolation | config-change |
| price_table | 0004 | 074,075 | — | model, organization | — | /admin/price-tables | registry | Permanent (historical) | price_table_tenant_isolation | config-change |
| provider_health | 0012 | 037,038 | A02 | model, organization, provider | — | ops, routing (internal) | routing/health | Transient(7-30d) | provider_health_tenant_isolation | none-runtime |

## Domain 5 — Routing & Prompts  (subsystem: Routing Engine / Prompt Mgmt; ADR-0012/0006)

| Table | ADRs | FR | NFR | Parents | Children | APIs | Future module | Retention | RLS | Audit |
|-------|------|----|-----|---------|----------|------|---------------|-----------|-----|-------|
| routing_policy | 0012 | 030-033 | P01,M02 | organization, project | routing_policy_rule | /admin/routing-policies | routing | Permanent | routing_policy_tenant_isolation | config-change |
| routing_policy_rule | 0012 | 039-041 | M02 | model, organization, routing_policy | — | /admin/routing-policies | routing | Permanent | routing_policy_rule_tenant_isolation | config-change |
| prompt_template | 0006 | 058 | — | app_user, organization, project | prompt_version | /admin/prompts | prompt | Permanent | prompt_template_tenant_isolation | config-change |
| prompt_version | 0006 | 058 | — | app_user, organization, prompt_template | — | /admin/prompts | prompt | Permanent (repro) | prompt_version_tenant_isolation | config-change |

## Domain 6 — Cache & Embeddings  (subsystem: Semantic Cache; ADR-0006/0007)

| Table | ADRs | FR | NFR | Parents | Children | APIs | Future module | Retention | RLS | Audit |
|-------|------|----|-----|---------|----------|------|---------------|-----------|-----|-------|
| embedding | 0006,0007 | 054-058 | P03,SEC07 | organization | semantic_cache_entry | /v1/* (internal), ops | cache/embeddings | Operational-hot | embedding_tenant_isolation | none-runtime |
| semantic_cache_entry | 0006 | 050-058 | P02,P03,SEC07 | embedding, model, organization, project | — | /v1/*, /admin/cache | cache | Operational-hot(TTL) | semantic_cache_entry_tenant_isolation | none-runtime (purge=config) |

## Domain 7 — Cost, Ledger, Usage, Billing  (subsystem: Budget/Metering; ADR-0004)

| Table | ADRs | FR | NFR | Parents | Children | APIs | Future module | Retention | RLS | Audit |
|-------|------|----|-----|---------|----------|------|---------------|-----------|-----|-------|
| budget | 0004 | 060-067 | P05 | organization | reservation | /admin/budgets | budget | Permanent | budget_tenant_isolation | config-change |
| reservation | 0004 | 060-063 | P05,P06 | api_key, budget, organization | — | /v1/* (internal) | budget/reconciler | Transient(7-30d) | reservation_tenant_isolation | none-runtime |
| usage_ledger | 0004 | 070-073 | S05,P06 | organization | — | /v1/*(write), /admin/usage(read) | metering | Hot→Compliance (partitioned) | usage_ledger_tenant_isolation | **append-only** (self-evidence) |
| usage_rollup | 0004 | 086 | O05 | organization | — | /admin/usage | analytics | Operational-long | usage_rollup_tenant_isolation | none-runtime |
| billing_account | — | — | — | organization | invoice | /admin/billing | billing | Permanent | billing_account_tenant_isolation | config-change |
| invoice | — | — | — | billing_account, organization | — | /admin/billing | billing | Permanent(financial 7y) | invoice_tenant_isolation | config-change |
| rate_limit_policy | — | 064,065 | S06 | organization | — | /admin/rate-limits | budget/limits | Permanent | rate_limit_policy_tenant_isolation | config-change |

## Domain 8 — Governance & Ops  (subsystem: Governance / Platform; ADR-0009/0005/0011)

| Table | ADRs | FR | NFR | Parents | Children | APIs | Future module | Retention | RLS | Audit |
|-------|------|----|-----|---------|----------|------|---------------|-----------|-----|-------|
| audit_event | 0009 | 113-115 | SEC09 | (org logical) | — | /admin/audit (read/export) | governance/audit | Compliance(1-7y, partitioned) | audit_event_tenant_isolation | **self (immutable)** |
| governance_policy | 0009,0010 | 110-118 | C01-C06 | organization, project | — | /admin/governance | governance | Permanent | governance_policy_tenant_isolation | config-change |
| feature_flag | — | — | — | organization* | — | /admin/flags | platform/config | Permanent | *global+per-org* | config-change |
| notification | 0005 | 066,085 | — | organization | — | ops, workers | notifications | Transient(90d) | notification_tenant_isolation | none-runtime |
| background_job | 0005 | — | S05 | organization* | — | workers (internal) | workers | Transient | background_job_tenant_isolation | none-runtime |
| configuration | — | — | — | app_user, organization* | — | /admin/config | platform/config | Permanent | *global+per-org* | config-change |
| secret_reference | 0011 | 022,093,097 | SEC03 | organization | provider, webhook | /admin/secrets(refs) | secrets | Permanent | secret_reference_tenant_isolation | config-change (rotation) |
| webhook | 0011 | — | — | organization, secret_reference | webhook_delivery | /admin/webhooks | webhooks | Permanent | webhook_tenant_isolation | config-change |
| webhook_delivery | 0005 | — | — | organization, webhook | — | ops, workers | webhooks | Transient(30-90d) | webhook_delivery_tenant_isolation | none-runtime |

\* nullable `organization_id` (NULL = global scope); org-scoped rows filter by tenant.

---

## Cross-cutting summary

### Build order (DB layer, follows FK topology → Migration ordering)
`organization` → identity (`app_user`…`refresh_token`) → RBAC (`permission`,`role`,`role_permission`,
`membership`) → projects/access → `secret_reference` → providers/registry (+deferred FK) → routing/
prompts → cache/embeddings → cost/ledger/billing → governance/ops. Matches
[`Migration_Strategy.md`](Migration_Strategy.md) §2.

### API ownership rollup (see [`System_Context.md`](System_Context.md) §8)
- **`/v1/*` (inference)** touches: `api_key`(validate), `governance_policy`, `budget`/`reservation`,
  `semantic_cache_entry`/`embedding`, `provider`/`model`/`price_table`, writes `usage_ledger`.
- **`/admin/*`** owns all config/registry/budget/governance/keys CRUD (audited: config-change).
- **`/auth/*`** owns `session`, `refresh_token`, `oauth_identity`, `app_user` (audited: security).
- **workers** (no external API) own `usage_rollup`, `background_job`, `webhook_delivery`, embedding
  population, and append to `usage_ledger`/`audit_event`.

### Audit-requirement rollup (→ `audit_event`, ADR-0009)
- **Security-audited:** all identity/key/permission changes (`app_user`, `session`, `refresh_token`,
  `service_account`, `oauth_identity`, `membership`, `project_member`, `api_key`, `api_key_scope`).
- **Config-change-audited:** all provider/model/pricing/routing/prompt/budget/governance/rate-limit/
  secret/webhook/billing config CRUD.
- **Not runtime-audited (data path):** `usage_ledger` (is itself the metering record), `reservation`,
  `semantic_cache_entry`, `embedding`, `provider_health`, `notification`, `background_job`,
  `webhook_delivery` — their effects are observable via metrics/traces, and cache **purge** is audited
  as a config action.
- **Self:** `audit_event` is the immutable log (append-only, hash-chained).

### Coverage
All 41 base tables appear above with every requested attribute. RLS policy exists for all 33 tenant
tables + the 2 partitioned tables ([`RLS_Strategy.md`](RLS_Strategy.md)); global-reference tables
(`permission`, system `role`, `role_permission`) are marked. No table is unmapped.
