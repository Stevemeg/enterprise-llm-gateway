-- ADR-0014: least-privilege runtime role so PostgreSQL RLS actually enforces tenant
-- isolation (superusers/BYPASSRLS roles are NEVER subject to policies, even under FORCE).
-- Realizes RLS_Strategy.md §4 (app_rw), deferred from Phase 3. Forward-only, idempotent.
--
-- Runtime/DDL split: this migration runs as the schema OWNER (the migrator). The application
-- connects at runtime as `app_rw`, which is NOSUPERUSER + NOBYPASSRLS and therefore subject
-- to every RLS policy. Passwords/LOGIN are environment-specific and set out-of-band (dev: the
-- docker initdb script; prod: ops/secret manager) — never stored in migrations.

-- 1. Ensure the role exists with the correct security attributes (idempotent).
--    CREATE with no LOGIN/password here; environments grant LOGIN + password separately.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        CREATE ROLE app_rw NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE INHERIT;
    ELSE
        -- Re-assert the safety-critical attributes even if the role pre-exists.
        ALTER ROLE app_rw NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END $$;

-- 2. Schema + sequence usage.
GRANT USAGE ON SCHEMA public TO app_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw;

-- 3. DML on all existing tables (tenant tables are RLS-guarded; global reference tables are
--    read-mostly and still policy-free by design — RLS_Strategy.md §3).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;

-- 4. Append-only enforcement via privilege (belt-and-suspenders with the hash chain and
--    policies): the request path may INSERT but never UPDATE/DELETE the immutable logs
--    (RLS_Strategy.md §4; FR-113/114; NFR-SEC09). Applies to the partitioned parents.
REVOKE UPDATE, DELETE ON audit_event  FROM app_rw;
REVOKE UPDATE, DELETE ON usage_ledger FROM app_rw;

-- 5. Future tables/sequences created by the owner are auto-granted to app_rw, so a new
--    tenant table cannot silently become unreachable (or, worse, be reached only via a
--    BYPASSRLS role). A CI grant-coverage check backs this up.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_rw;
