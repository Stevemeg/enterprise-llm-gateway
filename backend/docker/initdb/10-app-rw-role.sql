-- DEV/GATE-2 ONLY. Runs once at cluster initialization (docker-entrypoint-initdb.d), as the
-- POSTGRES_USER superuser. Creates the app_rw LOGIN role with a well-known *development*
-- password so the app and integration tests can connect as the least-privilege runtime role
-- (ADR-0014). Grants are applied later by migration 0003 (which runs as the owner after the
-- tables exist). In production, app_rw's LOGIN + password are provisioned by ops/secret
-- management — NOT by this file, and NOT by any migration.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        CREATE ROLE app_rw LOGIN PASSWORD 'app_rw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE INHERIT;
    END IF;
END $$;
