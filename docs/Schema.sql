-- ============================================================================
-- Enterprise LLM Gateway & Cost Router — PostgreSQL 16 Schema (Phase 3)
-- ----------------------------------------------------------------------------
-- Status: Phase 3 — Database Architecture · Draft for approval
-- Realizes: ADR-0002 (tenancy+RLS), ADR-0004 (reserve/commit ledger),
--           ADR-0006 (pgvector cache), ADR-0007 (embeddings), ADR-0008 (RBAC),
--           ADR-0009 (audit), ADR-0011 (secrets as references only).
-- Conventions:
--   * UUID primary keys (default gen_random_uuid; UUIDv7 recommended app-side
--     for time-ordered locality on high-volume tables — see Database_Design.md).
--   * Every tenant-owned table has organization_id NOT NULL + RLS (RLS_Strategy.md).
--   * timestamptz everywhere; created_at/updated_at on mutable entities.
--   * snake_case singular table names; "user" is reserved -> app_user.
--   * Secrets are NEVER stored — only references (secret_reference) — ADR-0011.
-- This file is DDL only. No application/ORM code (per Phase 3 constraints).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 0. Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid(), digest()
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector: semantic cache (ADR-0006)
CREATE EXTENSION IF NOT EXISTS pg_stat_statements; -- query observability (NFR-O)
CREATE EXTENSION IF NOT EXISTS btree_gin;     -- composite GIN where useful
CREATE EXTENSION IF NOT EXISTS citext;        -- case-insensitive email uniqueness

-- ---------------------------------------------------------------------------
-- 1. Enumerated types (stable, small domains). Larger/config-like sets use
--    lookup tables (role/permission) instead. See Database_Design.md §Enums.
-- ---------------------------------------------------------------------------
CREATE TYPE org_status        AS ENUM ('active','suspended','deleted');
CREATE TYPE deployment_mode   AS ENUM ('saas','self_hosted');
CREATE TYPE principal_type    AS ENUM ('user','service_account','api_key');
CREATE TYPE membership_status AS ENUM ('invited','active','disabled');
CREATE TYPE api_key_status    AS ENUM ('active','revoked','expired');
CREATE TYPE provider_type     AS ENUM ('openai','anthropic','google','bedrock','azure_openai','openai_compatible','self_hosted');
CREATE TYPE model_modality    AS ENUM ('chat','completion','embedding','multimodal');
CREATE TYPE quality_tier      AS ENUM ('economy','standard','premium','frontier');
CREATE TYPE routing_strategy  AS ENUM ('lowest_cost','lowest_latency','quality_tier','weighted','pinned');
CREATE TYPE health_state      AS ENUM ('healthy','degraded','open','half_open');
CREATE TYPE budget_scope      AS ENUM ('organization','project','api_key');
CREATE TYPE budget_period     AS ENUM ('daily','weekly','monthly','custom');
CREATE TYPE limit_kind        AS ENUM ('soft','hard');
CREATE TYPE reservation_status AS ENUM ('reserved','committed','released','expired');
CREATE TYPE ledger_entry_type AS ENUM ('debit','credit');
CREATE TYPE cache_hit_type    AS ENUM ('miss','exact_hit','semantic_hit');
CREATE TYPE invoice_status    AS ENUM ('draft','open','paid','void','uncollectible');
CREATE TYPE audit_result      AS ENUM ('allow','deny','success','failure');
CREATE TYPE job_status        AS ENUM ('queued','running','succeeded','failed','dead_letter');
CREATE TYPE notification_status AS ENUM ('pending','sent','failed');
CREATE TYPE webhook_delivery_status AS ENUM ('pending','delivered','failed','dead_letter');
CREATE TYPE pii_action        AS ENUM ('allow_with_log','redact','block');
CREATE TYPE logging_policy     AS ENUM ('store','hash','drop');

-- ===========================================================================
-- 2. TENANCY & IDENTITY
-- ===========================================================================

-- 2.1 organization = tenant (top-level isolation boundary) — ADR-0002 / FR-130
CREATE TABLE organization (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            text NOT NULL,
    name            text NOT NULL,
    status          org_status NOT NULL DEFAULT 'active',
    deployment_mode deployment_mode NOT NULL DEFAULT 'saas',
    home_region     text NOT NULL DEFAULT 'us-east-1',   -- residency pin (ADR-0010)
    settings        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- misc org settings (see Database_Design.md JSONB)
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz,
    CONSTRAINT organization_slug_key UNIQUE (slug),
    CONSTRAINT organization_slug_format CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$')
);
COMMENT ON TABLE organization IS 'Tenant / customer organization; top-level isolation boundary (ADR-0002, FR-130).';

-- 2.2 app_user (tenant-scoped human principal) — ADR-0008 / FR-090
CREATE TABLE app_user (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    email           citext NOT NULL,                      -- see note: citext via case-insensitive; using text+lower index if citext absent
    display_name    text,
    is_active       boolean NOT NULL DEFAULT true,
    last_login_at   timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz,
    CONSTRAINT app_user_org_email_key UNIQUE (organization_id, email)
);
COMMENT ON TABLE app_user IS 'Human user, scoped to one organization for tenant isolation (FR-131).';

-- 2.3 oauth_identity (external SSO identities for a user) — FR-092
CREATE TABLE oauth_identity (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    provider        text NOT NULL,                        -- 'okta','azuread','google', ...
    subject         text NOT NULL,                        -- OIDC 'sub'
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT oauth_identity_provider_subject_key UNIQUE (provider, subject)
);
COMMENT ON TABLE oauth_identity IS 'Federated identity mapping (OIDC provider+subject -> user) (FR-092).';

-- 2.4 service_account (tenant-scoped machine principal) — ADR-0008
CREATE TABLE service_account (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    name            text NOT NULL,
    description     text,
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz,
    CONSTRAINT service_account_org_name_key UNIQUE (organization_id, name)
);
COMMENT ON TABLE service_account IS 'Non-human principal for automation; RBAC-assignable (FR-098).';

-- 2.4b service_account_credential (client-credentials for a service account) — ADR-0013, FR-098/097
CREATE TABLE service_account_credential (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id    uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    service_account_id uuid NOT NULL REFERENCES service_account(id) ON DELETE CASCADE,
    client_id          text NOT NULL,
    secret_hash        bytea NOT NULL,                    -- SHA-256 of client secret; never plaintext
    status             api_key_status NOT NULL DEFAULT 'active',
    rotation_reason    text,                              -- why last rotated (scheduled|compromise|manual)
    created_by         uuid REFERENCES app_user(id) ON DELETE SET NULL,
    revoked_by         uuid REFERENCES app_user(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    last_used_at       timestamptz,                       -- credential hygiene / stale-credential detection
    last_rotated_at    timestamptz,
    expires_at         timestamptz,
    revoked_at         timestamptz,
    CONSTRAINT service_account_credential_client_id_key UNIQUE (client_id)
);
COMMENT ON TABLE service_account_credential IS 'Hashed client-credential for a service account; supports rotation with grace overlap (ADR-0013). Only the hash is stored (NFR-SEC03, FR-097).';

-- 2.5 session (admin auth session) — FR-091
CREATE TABLE session (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    ip_address      inet,
    user_agent      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    CONSTRAINT session_expiry_ck CHECK (expires_at > created_at)
);
COMMENT ON TABLE session IS 'Authenticated admin session; parent of refresh tokens (FR-091).';

-- 2.6 refresh_token (rotating; stores only a hash) — FR-091/097
CREATE TABLE refresh_token (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    session_id      uuid NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    token_hash      bytea NOT NULL,                       -- SHA-256 of token; never the token
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    rotated_to      uuid REFERENCES refresh_token(id),    -- rotation chain
    revoked_at      timestamptz,
    CONSTRAINT refresh_token_hash_key UNIQUE (token_hash)
);
COMMENT ON TABLE refresh_token IS 'Rotating refresh token; only SHA-256 hash stored (NFR-SEC03, FR-097).';

-- ===========================================================================
-- 3. RBAC (ADR-0008 / FR-098..101)
-- ===========================================================================

-- 3.1 role (system + custom). System roles seeded; custom are per-org.
CREATE TABLE role (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES organization(id) ON DELETE CASCADE, -- NULL => global system role
    key             text NOT NULL,                        -- 'owner','admin','operator','finance','auditor','developer'
    name            text NOT NULL,
    is_system       boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT role_scope_key UNIQUE (organization_id, key)
);
COMMENT ON TABLE role IS 'Named RBAC role; system roles have NULL organization_id (ADR-0008, FR-098).';

-- 3.2 permission (fine-grained catalog; global reference data)
CREATE TABLE permission (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key             text NOT NULL,                        -- 'budget:write','key:issue','audit:read', ...
    description     text NOT NULL,
    CONSTRAINT permission_key_key UNIQUE (key)
);
COMMENT ON TABLE permission IS 'Fine-grained permission catalog (ADR-0008). Global reference data.';

-- 3.3 role_permission (M2M role<->permission)
CREATE TABLE role_permission (
    role_id         uuid NOT NULL REFERENCES role(id) ON DELETE CASCADE,
    permission_id   uuid NOT NULL REFERENCES permission(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);
COMMENT ON TABLE role_permission IS 'M2M: which permissions a role grants (FR-099/100).';

-- 3.4 membership (M2M user/service_account <-> organization, carrying role) — FR-098/135
CREATE TABLE membership (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    user_id         uuid REFERENCES app_user(id) ON DELETE CASCADE,
    service_account_id uuid REFERENCES service_account(id) ON DELETE CASCADE,
    role_id         uuid NOT NULL REFERENCES role(id) ON DELETE RESTRICT,
    status          membership_status NOT NULL DEFAULT 'active',
    created_at      timestamptz NOT NULL DEFAULT now(),
    -- exactly one principal type per membership row
    CONSTRAINT membership_principal_ck CHECK (
        (user_id IS NOT NULL)::int + (service_account_id IS NOT NULL)::int = 1),
    CONSTRAINT membership_user_role_key   UNIQUE (organization_id, user_id, role_id),
    CONSTRAINT membership_sa_role_key     UNIQUE (organization_id, service_account_id, role_id)
);
COMMENT ON TABLE membership IS 'Org-level role assignment for a user or service account (FR-098). A principal may hold multiple roles.';

-- ===========================================================================
-- 4. PROJECTS (mid-tier grouping; realizes ADR-0004 "team" tier) — FR-135
-- ===========================================================================
CREATE TABLE project (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    slug            text NOT NULL,
    name            text NOT NULL,
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz,
    CONSTRAINT project_org_slug_key UNIQUE (organization_id, slug)
);
COMMENT ON TABLE project IS 'Grouping of keys/budgets/policies within an org; Organization->Project->API key scope chain (refines ADR-0004 team tier).';

-- 4.1 project_member (M2M user <-> project with optional project role) — FR-136
CREATE TABLE project_member (
    project_id      uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role_id         uuid REFERENCES role(id) ON DELETE SET NULL,
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE, -- denormalized for RLS
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, user_id)
);
COMMENT ON TABLE project_member IS 'M2M membership of users in projects, optional project-scoped role (FR-136).';

-- ===========================================================================
-- 5. ACCESS: API KEYS (virtual keys) — ADR-0008 / FR-094..097
-- ===========================================================================
CREATE TABLE api_key (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    project_id      uuid REFERENCES project(id) ON DELETE CASCADE,
    name            text NOT NULL,
    key_prefix      text NOT NULL,                        -- non-secret display prefix e.g. 'elg_live_ab12'
    key_hash        bytea NOT NULL,                       -- SHA-256 of full key; full key shown once
    status          api_key_status NOT NULL DEFAULT 'active',
    created_by      uuid REFERENCES app_user(id) ON DELETE SET NULL,
    last_used_at    timestamptz,
    expires_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz,
    CONSTRAINT api_key_hash_key UNIQUE (key_hash),
    CONSTRAINT api_key_prefix_key UNIQUE (key_prefix)
);
COMMENT ON TABLE api_key IS 'Virtual API key for inference clients; only SHA-256 hash stored, shown once (FR-097).';

-- 5.1 api_key_scope (M2M key <-> scope; inference-only subset) — FR-095
CREATE TABLE api_key_scope (
    api_key_id      uuid NOT NULL REFERENCES api_key(id) ON DELETE CASCADE,
    scope           text NOT NULL,                        -- 'infer:chat','infer:embed', ...
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE, -- denormalized for RLS
    PRIMARY KEY (api_key_id, scope)
);
COMMENT ON TABLE api_key_scope IS 'M2M scopes granted to a virtual key; never admin permissions (ADR-0008).';

-- ===========================================================================
-- 6. PROVIDERS, MODELS, REGISTRY, HEALTH — ADR-0003 / FR-020..029, 074
-- ===========================================================================

-- 6.1 provider (tenant-scoped configuration; credentials via secret_reference)
CREATE TABLE provider (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    type            provider_type NOT NULL,
    name            text NOT NULL,
    base_url        text,                                 -- for openai_compatible/self_hosted
    region          text,                                 -- residency eligibility (FR-116)
    credential_secret_ref uuid,                            -- FK to secret_reference added post-definition (forward ref)
    is_enabled      boolean NOT NULL DEFAULT true,        -- runtime enable/disable (FR-028)
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- timeouts/retries/concurrency (FR-029)
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT provider_org_name_key UNIQUE (organization_id, name)
);
COMMENT ON TABLE provider IS 'Per-org provider configuration; credentials referenced, never stored (ADR-0003/0011, FR-020/022).';

-- 6.2 model (the model registry entry) — FR-021
CREATE TABLE model (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    provider_id     uuid NOT NULL REFERENCES provider(id) ON DELETE CASCADE,
    name            text NOT NULL,                        -- provider model id, e.g. 'gpt-4o'
    alias           text,                                 -- org-facing alias resolved by routing (FR-005)
    modality        model_modality NOT NULL,
    quality_tier    quality_tier NOT NULL DEFAULT 'standard',
    context_window  integer,
    max_output_tokens integer,
    is_enabled      boolean NOT NULL DEFAULT true,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT model_provider_name_key UNIQUE (provider_id, name),
    CONSTRAINT model_org_alias_key UNIQUE (organization_id, alias)
);
COMMENT ON TABLE model IS 'Model registry: capability, quality tier, context window; enable/disable at runtime (FR-021/028).';

-- 6.3 price_table (versioned, effective-dated pricing) — FR-074/075
CREATE TABLE price_table (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    model_id        uuid NOT NULL REFERENCES model(id) ON DELETE CASCADE,
    currency        char(3) NOT NULL DEFAULT 'USD',
    input_price_per_1k   numeric(18,8) NOT NULL,          -- cost per 1k input tokens
    output_price_per_1k  numeric(18,8) NOT NULL,
    effective_from  timestamptz NOT NULL,
    effective_to    timestamptz,                          -- NULL = current
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT price_nonneg_ck CHECK (input_price_per_1k >= 0 AND output_price_per_1k >= 0),
    CONSTRAINT price_effective_ck CHECK (effective_to IS NULL OR effective_to > effective_from),
    CONSTRAINT price_model_effective_key UNIQUE (model_id, effective_from)
);
COMMENT ON TABLE price_table IS 'Effective-dated pricing per model for cost computation & historical reproducibility (FR-074/075, SM-T07).';

-- 6.4 provider_health (rolling health snapshots feeding circuit breaker) — FR-037/038
CREATE TABLE provider_health (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    provider_id     uuid NOT NULL REFERENCES provider(id) ON DELETE CASCADE,
    model_id        uuid REFERENCES model(id) ON DELETE CASCADE,
    state           health_state NOT NULL DEFAULT 'healthy',
    success_rate    numeric(5,4),                         -- 0..1 over window
    p95_latency_ms  integer,
    observed_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT provider_health_rate_ck CHECK (success_rate IS NULL OR (success_rate >= 0 AND success_rate <= 1))
);
COMMENT ON TABLE provider_health IS 'Health/circuit-breaker signal snapshots per provider/model (FR-037/038). Short retention.';

-- ===========================================================================
-- 7. ROUTING (ADR-0012 / FR-030..041)
-- ===========================================================================
CREATE TABLE routing_policy (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    project_id      uuid REFERENCES project(id) ON DELETE CASCADE,
    name            text NOT NULL,
    strategy        routing_strategy NOT NULL DEFAULT 'lowest_cost',
    is_active       boolean NOT NULL DEFAULT true,
    constraints     jsonb NOT NULL DEFAULT '{}'::jsonb,   -- allowed providers/regions/models, residency (FR-032/116)
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT routing_policy_org_name_key UNIQUE (organization_id, name)
);
COMMENT ON TABLE routing_policy IS 'Declarative routing policy scoped to org/project (ADR-0012, FR-030).';

CREATE TABLE routing_policy_rule (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    routing_policy_id uuid NOT NULL REFERENCES routing_policy(id) ON DELETE CASCADE,
    priority        integer NOT NULL,                     -- lower = evaluated first (fallback chains, FR-040)
    model_id        uuid REFERENCES model(id) ON DELETE SET NULL,
    weight          integer,                              -- for weighted/canary (FR-041)
    condition       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- right-sizing/escalation signal (FR-039)
    CONSTRAINT routing_rule_policy_priority_key UNIQUE (routing_policy_id, priority),
    CONSTRAINT routing_rule_weight_ck CHECK (weight IS NULL OR weight >= 0)
);
COMMENT ON TABLE routing_policy_rule IS 'Ordered candidate rules within a policy: fallback chains, weights, right-sizing (FR-039/040/041).';

-- ===========================================================================
-- 8. PROMPT MANAGEMENT (ADR-0006 §prompt / FR-058, 118)
-- ===========================================================================
CREATE TABLE prompt_template (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    project_id      uuid REFERENCES project(id) ON DELETE CASCADE,
    name            text NOT NULL,
    description     text,
    created_by      uuid REFERENCES app_user(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT prompt_template_org_name_key UNIQUE (organization_id, name)
);
COMMENT ON TABLE prompt_template IS 'Named server-side prompt template; versions participate in cache keys (FR-058).';

CREATE TABLE prompt_version (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    prompt_template_id uuid NOT NULL REFERENCES prompt_template(id) ON DELETE CASCADE,
    version         integer NOT NULL,
    content         text NOT NULL,
    variables       jsonb NOT NULL DEFAULT '[]'::jsonb,   -- declared template variables
    is_published    boolean NOT NULL DEFAULT false,
    created_by      uuid REFERENCES app_user(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT prompt_version_template_version_key UNIQUE (prompt_template_id, version)
);
COMMENT ON TABLE prompt_version IS 'Immutable versioned prompt content; version change invalidates dependent cache (FR-058).';

-- ===========================================================================
-- 9. SEMANTIC CACHE & EMBEDDINGS (ADR-0006/0007 / FR-050..058)
-- ===========================================================================

-- 9.1 embedding (normalized vector store; reusable) — ADR-0007
--     Dimension is model-dependent; 1024 default, finalized Phase 8. Changing
--     dimension is a versioned migration (re-embed). halfvec option: see Indexing_Strategy.md.
CREATE TABLE embedding (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    embedding_model text NOT NULL,                        -- model name that produced the vector
    embedding_version text NOT NULL,                      -- version tag (space identity)
    dim             smallint NOT NULL,
    vector          vector(1024) NOT NULL,                -- pgvector column (ADR-0006)
    created_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE embedding IS 'Tenant-scoped embedding vectors for semantic cache/retrieval; tagged with model+version (ADR-0007, FR-054/058).';

-- 9.2 semantic_cache_entry (exact + semantic cache metadata + response) — FR-050..058
CREATE TABLE semantic_cache_entry (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    project_id      uuid REFERENCES project(id) ON DELETE CASCADE,
    request_hash    bytea NOT NULL,                       -- SHA-256 of normalized request (exact key, FR-050)
    model_id        uuid REFERENCES model(id) ON DELETE SET NULL,
    prompt_fingerprint text,                              -- normalized prompt digest for auditability
    response        jsonb NOT NULL,                       -- cached canonical response
    embedding_id    uuid REFERENCES embedding(id) ON DELETE SET NULL, -- semantic tier (FR-054)
    hit_count       bigint NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz,                          -- TTL (FR-051/058)
    CONSTRAINT semantic_cache_org_hash_key UNIQUE (organization_id, request_hash)
);
COMMENT ON TABLE semantic_cache_entry IS 'Exact+semantic cache entry, tenant-scoped; exact key = request_hash, semantic via embedding_id (FR-050..058).';

-- ===========================================================================
-- 10. BUDGETS, RESERVE/COMMIT LEDGER, USAGE, BILLING — ADR-0004 / FR-060..077
-- ===========================================================================

-- 10.1 budget (hierarchical: organization/project/api_key) — FR-060..062
CREATE TABLE budget (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    scope           budget_scope NOT NULL,
    scope_id        uuid NOT NULL,                        -- org/project/api_key id (polymorphic; integrity enforced in app + trigger, see Database_Design.md)
    period          budget_period NOT NULL DEFAULT 'monthly',
    limit_kind      limit_kind NOT NULL DEFAULT 'hard',
    amount_limit    numeric(18,6) NOT NULL,               -- currency amount
    currency        char(3) NOT NULL DEFAULT 'USD',
    period_start    timestamptz NOT NULL,
    period_end      timestamptz NOT NULL,
    alert_thresholds integer[] NOT NULL DEFAULT '{80,100}', -- percent thresholds (FR-066)
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT budget_amount_ck CHECK (amount_limit >= 0),
    CONSTRAINT budget_period_ck CHECK (period_end > period_start),
    CONSTRAINT budget_scope_period_key UNIQUE (organization_id, scope, scope_id, period, period_start)
);
COMMENT ON TABLE budget IS 'Hierarchical budget (org/project/key), hard or soft, with alert thresholds (ADR-0004, FR-060..067).';

-- 10.2 reservation (durable mirror of Redis reserve for reconciliation) — ADR-0004
CREATE TABLE reservation (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    budget_id       uuid REFERENCES budget(id) ON DELETE SET NULL,
    api_key_id      uuid REFERENCES api_key(id) ON DELETE SET NULL,
    request_id      uuid NOT NULL,                        -- gateway x-request-id
    estimated_cost  numeric(18,8) NOT NULL,
    actual_cost     numeric(18,8),
    status          reservation_status NOT NULL DEFAULT 'reserved',
    created_at      timestamptz NOT NULL DEFAULT now(),
    settled_at      timestamptz,
    expires_at      timestamptz NOT NULL,
    CONSTRAINT reservation_cost_ck CHECK (estimated_cost >= 0 AND (actual_cost IS NULL OR actual_cost >= 0)),
    CONSTRAINT reservation_request_key UNIQUE (request_id)
);
COMMENT ON TABLE reservation IS 'Durable record of a budget reservation for reconciliation with Redis counters (ADR-0004). High churn, short retention.';

-- 10.3 usage_ledger (append-only double-entry, PARTITIONED monthly) — FR-070..073
CREATE TABLE usage_ledger (
    id              uuid NOT NULL DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    project_id      uuid,
    api_key_id      uuid,
    request_id      uuid NOT NULL,
    reservation_id  uuid,
    provider_id     uuid,
    model_id        uuid,
    entry_type      ledger_entry_type NOT NULL,           -- double-entry (debit/credit)
    prompt_tokens   integer NOT NULL DEFAULT 0,
    completion_tokens integer NOT NULL DEFAULT 0,
    total_tokens    integer GENERATED ALWAYS AS (prompt_tokens + completion_tokens) STORED,
    cost_amount     numeric(18,8) NOT NULL DEFAULT 0,
    currency        char(3) NOT NULL DEFAULT 'USD',
    cache_hit       cache_hit_type NOT NULL DEFAULT 'miss',
    latency_ms      integer,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at),                          -- partition key must be in PK
    CONSTRAINT usage_tokens_ck CHECK (prompt_tokens >= 0 AND completion_tokens >= 0),
    CONSTRAINT usage_cost_ck   CHECK (cost_amount >= 0)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE usage_ledger IS 'Append-only, double-entry usage/cost system of record; partitioned monthly (ADR-0004, FR-070..073, NFR-S05).';

-- Illustrative initial partitions (migration/automation creates rolling months) --
CREATE TABLE usage_ledger_2026_07 PARTITION OF usage_ledger
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE usage_ledger_2026_08 PARTITION OF usage_ledger
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');

-- 10.4 usage_rollup (denormalized aggregates for analytics) — FR-086, justified denorm
CREATE TABLE usage_rollup (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    project_id      uuid,
    model_id        uuid,
    bucket_date     date NOT NULL,                        -- day grain
    request_count   bigint NOT NULL DEFAULT 0,
    total_tokens    bigint NOT NULL DEFAULT 0,
    total_cost      numeric(20,6) NOT NULL DEFAULT 0,
    cache_hit_count bigint NOT NULL DEFAULT 0,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT usage_rollup_key UNIQUE (organization_id, project_id, model_id, bucket_date)
);
COMMENT ON TABLE usage_rollup IS 'Precomputed daily aggregates (denormalized for dashboard performance; justified in Database_Design.md) (FR-086).';

-- 10.5 billing_account & invoice — FR (metering feeds billing; billing external in v1)
CREATE TABLE billing_account (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    external_ref    text,                                 -- external billing system id (no PAN/card data)
    currency        char(3) NOT NULL DEFAULT 'USD',
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT billing_account_org_key UNIQUE (organization_id)
);
COMMENT ON TABLE billing_account IS 'Billing linkage for an org; references external billing system only (no card/PAN data).';

CREATE TABLE invoice (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    billing_account_id uuid NOT NULL REFERENCES billing_account(id) ON DELETE CASCADE,
    period_start    date NOT NULL,
    period_end      date NOT NULL,
    amount_due      numeric(20,6) NOT NULL DEFAULT 0,
    currency        char(3) NOT NULL DEFAULT 'USD',
    status          invoice_status NOT NULL DEFAULT 'draft',
    issued_at       timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT invoice_period_ck CHECK (period_end >= period_start),
    CONSTRAINT invoice_account_period_key UNIQUE (billing_account_id, period_start, period_end)
);
COMMENT ON TABLE invoice IS 'Periodic invoice derived from usage_rollup; billing execution is external in v1.';

-- ===========================================================================
-- 11. RATE LIMITS — FR-064/065
-- ===========================================================================
CREATE TABLE rate_limit_policy (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    scope           budget_scope NOT NULL,                -- reuse org/project/api_key scoping
    scope_id        uuid NOT NULL,
    requests_per_second integer,
    requests_per_period integer,
    tokens_per_period bigint,
    period          budget_period NOT NULL DEFAULT 'monthly',
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT rate_limit_nonneg_ck CHECK (
        (requests_per_second IS NULL OR requests_per_second >= 0) AND
        (requests_per_period IS NULL OR requests_per_period >= 0) AND
        (tokens_per_period IS NULL OR tokens_per_period >= 0)),
    CONSTRAINT rate_limit_scope_key UNIQUE (organization_id, scope, scope_id, period)
);
COMMENT ON TABLE rate_limit_policy IS 'Per-scope rate/quota limits enforced at runtime via Redis; this is the config of record (FR-064/065).';

-- ===========================================================================
-- 12. GOVERNANCE: AUDIT (append-only, hash-chained, PARTITIONED) & POLICY
--     ADR-0009 / FR-110..117, FR-113/114
-- ===========================================================================
CREATE TABLE audit_event (
    id              uuid NOT NULL DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,                        -- FK enforced logically; partitioned table (see note)
    actor_type      principal_type,
    actor_id        uuid,
    action          text NOT NULL,                        -- 'budget.update','key.revoke', ...
    resource_type   text,
    resource_id     uuid,
    result          audit_result NOT NULL,
    ip_address      inet,
    detail          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- before/after (PII-scrubbed)
    prev_hash       bytea,                                -- hash chain link (tamper-evidence)
    entry_hash      bytea NOT NULL,                       -- SHA-256(prev_hash || canonical(row))
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE audit_event IS 'Append-only, hash-chained audit log; immutable via API + DB grants (FR-113/114, NFR-SEC09).';

CREATE TABLE audit_event_2026_07 PARTITION OF audit_event
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE audit_event_2026_08 PARTITION OF audit_event
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');

CREATE TABLE governance_policy (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    project_id      uuid REFERENCES project(id) ON DELETE CASCADE,
    pii_action      pii_action NOT NULL DEFAULT 'redact',
    allowed_regions text[] NOT NULL DEFAULT '{}',         -- residency (FR-116/117)
    prompt_logging  logging_policy NOT NULL DEFAULT 'hash',
    response_logging logging_policy NOT NULL DEFAULT 'hash',
    semantic_cache_enabled boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT governance_policy_scope_key UNIQUE (organization_id, project_id)
);
COMMENT ON TABLE governance_policy IS 'Per-org/project PII action, residency regions, logging policy, cache toggle (FR-110..118).';

-- ===========================================================================
-- 13. PLATFORM / OPS: flags, notifications, jobs, config, secrets, webhooks
-- ===========================================================================

-- 13.1 feature_flag (global or per-org)
CREATE TABLE feature_flag (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES organization(id) ON DELETE CASCADE, -- NULL = global
    key             text NOT NULL,
    is_enabled      boolean NOT NULL DEFAULT false,
    rollout         jsonb NOT NULL DEFAULT '{}'::jsonb,   -- percentage/targeting
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT feature_flag_scope_key UNIQUE (organization_id, key)
);
COMMENT ON TABLE feature_flag IS 'Feature flags, global (NULL org) or per-org override.';

-- 13.2 notification
CREATE TABLE notification (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    type            text NOT NULL,                        -- 'budget_threshold','slo_burn', ...
    channel         text NOT NULL,                        -- 'email','slack','webhook'
    payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
    status          notification_status NOT NULL DEFAULT 'pending',
    created_at      timestamptz NOT NULL DEFAULT now(),
    sent_at         timestamptz
);
COMMENT ON TABLE notification IS 'Outbound notifications (budget/SLO alerts) with delivery status (FR-066/085).';

-- 13.3 background_job (worker job tracking) — ADR-0005
CREATE TABLE background_job (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES organization(id) ON DELETE CASCADE, -- NULL = system job
    type            text NOT NULL,                        -- 'embedding','rollup','reconcile', ...
    status          job_status NOT NULL DEFAULT 'queued',
    payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempts        integer NOT NULL DEFAULT 0,
    max_attempts    integer NOT NULL DEFAULT 5,
    available_at    timestamptz NOT NULL DEFAULT now(),
    locked_at       timestamptz,
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT background_job_attempts_ck CHECK (attempts >= 0 AND attempts <= max_attempts)
);
COMMENT ON TABLE background_job IS 'Durable tracking of worker jobs (embeddings/rollups/reconcile) with retries/DLQ (ADR-0005).';

-- 13.4 configuration (typed config store; org or global)
CREATE TABLE configuration (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES organization(id) ON DELETE CASCADE, -- NULL = global
    key             text NOT NULL,
    value           jsonb NOT NULL,
    updated_by      uuid REFERENCES app_user(id) ON DELETE SET NULL,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT configuration_scope_key UNIQUE (organization_id, key)
);
COMMENT ON TABLE configuration IS 'Runtime configuration values (org-scoped or global). Non-secret only.';

-- 13.5 secret_reference (POINTER to a secret in the secrets manager; NEVER the value) — ADR-0011
CREATE TABLE secret_reference (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    name            text NOT NULL,
    provider        text NOT NULL,                        -- 'aws_secrets_manager','vault','k8s_sealed'
    reference_path  text NOT NULL,                        -- e.g. 'secret/data/org/x/openai' (a PATH, not a value)
    version         text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    rotated_at      timestamptz,
    CONSTRAINT secret_reference_org_name_key UNIQUE (organization_id, name),
    -- Guardrail: reference_path must look like a path/ARN, not an inline secret.
    CONSTRAINT secret_reference_is_pointer_ck CHECK (length(reference_path) <= 512)
);
COMMENT ON TABLE secret_reference IS 'Reference/pointer to a secret in an external manager. Stores NO secret values (ADR-0011, NFR-SEC03).';

-- 13.6 webhook & webhook_delivery
CREATE TABLE webhook (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    url             text NOT NULL,
    events          text[] NOT NULL DEFAULT '{}',         -- subscribed event types
    secret_ref      uuid REFERENCES secret_reference(id) ON DELETE SET NULL, -- signing secret reference
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT webhook_url_ck CHECK (url ~* '^https://')
);
COMMENT ON TABLE webhook IS 'Outbound webhook subscription; signing secret referenced, not stored (ADR-0011).';

CREATE TABLE webhook_delivery (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    webhook_id      uuid NOT NULL REFERENCES webhook(id) ON DELETE CASCADE,
    event_type      text NOT NULL,
    payload         jsonb NOT NULL,
    status          webhook_delivery_status NOT NULL DEFAULT 'pending',
    attempts        integer NOT NULL DEFAULT 0,
    response_code   integer,
    created_at      timestamptz NOT NULL DEFAULT now(),
    delivered_at    timestamptz,
    CONSTRAINT webhook_delivery_attempts_ck CHECK (attempts >= 0)
);
COMMENT ON TABLE webhook_delivery IS 'Per-attempt webhook delivery record with retry/DLQ status.';

-- ---------------------------------------------------------------------------
-- 13.7 Deferred foreign keys (forward references resolved after all tables)
-- ---------------------------------------------------------------------------
ALTER TABLE provider
    ADD CONSTRAINT provider_secret_ref_fk
    FOREIGN KEY (credential_secret_ref) REFERENCES secret_reference(id) ON DELETE SET NULL;

-- ===========================================================================
-- 14. INDEXES (every index justified in Indexing_Strategy.md)
-- ===========================================================================
-- Tenant-scoped access patterns: (organization_id, ...) leading columns.
CREATE INDEX ix_app_user_org              ON app_user (organization_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_oauth_identity_user       ON oauth_identity (user_id);
CREATE INDEX ix_service_account_org       ON service_account (organization_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_sa_credential_account     ON service_account_credential (service_account_id) WHERE status = 'active';
CREATE INDEX ix_session_user              ON session (user_id);
CREATE INDEX ix_session_expiry            ON session (expires_at);
CREATE INDEX ix_refresh_token_session     ON refresh_token (session_id);
CREATE INDEX ix_membership_org            ON membership (organization_id);
CREATE INDEX ix_membership_user           ON membership (user_id);
CREATE INDEX ix_role_permission_perm      ON role_permission (permission_id);
CREATE INDEX ix_project_org               ON project (organization_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_project_member_user       ON project_member (user_id);
CREATE INDEX ix_api_key_org_project       ON api_key (organization_id, project_id) WHERE status = 'active';
CREATE INDEX ix_api_key_scope_org         ON api_key_scope (organization_id);
CREATE INDEX ix_provider_org              ON provider (organization_id) WHERE is_enabled;
CREATE INDEX ix_model_org                 ON model (organization_id) WHERE is_enabled;
CREATE INDEX ix_model_provider            ON model (provider_id);
CREATE INDEX ix_price_table_model_current ON price_table (model_id, effective_from DESC);
CREATE INDEX ix_provider_health_provider  ON provider_health (provider_id, observed_at DESC);
CREATE INDEX ix_routing_policy_org        ON routing_policy (organization_id) WHERE is_active;
CREATE INDEX ix_routing_rule_policy       ON routing_policy_rule (routing_policy_id, priority);
CREATE INDEX ix_prompt_template_org       ON prompt_template (organization_id);
CREATE INDEX ix_prompt_version_template   ON prompt_version (prompt_template_id, version DESC);
CREATE INDEX ix_semantic_cache_expiry     ON semantic_cache_entry (expires_at);
CREATE INDEX ix_semantic_cache_org        ON semantic_cache_entry (organization_id);
-- pgvector ANN index (HNSW, cosine) — semantic cache lookup (ADR-0006, NFR-P03)
CREATE INDEX ix_embedding_hnsw            ON embedding USING hnsw (vector vector_cosine_ops);
CREATE INDEX ix_embedding_org             ON embedding (organization_id);
CREATE INDEX ix_budget_scope             ON budget (organization_id, scope, scope_id) WHERE is_active;
CREATE INDEX ix_reservation_status        ON reservation (status, expires_at);
CREATE INDEX ix_reservation_budget        ON reservation (budget_id);
CREATE INDEX ix_usage_ledger_org_time     ON usage_ledger (organization_id, created_at DESC);
CREATE INDEX ix_usage_ledger_request      ON usage_ledger (request_id);
CREATE INDEX ix_usage_rollup_lookup       ON usage_rollup (organization_id, bucket_date DESC);
CREATE INDEX ix_invoice_account           ON invoice (billing_account_id, period_start DESC);
CREATE INDEX ix_rate_limit_scope          ON rate_limit_policy (organization_id, scope, scope_id) WHERE is_active;
CREATE INDEX ix_audit_event_org_time      ON audit_event (organization_id, created_at DESC);
CREATE INDEX ix_audit_event_action        ON audit_event (organization_id, action, created_at DESC);
CREATE INDEX ix_governance_policy_org     ON governance_policy (organization_id);
CREATE INDEX ix_feature_flag_key          ON feature_flag (key);
CREATE INDEX ix_notification_org_status   ON notification (organization_id, status);
CREATE INDEX ix_background_job_poll       ON background_job (status, available_at) WHERE status IN ('queued','failed');
CREATE INDEX ix_configuration_org         ON configuration (organization_id);
CREATE INDEX ix_secret_reference_org      ON secret_reference (organization_id);
CREATE INDEX ix_webhook_org               ON webhook (organization_id) WHERE is_active;
CREATE INDEX ix_webhook_delivery_hook     ON webhook_delivery (webhook_id, created_at DESC);

-- ADR-0015: single-use OIDC login state (state/nonce/PKCE) between /authorize and /callback.
-- Consumed atomically via DELETE .. RETURNING; TTL = 5 minutes; swept every minute.
CREATE TABLE oidc_login_state (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    state_hash            bytea NOT NULL,          -- sha256(state); raw state never stored
    nonce_hash            bytea NOT NULL,          -- sha256(nonce); id_token nonce checked against this
    code_verifier         text NOT NULL,           -- PKCE secret; deleted on consume
    code_challenge_method text NOT NULL DEFAULT 'S256',
    provider              text NOT NULL,
    redirect_uri          text NOT NULL,
    return_to             text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    expires_at            timestamptz NOT NULL,
    CONSTRAINT oidc_login_state_state_hash_key UNIQUE (state_hash)
);
CREATE INDEX ix_oidc_login_state_expires ON oidc_login_state (expires_at);

-- ===========================================================================
-- 15. ROW-LEVEL SECURITY (representative; full policy set in RLS_Strategy.md)
--     Session sets: SET app.current_org = '<uuid>'; workers use a bypass role.
-- ===========================================================================
-- Helper expression: NULLIF(current_setting('app.current_org', true), '')::uuid
-- Enable + FORCE RLS on tenant-owned tables; policy restricts to current org.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'app_user','oauth_identity','service_account','service_account_credential','oidc_login_state','session','refresh_token',
    'membership','project','project_member','api_key','api_key_scope',
    'provider','model','price_table','provider_health','routing_policy',
    'routing_policy_rule','prompt_template','prompt_version','embedding',
    'semantic_cache_entry','budget','reservation','usage_rollup',
    'billing_account','invoice','rate_limit_policy','governance_policy',
    'notification','configuration','secret_reference','webhook','webhook_delivery'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', t);
    EXECUTE format($p$CREATE POLICY %1$s_tenant_isolation ON %1$I
                      USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
                      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);$p$, t);
  END LOOP;
END $$;
-- Partitioned tables (usage_ledger, audit_event) get RLS on the parent; see RLS_Strategy.md.
ALTER TABLE usage_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_ledger FORCE ROW LEVEL SECURITY;
CREATE POLICY usage_ledger_tenant_isolation ON usage_ledger
    USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);
ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_event FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_event_tenant_isolation ON audit_event
    USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);

-- Append-only enforcement for audit_event & usage_ledger is via role grants
-- (no UPDATE/DELETE to application roles) — see RLS_Strategy.md & Migration_Strategy.md.

-- ===========================================================================
-- 16. RUNTIME DATABASE ROLE (ADR-0014; realizes RLS_Strategy.md §4 app_rw)
--     RLS is bypassed by superusers and BYPASSRLS roles EVEN UNDER FORCE, so the
--     application must connect as a least-privilege, RLS-subject role. Applied by
--     migration 0003_database_roles (runs as the schema owner). LOGIN/password are
--     set per-environment (dev: docker initdb; prod: ops/secret manager), never here.
-- ---------------------------------------------------------------------------
--   CREATE ROLE app_rw NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE INHERIT;
--   GRANT USAGE ON SCHEMA public TO app_rw;
--   GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw;
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
--   REVOKE UPDATE, DELETE ON audit_event, usage_ledger FROM app_rw;   -- append-only
--   ALTER DEFAULT PRIVILEGES IN SCHEMA public
--     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;       -- future tables
--   ALTER DEFAULT PRIVILEGES IN SCHEMA public
--     GRANT USAGE, SELECT ON SEQUENCES TO app_rw;
-- Deferred to their milestones (RLS_Strategy §4): app_worker, app_reconciler, rls_bypass.

-- ============================================================================
-- End of schema. Global reference tables (permission, system role) and
-- seed data are applied via migrations — see Migration_Strategy.md.
-- ============================================================================
