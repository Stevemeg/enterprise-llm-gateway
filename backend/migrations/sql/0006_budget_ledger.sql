-- ADR-0017: durable, tenant-scoped budget ledger for atomic reserve/commit (ADR-0016 Slice 9).
--
-- Deliberately narrower than, and deliberately NOT reusing, the Phase-1 illustrative
-- `budget` / `reservation` / `usage_ledger` tables created in 0001_initial.sql: those model
-- hierarchical org/project/api_key scope and a provider/model catalog FK that no current
-- capability populates, and type their request identity as `uuid NOT NULL` /
-- `UNIQUE (request_id)` (globally unique) — but `InferenceRequest.correlation_id` (Slice 7) is
-- an arbitrary caller-supplied `str`, not a UUID, and has no reason to be globally unique across
-- tenants. See ADR-0017 for the full analysis. These new tables model exactly what
-- BudgetPort/PricingPort/CostAccountant (Slice 8) already define: organization-scoped, no
-- catalog FK, `correlation_id text`, identity `UNIQUE (organization_id, correlation_id)`.

-- 1. org_budget — one hard limit per organization, with a running reserved/spent total.
--    The atomic primitive: `UPDATE ... WHERE (amount_limit - spent - reserved) >= [cost]` is a
--    single indivisible read-check-write statement — Postgres's own atomicity, not an invented one.
CREATE TABLE org_budget (
    organization_id uuid PRIMARY KEY REFERENCES organization(id) ON DELETE CASCADE,
    amount_limit    numeric(18,8) NOT NULL,
    currency        char(3) NOT NULL,
    reserved        numeric(18,8) NOT NULL DEFAULT 0,
    spent           numeric(18,8) NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT org_budget_amount_ck   CHECK (amount_limit >= 0),
    CONSTRAINT org_budget_reserved_ck CHECK (reserved >= 0),
    CONSTRAINT org_budget_spent_ck    CHECK (spent >= 0)
);
COMMENT ON TABLE org_budget IS
    'One hard budget per organization with a live reserved/spent total (ADR-0017). '
    'Narrower than Schema.sql''s illustrative `budget` — no project/api_key scope or period '
    'rollover exists yet because nothing consumes them (Rule 5).';

-- 2. budget_reservation — durable reserve/commit/release record, keyed by the caller's own
--    identifier. UNIQUE (organization_id, correlation_id) is the idempotency guarantee: it is
--    tenant-scoped because correlation_id is only ever meaningful within one tenant's requests.
CREATE TABLE budget_reservation (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    correlation_id  text NOT NULL,
    estimated_cost  numeric(18,8) NOT NULL,
    actual_cost     numeric(18,8),
    currency        char(3) NOT NULL,
    status          reservation_status NOT NULL DEFAULT 'reserved',
    created_at      timestamptz NOT NULL DEFAULT now(),
    settled_at      timestamptz,
    CONSTRAINT budget_reservation_cost_ck
        CHECK (estimated_cost >= 0 AND (actual_cost IS NULL OR actual_cost >= 0)),
    CONSTRAINT budget_reservation_org_correlation_key UNIQUE (organization_id, correlation_id)
);
COMMENT ON TABLE budget_reservation IS
    'Reserve/commit/release record (ADR-0017). Reuses the reservation_status enum from '
    '0001_initial.sql (reserved/committed/released/expired) — the enum type, not the table.';

-- 3. cost_ledger — append-only actual-cost record, written once at settlement. Not the
--    double-entry `usage_ledger` from 0001_initial.sql: CostAccountant (Slice 8) produces one
--    CostRecord per call, not paired debit/credit rows, and nothing here consumes double-entry.
CREATE TABLE cost_ledger (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id   uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    correlation_id    text NOT NULL,
    provider          text NOT NULL,
    model             text NOT NULL,
    prompt_tokens     integer NOT NULL,
    completion_tokens integer NOT NULL,
    input_cost        numeric(18,8) NOT NULL,
    output_cost       numeric(18,8) NOT NULL,
    total_cost        numeric(18,8) NOT NULL,
    currency          char(3) NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cost_ledger_tokens_ck CHECK (prompt_tokens >= 0 AND completion_tokens >= 0),
    CONSTRAINT cost_ledger_cost_ck   CHECK (input_cost >= 0 AND output_cost >= 0 AND total_cost >= 0),
    CONSTRAINT cost_ledger_org_correlation_key UNIQUE (organization_id, correlation_id)
);
COMMENT ON TABLE cost_ledger IS
    'Append-only settled cost record (ADR-0017/Slice 9). One row per settled correlation_id.';

CREATE INDEX ix_budget_reservation_org_status ON budget_reservation (organization_id, status);
CREATE INDEX ix_cost_ledger_org_time          ON cost_ledger (organization_id, created_at DESC);

-- RLS: same NULLIF-safe policy shape as every other tenant table (migration 0005).
ALTER TABLE org_budget ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_budget FORCE ROW LEVEL SECURITY;
CREATE POLICY org_budget_tenant_isolation ON org_budget
    USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);

ALTER TABLE budget_reservation ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_reservation FORCE ROW LEVEL SECURITY;
CREATE POLICY budget_reservation_tenant_isolation ON budget_reservation
    USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);

ALTER TABLE cost_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_ledger FORCE ROW LEVEL SECURITY;
CREATE POLICY cost_ledger_tenant_isolation ON cost_ledger
    USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);

-- Append-only enforcement for cost_ledger, mirroring audit_event/usage_ledger (migration 0003):
-- the request path may INSERT but never UPDATE/DELETE a settled cost record.
REVOKE UPDATE, DELETE ON cost_ledger FROM app_rw;
