-- Fix: tenant RLS policies raised invalid_text_representation on pooled connections.
--
-- set_config('app.current_org', ..., true) is TRANSACTION-local. After that transaction commits,
-- the GUC on that (pooled, reused) connection reads back as an EMPTY STRING rather than NULL, so
-- `current_setting('app.current_org', true)::uuid` evaluated ''::uuid and raised
--     ERROR: invalid input syntax for type uuid: ""
-- instead of matching zero rows. Deny-by-default therefore errored rather than filtering - a
-- correctness/availability defect (it fails closed, so it was never an isolation bypass).
--
-- NULLIF(..., '') maps both "never set" and "reset after a transaction" to NULL, and
-- `organization_id = NULL` is NULL => no rows. Deny-by-default now behaves as documented.
--
-- Recreated dynamically from pg_policies so EVERY tenant-isolation policy is covered, including
-- ones added after the initial schema (service_account_credential, oidc_login_state).
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT tablename
        FROM pg_policies
        WHERE schemaname = 'public'
          AND policyname = tablename || '_tenant_isolation'
    LOOP
        EXECUTE format('DROP POLICY %I ON %I;', r.tablename || '_tenant_isolation', r.tablename);
        EXECUTE format(
            $p$CREATE POLICY %1$s_tenant_isolation ON %1$I
                 USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
                 WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);$p$,
            r.tablename);
    END LOOP;
END $$;
