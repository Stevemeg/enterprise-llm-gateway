-- ADR-0013: service-account client credentials (hashed, rotatable, RLS-scoped).
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
COMMENT ON TABLE service_account_credential IS 'Hashed client-credential for a service account (ADR-0013).';

CREATE INDEX ix_sa_credential_account ON service_account_credential (service_account_id)
    WHERE status = 'active';

ALTER TABLE service_account_credential ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_account_credential FORCE ROW LEVEL SECURITY;
CREATE POLICY service_account_credential_tenant_isolation ON service_account_credential
    USING (organization_id = current_setting('app.current_org', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_org', true)::uuid);
