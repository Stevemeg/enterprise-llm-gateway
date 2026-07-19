-- ADR-0015: OIDC login state (state/nonce/PKCE) persisted between /authorize and /callback.
-- Tenant-scoped and RLS-protected like every other tenant table (no guardrail exemption).
-- Single-use is enforced by atomic `DELETE ... RETURNING` on consume; TTL = 5 minutes.
CREATE TABLE oidc_login_state (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    state_hash            bytea NOT NULL,          -- sha256(state random part); raw state never stored
    nonce_hash            bytea NOT NULL,          -- sha256(nonce); id_token nonce verified against this
    code_verifier         text NOT NULL,           -- PKCE secret sent at token exchange; deleted on consume
    code_challenge_method text NOT NULL DEFAULT 'S256',
    provider              text NOT NULL,           -- configured IdP identifier
    redirect_uri          text NOT NULL,           -- our callback URI (exact-match on return)
    return_to             text,                    -- post-login destination (allow-list validated)
    created_at            timestamptz NOT NULL DEFAULT now(),
    expires_at            timestamptz NOT NULL,    -- TTL = 5 min; past ⇒ treated as absent (fail closed)
    CONSTRAINT oidc_login_state_state_hash_key UNIQUE (state_hash)
);
COMMENT ON TABLE oidc_login_state IS 'Single-use OIDC login state (ADR-0015); consumed via DELETE..RETURNING.';

-- Supports the every-minute expiry sweep (active cleanup, ADR-0015).
CREATE INDEX ix_oidc_login_state_expires ON oidc_login_state (expires_at);

ALTER TABLE oidc_login_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE oidc_login_state FORCE ROW LEVEL SECURITY;
CREATE POLICY oidc_login_state_tenant_isolation ON oidc_login_state
    USING (organization_id = current_setting('app.current_org', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_org', true)::uuid);
