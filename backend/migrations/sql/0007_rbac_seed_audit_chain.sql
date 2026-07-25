-- ADR-0016 Slice 18: durable RBAC storage + hash-chained audit sink.
--
-- Five independent concerns, each justified below:
--   1. RBAC reference data (ADR-0008)      - the catalog and system roles the resolver reads.
--   2. audit_chain_head (ADR-0009)         - the authoritative per-tenant hash-chain head.
--   3. audit_event DEFAULT partition       - the log had partitions only to 2026-09-01.
--   4. Partition hardening                 - parent RLS/REVOKE do NOT cover direct partition access.
--   5. API-key bootstrap lookup (ADR-0019) - resolve a tenant from a credential under RLS.
--
-- Unlike migration 0006 (ADR-0017) this migration deliberately DOES reuse the Phase-1 tables:
-- role/permission/role_permission/membership and audit_event model exactly what
-- PermissionResolver and AuthAuditSink need, with no unused dimension forcing a narrower
-- redesign. Where a Phase-1 column cannot represent an application fact (audit_event's
-- organization_id is NOT NULL; AuthAuditEvent's is optional for a rejection) the SINK adapts and
-- the schema is left alone - see adapters/audit/sql_sink.py.

-- ===========================================================================
-- 1. RBAC REFERENCE DATA (ADR-0008 role -> permission matrix)
--    No migration had ever seeded these, so `role`, `permission` and `role_permission` were
--    empty: a durable resolver would have resolved every principal to nothing.
-- ===========================================================================

-- Fine-grained permission catalog. Global reference data (no organization_id, no RLS).
INSERT INTO permission (key, description) VALUES
    ('tenant:manage',    'Manage the organization itself (ADR-0008; owner only).'),
    ('team:manage',      'Create and modify teams/projects.'),
    ('member:invite',    'Invite and remove organization members.'),
    ('key:issue',        'Issue virtual API keys.'),
    ('key:revoke',       'Revoke virtual API keys.'),
    ('provider:write',   'Register and configure providers.'),
    ('model:write',      'Register and configure models.'),
    ('routing:write',    'Author routing policy.'),
    ('policy:write',     'Author governance policy.'),
    ('budget:write',     'Create and change budgets.'),
    ('budget:read',      'Read budgets and remaining allowance.'),
    ('usage:read',       'Read usage and cost reporting.'),
    ('audit:read',       'Read the audit log.'),
    ('inference:invoke', 'Execute an inference request (POST /v1/inference).')
ON CONFLICT (key) DO NOTHING;

-- The six v1 system roles (FR-098). organization_id IS NULL => global system role, which is why
-- `role` is exempt from the tenant-RLS guardrail (RLS_Strategy.md §3/§10).
-- NOT ON CONFLICT: role_scope_key is UNIQUE (organization_id, key) and PostgreSQL treats NULLs as
-- distinct, so a conflict target on (organization_id, key) would never match a system role.
INSERT INTO role (organization_id, key, name, is_system)
SELECT NULL, seed.key, seed.name, true
FROM (VALUES
    ('owner',     'Owner'),
    ('admin',     'Administrator'),
    ('operator',  'Operator'),
    ('finance',   'Finance'),
    ('auditor',   'Auditor'),
    ('developer', 'Developer')
) AS seed(key, name)
WHERE NOT EXISTS (
    SELECT 1 FROM role existing
    WHERE existing.organization_id IS NULL AND existing.key = seed.key
);

-- ADR-0008's role -> permission matrix, verbatim.
--
-- `inference:invoke` is deliberately granted to NO human role. ADR-0008's matrix ends with
-- "infer:chat / infer:embed (via keys) - application principals only -", so inference authority
-- belongs to virtual keys (api_key_scope), not to admin roles. That is why Slice 18 must wire
-- API-key verification as well: without it the inference endpoint has no principal type that can
-- ever be authorized, and durable RBAC alone would not unblock it.
INSERT INTO role_permission (role_id, permission_id)
SELECT r.id, p.id
FROM (VALUES
    ('owner',     'tenant:manage'),
    ('owner',     'team:manage'),
    ('owner',     'member:invite'),
    ('owner',     'key:issue'),
    ('owner',     'key:revoke'),
    ('owner',     'provider:write'),
    ('owner',     'model:write'),
    ('owner',     'routing:write'),
    ('owner',     'policy:write'),
    ('owner',     'budget:write'),
    ('owner',     'budget:read'),
    ('owner',     'usage:read'),
    ('owner',     'audit:read'),

    ('admin',     'team:manage'),
    ('admin',     'member:invite'),
    ('admin',     'key:issue'),
    ('admin',     'key:revoke'),
    ('admin',     'provider:write'),
    ('admin',     'model:write'),
    ('admin',     'routing:write'),
    ('admin',     'policy:write'),
    ('admin',     'budget:write'),
    ('admin',     'budget:read'),
    ('admin',     'usage:read'),
    ('admin',     'audit:read'),

    ('operator',  'provider:write'),
    ('operator',  'model:write'),
    ('operator',  'routing:write'),
    ('operator',  'policy:write'),
    ('operator',  'budget:read'),
    ('operator',  'usage:read'),

    ('finance',   'budget:write'),
    ('finance',   'budget:read'),
    ('finance',   'usage:read'),

    -- ADR-0008: "auditor is strictly read + audit:read" (satisfies AC-US-072).
    ('auditor',   'budget:read'),
    ('auditor',   'usage:read'),
    ('auditor',   'audit:read'),

    ('developer', 'budget:read'),
    ('developer', 'usage:read')
) AS grants(role_key, permission_key)
JOIN role r       ON r.organization_id IS NULL AND r.key = grants.role_key
JOIN permission p ON p.key = grants.permission_key
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ===========================================================================
-- 2. audit_chain_head - the authoritative per-tenant hash-chain head.
--
--    Deriving the previous hash with `ORDER BY created_at DESC LIMIT 1` is NOT sufficient:
--    two rows sharing a created_at make the predecessor ambiguous, and two writers that pick
--    the same predecessor FORK the chain while each looks individually valid. A single head row
--    per tenant makes the predecessor a fact rather than an inference, and gives the writer a
--    real row to lock.
--
--    Per-tenant rather than global: RLS confines every read to one organization, so a global
--    chain would be unverifiable by the only parties allowed to read it.
-- ===========================================================================
CREATE TABLE audit_chain_head (
    organization_id uuid PRIMARY KEY REFERENCES organization(id) ON DELETE CASCADE,
    entry_hash      bytea NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE audit_chain_head IS
    'Authoritative hash-chain head per organization (ADR-0016 Slice 18). Removes the ambiguity '
    'of deriving the previous hash by timestamp ordering, and is the row writers lock.';

ALTER TABLE audit_chain_head ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_chain_head FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_chain_head_tenant_isolation ON audit_chain_head
    USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);

-- ===========================================================================
-- 3. audit_event DEFAULT partition.
--    0001_initial created partitions for 2026-07 and 2026-08 only. Slice 18 is the first thing
--    that ever writes this table, so without a catch-all every audit INSERT would begin failing
--    with "no partition of relation found" on 2026-09-01. Losing audit records is worse than the
--    known cost of a default partition (adding a narrower partition later must scan it).
-- ===========================================================================
CREATE TABLE audit_event_default PARTITION OF audit_event DEFAULT;
COMMENT ON TABLE audit_event_default IS
    'Catch-all partition so an audit INSERT can never fail for want of a partition. Monthly '
    'partitions may be split out of it later (requires a scan of this table).';

-- ===========================================================================
-- 4. PARTITION HARDENING - closing a verified cross-tenant read and append-only bypass.
--
--    Verified against real PostgreSQL before writing this migration, as app_rw with tenant B
--    bound against a row owned by tenant A:
--        SELECT count(*) FROM audit_event           -> 0   (parent policy enforced)
--        SELECT count(*) FROM audit_event_2026_07   -> 1   <-- CROSS-TENANT READ
--        UPDATE audit_event_2026_07 SET action=...  -> 1   <-- APPEND-ONLY BYPASS
--        UPDATE audit_event ...                     -> ERROR: permission denied
--
--    Two independent causes, both invisible until something actually wrote the table:
--      * A parent's RLS policies are NOT applied when a partition is named directly, and
--        0001_initial enabled RLS only on the partitioned parents (pg_class.relrowsecurity was
--        false on every partition).
--      * 0003_database_roles ran `GRANT ... ON ALL TABLES` (which included the partitions) and
--        then revoked UPDATE/DELETE only on the parents.
--
--    Applied dynamically over pg_inherits so every existing partition is covered, including the
--    DEFAULT partition created above and usage_ledger's, which had the identical defect.
-- ===========================================================================
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT child.relname AS partition
        FROM pg_inherits i
        JOIN pg_class child  ON child.oid  = i.inhrelid
        JOIN pg_class parent ON parent.oid = i.inhparent
        WHERE parent.relname IN ('audit_event', 'usage_ledger')
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', r.partition);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', r.partition);
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = r.partition
              AND policyname = r.partition || '_tenant_isolation'
        ) THEN
            EXECUTE format(
                $p$CREATE POLICY %1$s_tenant_isolation ON %1$I
                     USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
                     WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);$p$,
                r.partition);
        END IF;
        -- Append-only, matching the parents (FR-113/114, NFR-SEC09). INSERT is untouched:
        -- PostgreSQL checks privileges on the relation named in the statement, so inserting
        -- through the parent still routes into a partition the app may not UPDATE.
        EXECUTE format('REVOKE UPDATE, DELETE ON %I FROM app_rw;', r.partition);
    END LOOP;
END $$;

-- ===========================================================================
-- 5. API-KEY CREDENTIAL BOOTSTRAP (ADR-0019)
--    Resolving a presented key to its tenant must happen BEFORE a tenant is known, but api_key
--    is RLS-scoped and app_rw is NOBYPASSRLS (ADR-0014, not negotiable). The sanctioned path is
--    one SECURITY DEFINER function exposing exactly one fact: which organization owns this exact
--    prefix. See ADR-0019 for the options rejected.
-- ===========================================================================

-- The owner needs its own policy because api_key is under FORCE ROW LEVEL SECURITY, which
-- subjects the owner to policies too. Relying on owner privileges alone would work only where the
-- owner happens to be a superuser - true in dev, and never to be assumed in production.
-- Scoped TO the owner role, resolved as current_user so no environment's owner is hard-coded.
-- app_rw is not that role, so app_rw cannot use this policy; its only access is via the function.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'api_key'
          AND policyname = 'api_key_bootstrap_lookup'
    ) THEN
        EXECUTE format(
            'CREATE POLICY api_key_bootstrap_lookup ON api_key FOR SELECT TO %I USING (true)',
            current_user);
    END IF;
END $$;

-- STABLE + LANGUAGE sql: one statement, no side effects. `SET search_path` is mandatory on a
-- SECURITY DEFINER function - without it the body is hijackable via a caller-controlled path.
CREATE OR REPLACE FUNCTION gateway_api_key_tenant(p_key_prefix text)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
    SELECT organization_id
    FROM public.api_key
    WHERE key_prefix = p_key_prefix
      AND status = 'active'
    LIMIT 1;
$fn$;

COMMENT ON FUNCTION gateway_api_key_tenant(text) IS
    'ADR-0019 credential bootstrap: maps an EXACT non-secret api_key prefix to its owning '
    'organization and nothing else. Exact match only - no enumeration, no hash, no scopes. '
    'Authorised for credential bootstrap only; any further SECURITY DEFINER needs its own ADR.';

REVOKE ALL ON FUNCTION gateway_api_key_tenant(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gateway_api_key_tenant(text) TO app_rw;
