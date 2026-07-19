# Entity-Relationship Diagram (ERD)

**Phase:** 3 — Database Architecture · Draft for approval
**Last updated:** 2026-07-15

Mermaid `erDiagram`s for all **41 tables**, split by domain for readability, plus a high-level overview
and an explicit list of many-to-many relationships. Canonical DDL: [`Schema.sql`](Schema.sql); details:
[`Data_Dictionary.md`](Data_Dictionary.md). Crow's-foot: `||--o{` = one-to-many, `}o--o{` = many-to-many
(via association table).

## 0. High-level domain overview

```mermaid
flowchart TB
    ORG[organization = tenant]
    subgraph Identity
      U[app_user]; SA[service_account]; OI[oauth_identity]; S[session]; RT[refresh_token]
    end
    subgraph RBAC
      R[role]; P[permission]; RP[role_permission]; M[membership]
    end
    subgraph Projects_Access
      PR[project]; PM[project_member]; AK[api_key]; AKS[api_key_scope]
    end
    subgraph Providers
      PV[provider]; MD[model]; PT[price_table]; PH[provider_health]
    end
    subgraph Routing_Prompts
      RPOL[routing_policy]; RR[routing_policy_rule]; PTPL[prompt_template]; PVER[prompt_version]
    end
    subgraph Cache
      EMB[embedding]; SCE[semantic_cache_entry]
    end
    subgraph Cost
      B[budget]; RES[reservation]; UL[usage_ledger]; UR[usage_rollup]; BA[billing_account]; INV[invoice]; RL[rate_limit_policy]
    end
    subgraph Governance_Ops
      AE[audit_event]; GP[governance_policy]; FF[feature_flag]; NT[notification]; BJ[background_job]; CF[configuration]; SR[secret_reference]; WH[webhook]; WD[webhook_delivery]
    end
    ORG --> Identity & RBAC & Projects_Access & Providers & Routing_Prompts & Cache & Cost & Governance_Ops
```

## 1. Tenancy & Identity

```mermaid
erDiagram
    organization ||--o{ app_user : has
    organization ||--o{ service_account : has
    service_account ||--o{ service_account_credential : "authenticates via"
    organization ||--o{ session : has
    organization ||--o{ oidc_login_state : "login attempts"
    app_user ||--o{ oauth_identity : "federated by"
    app_user ||--o{ session : "authenticates"
    session ||--o{ refresh_token : "issues"
    organization {
      uuid id PK
      text slug UK
      text name
      org_status status
      deployment_mode deployment_mode
      text home_region
    }
    app_user {
      uuid id PK
      uuid organization_id FK
      citext email
      boolean is_active
    }
    oauth_identity {
      uuid id PK
      uuid user_id FK
      text provider
      text subject
    }
    service_account {
      uuid id PK
      uuid organization_id FK
      text name
    }
    service_account_credential {
      uuid id PK
      uuid service_account_id FK
      text client_id UK
      bytea secret_hash
      api_key_status status
    }
    oidc_login_state {
      uuid id PK
      uuid organization_id FK
      bytea state_hash UK
      bytea nonce_hash
      text code_verifier
      timestamptz expires_at
    }
    session {
      uuid id PK
      uuid user_id FK
      timestamptz expires_at
    }
    refresh_token {
      uuid id PK
      uuid session_id FK
      bytea token_hash UK
      uuid rotated_to FK
    }
```

## 2. RBAC

```mermaid
erDiagram
    role ||--o{ role_permission : grants
    permission ||--o{ role_permission : "granted by"
    role ||--o{ membership : "assigned in"
    organization ||--o{ membership : scopes
    app_user ||--o{ membership : "member via"
    service_account ||--o{ membership : "member via"
    role {
      uuid id PK
      uuid organization_id FK "NULL=system"
      text key
      boolean is_system
    }
    permission {
      uuid id PK
      text key UK
    }
    role_permission {
      uuid role_id PK,FK
      uuid permission_id PK,FK
    }
    membership {
      uuid id PK
      uuid organization_id FK
      uuid user_id FK
      uuid service_account_id FK
      uuid role_id FK
    }
```

## 3. Projects & Access

```mermaid
erDiagram
    organization ||--o{ project : has
    project ||--o{ project_member : "includes"
    app_user ||--o{ project_member : "member of"
    organization ||--o{ api_key : issues
    project ||--o{ api_key : scopes
    api_key ||--o{ api_key_scope : "granted"
    project {
      uuid id PK
      uuid organization_id FK
      text slug
    }
    project_member {
      uuid project_id PK,FK
      uuid user_id PK,FK
      uuid role_id FK
    }
    api_key {
      uuid id PK
      uuid organization_id FK
      uuid project_id FK
      text key_prefix UK
      bytea key_hash UK
      api_key_status status
    }
    api_key_scope {
      uuid api_key_id PK,FK
      text scope PK
    }
```

## 4. Providers, Models & Registry

```mermaid
erDiagram
    organization ||--o{ provider : configures
    provider ||--o{ model : offers
    model ||--o{ price_table : "priced by"
    provider ||--o{ provider_health : "monitored by"
    model ||--o{ provider_health : "monitored by"
    secret_reference ||--o{ provider : "credential via"
    provider {
      uuid id PK
      uuid organization_id FK
      provider_type type
      uuid credential_secret_ref FK
      boolean is_enabled
    }
    model {
      uuid id PK
      uuid organization_id FK
      uuid provider_id FK
      text name
      model_modality modality
      quality_tier quality_tier
    }
    price_table {
      uuid id PK
      uuid model_id FK
      numeric input_price_per_1k
      numeric output_price_per_1k
      timestamptz effective_from
    }
    provider_health {
      uuid id PK
      uuid provider_id FK
      health_state state
      timestamptz observed_at
    }
```

## 5. Routing & Prompts

```mermaid
erDiagram
    organization ||--o{ routing_policy : owns
    project ||--o{ routing_policy : scopes
    routing_policy ||--o{ routing_policy_rule : "ordered by"
    model ||--o{ routing_policy_rule : "targets"
    organization ||--o{ prompt_template : owns
    prompt_template ||--o{ prompt_version : "versioned by"
    routing_policy {
      uuid id PK
      uuid organization_id FK
      routing_strategy strategy
    }
    routing_policy_rule {
      uuid id PK
      uuid routing_policy_id FK
      uuid model_id FK
      integer priority
      integer weight
    }
    prompt_template {
      uuid id PK
      uuid organization_id FK
      text name
    }
    prompt_version {
      uuid id PK
      uuid prompt_template_id FK
      integer version
      boolean is_published
    }
```

## 6. Cache & Embeddings

```mermaid
erDiagram
    organization ||--o{ embedding : owns
    organization ||--o{ semantic_cache_entry : owns
    embedding ||--o| semantic_cache_entry : "semantic tier of"
    model ||--o{ semantic_cache_entry : "produced by"
    embedding {
      uuid id PK
      uuid organization_id FK
      text embedding_model
      text embedding_version
      vector vector
    }
    semantic_cache_entry {
      uuid id PK
      uuid organization_id FK
      bytea request_hash
      uuid embedding_id FK
      jsonb response
      timestamptz expires_at
    }
```

## 7. Cost, Ledger, Usage & Billing

```mermaid
erDiagram
    organization ||--o{ budget : sets
    budget ||--o{ reservation : "reserved against"
    api_key ||--o{ reservation : "charged to"
    organization ||--o{ usage_ledger : meters
    organization ||--o{ usage_rollup : aggregates
    organization ||--o{ billing_account : "billed via"
    billing_account ||--o{ invoice : issues
    organization ||--o{ rate_limit_policy : limits
    budget {
      uuid id PK
      uuid organization_id FK
      budget_scope scope
      uuid scope_id
      numeric amount_limit
      limit_kind limit_kind
    }
    reservation {
      uuid id PK
      uuid organization_id FK
      uuid budget_id FK
      uuid request_id UK
      reservation_status status
    }
    usage_ledger {
      uuid id PK
      uuid organization_id FK
      uuid request_id
      ledger_entry_type entry_type
      numeric cost_amount
      timestamptz created_at PK
    }
    usage_rollup {
      uuid id PK
      uuid organization_id FK
      date bucket_date
      numeric total_cost
    }
    billing_account {
      uuid id PK
      uuid organization_id FK
    }
    invoice {
      uuid id PK
      uuid billing_account_id FK
      invoice_status status
    }
    rate_limit_policy {
      uuid id PK
      uuid organization_id FK
      budget_scope scope
      uuid scope_id
    }
```

## 8. Governance & Ops

```mermaid
erDiagram
    organization ||--o{ audit_event : records
    organization ||--o{ governance_policy : governs
    organization ||--o{ notification : notifies
    organization ||--o{ secret_reference : references
    organization ||--o{ webhook : subscribes
    webhook ||--o{ webhook_delivery : delivers
    organization ||--o{ configuration : configures
    secret_reference ||--o{ webhook : "signs via"
    audit_event {
      uuid id PK
      uuid organization_id
      text action
      bytea entry_hash
      timestamptz created_at PK
    }
    governance_policy {
      uuid id PK
      uuid organization_id FK
      pii_action pii_action
      text_array allowed_regions
    }
    feature_flag {
      uuid id PK
      uuid organization_id FK "NULL=global"
      text key
    }
    notification {
      uuid id PK
      uuid organization_id FK
      notification_status status
    }
    background_job {
      uuid id PK
      uuid organization_id FK "NULL=system"
      job_status status
    }
    configuration {
      uuid id PK
      uuid organization_id FK "NULL=global"
      text key
      jsonb value
    }
    secret_reference {
      uuid id PK
      uuid organization_id FK
      text reference_path
    }
    webhook {
      uuid id PK
      uuid organization_id FK
      uuid secret_ref FK
    }
    webhook_delivery {
      uuid id PK
      uuid webhook_id FK
      webhook_delivery_status status
    }
```

## 9. Many-to-many relationships (explicit)

| M2M | Left | Right | Association table | Extra attributes |
|-----|------|-------|-------------------|------------------|
| Role grants | `role` | `permission` | `role_permission` | — |
| Org membership | `app_user` / `service_account` | `organization` | `membership` | `role_id`, `status` |
| Project membership | `app_user` | `project` | `project_member` | `role_id` |
| Key scopes | `api_key` | scope (value) | `api_key_scope` | — |
| Policy candidates | `routing_policy` | `model` | `routing_policy_rule` | `priority`, `weight`, `condition` |

All other relationships are one-to-many (or one-to-one optional for `embedding`↔`semantic_cache_entry`).

## 10. Global (non-tenant-scoped) reference entities
`permission` (catalog), system `role` (NULL org), and NULL-org rows of `feature_flag` /
`configuration` are **global reference data** (not tenant-owned) and intentionally have no
`organization_id` requirement. `audit_event` carries `organization_id` but its FK is enforced
logically (append-only partitioned log) — see [`Database_Design.md`](Database_Design.md) §13 and
[`RLS_Strategy.md`](RLS_Strategy.md).
