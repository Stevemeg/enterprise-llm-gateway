# ADR-0014: Non-superuser runtime database role for RLS enforcement

- **Status:** Accepted (2026-07-18 — realized in Milestone 3d-2A.5, migration 0003)
- **Date:** 2026-07-18
- **Deciders:** Security Architect, Database Architect, Principal Architect, SRE
- **Phase:** 5 — Backend (Milestone 3d validation)
- **Realizes:** [RLS_Strategy.md](../RLS_Strategy.md) §4 (database role model), deferred from Phase 3
- **Affects:** ADR-0002 (tenant isolation), NFR-SEC07; adds DB roles + grants (no table changes)

## Context & problem
Tenant isolation is enforced by PostgreSQL **Row-Level Security** with `FORCE ROW LEVEL SECURITY`
on every tenant-owned table (ADR-0002, [RLS_Strategy.md](../RLS_Strategy.md)). RLS has one hard
exception the schema cannot override: **superusers and roles with `BYPASSRLS` are never subject to
policies — `FORCE` does not apply to them.**

The approved Phase-3 design already accounts for this: [RLS_Strategy.md](../RLS_Strategy.md) §4
mandates a least-privilege **`app_rw`** role (NOBYPASSRLS, subject to RLS) for the API request path,
with `BYPASSRLS` confined to a separate audited `rls_bypass` maintenance role, and §7 lists a
**"bypass containment"** test asserting request-serving roles do *not* have `BYPASSRLS`. That role
model was annotated "created in migrations, step 16" — but **it was never implemented.** Migration
`0001` enables RLS and creates policies; it creates **no roles and no grants.**

Consequently, today:
- `docker-compose.dev.yml` provisions the database as user **`gateway`**, which the Postgres image
  creates as a **superuser** (`rolsuper=t`, `rolbypassrls=t`).
- The application and the integration tests connect as `gateway`. **Every query bypasses RLS.**
- The Milestone 3d RLS integration test (`test_auth_rls_postgres.py`), run in Gate 2 as written,
  binds tenant B, reads tenant A's credential, **receives the row** (RLS bypassed), and its
  `assert ... is None` turns **red** — a false failure. There is no way to reach the required
  "0 skipped, all green" Gate-2 state while connected as a superuser.

This was verified empirically on a real PostgreSQL 14 instance mirroring the schema
(`organization → service_account → service_account_credential`, `ENABLE`+`FORCE` RLS, tenant policy):

| Connection role | Bound tenant | Reads other tenant's row? |
|-----------------|--------------|---------------------------|
| `gateway` (superuser, BYPASSRLS) | B (wrong) | **YES** — RLS bypassed |
| `app_rw`-equivalent (NOSUPERUSER, NOBYPASSRLS) | B (wrong) | **NO** — RLS enforced |
| `app_rw`-equivalent | A (own) | YES — correct |

The problem is therefore **not** the test — it is that the runtime never uses the non-superuser role
the architecture already requires. Left unaddressed in production, an app connecting as a
superuser/BYPASSRLS role makes tenant isolation (NFR-SEC07) a **silent no-op**.

## Decision drivers
- **NFR-SEC07** (tenant isolation must be DB-enforced, not app-enforced), **ADR-0002**.
- **RLS_Strategy.md §4/§5/§7** — the role model and bypass-containment test are already approved.
- The Milestone-3d Gate-2 requirement: the Postgres RLS test must **run and pass** (0 skipped).
- No-secret / least-privilege posture; append-only guarantees (§4) must not regress.
- Minimize scope now — only what is needed to close the RLS gap for the authenticated read/write
  path; defer worker/reconciler roles to their functional milestones.

## Options considered
### Option A — Test-only: ephemeral `SET ROLE` inside the RLS test
The test creates a throwaway `NOBYPASSRLS` role and `SET ROLE`s to it before querying.
- **Pros:** Zero schema/infra change; makes the one test green immediately.
- **Cons:** Leaves the **production** superuser-bypass gap open — the app itself would still bypass
  RLS in dev and (if provisioned the same way) prod. It also tests a *synthetic* role, not the role
  the app actually runs as, so it proves less than it appears to. Contradicts RLS_Strategy §7
  (bypass containment is about the *request-serving* role). Rejected as the primary fix.

### Option B — Realize `app_rw` now (minimal slice of RLS_Strategy §4) — **chosen**
Create the least-privilege **`app_rw`** login role (NOSUPERUSER, NOBYPASSRLS) plus a `migrator`
owner concept via a forward-only migration; grant `app_rw` exactly the DML it needs on tenant tables
(no `UPDATE/DELETE` on `audit_event`/`usage_ledger` — append-only), subject to RLS. The application
connects as `app_rw`; migrations run as the owner/superuser; the RLS integration test connects (or
`SET ROLE`s) as `app_rw` and therefore exercises the **real** runtime role.
- **Pros:** Fixes the test **and** the production gap with one change; the test now validates the
  exact role the app uses; directly satisfies RLS_Strategy §4/§7 and NFR-SEC07; small, well-scoped.
- **Cons:** Grants must be extended whenever new tables are added (mitigated by `ALTER DEFAULT
  PRIVILEGES` + a migration convention + a CI grant-coverage check); requires a second connection
  identity (owner for DDL, `app_rw` for runtime).

### Option C — Realize the entire §4 role model now (`app_rw` + `app_worker` + `app_reconciler` + `migrator` + `rls_bypass`)
- **Pros:** Complete, matches §4 in full.
- **Cons:** `app_worker`/`app_reconciler`/`rls_bypass` serve subsystems not built yet (metering,
  reconciliation, archival). Building their grants now is speculative and would drift before those
  milestones. Violates "one concern per slice." Deferred — each role lands with its subsystem.

## Decision
Adopt **Option B.** Introduce, via a new forward-only migration **`0003_database_roles`**, the
least-privilege request-path role and the runtime/DDL split the architecture already specifies —
scoped to what the authenticated request path needs today:

- **`app_rw`** — `LOGIN`, `NOSUPERUSER`, `NOBYPASSRLS`. Granted `SELECT/INSERT/UPDATE/DELETE` on
  tenant-owned tables **except** `UPDATE/DELETE` are **revoked** on `audit_event` and `usage_ledger`
  (append-only, RLS_Strategy §4; belt-and-suspenders with policy). `USAGE` on sequences/schema.
- **`app_ddl` / migrator (owner)** — owns the schema and runs migrations; **not** used at runtime.
  In dev this is the existing `gateway` superuser (keeps compose simple); the ADR records that in
  production these are distinct principals.
- **`ALTER DEFAULT PRIVILEGES`** so future tables created by the owner are automatically granted to
  `app_rw`, and a **grant-coverage check** (extends the Local_Validation grant-drift guard) so a new
  tenant table without an `app_rw` grant fails CI.

`app_worker`, `app_reconciler`, and `rls_bypass` (RLS_Strategy §4) are **explicitly deferred** to the
metering/reconciliation/archival milestones and will be added by their own migrations.

### Runtime wiring
- The application connects to Postgres as **`app_rw`**; migrations run as the owner. In dev,
  `docker-compose.dev.yml` creates the `app_rw` login role (via an init script or the `0003`
  migration) with a dev password; `.env.example` gains a distinct `GATEWAY_DATABASE__URL` for
  `app_rw` and documents that the migration URL uses the owner.
- The RLS integration test connects as (or `SET ROLE`s to) `app_rw`, so it validates the **real**
  request-path role. Bound to the wrong tenant it must read **zero** rows; bound to its own tenant it
  reads its row. This turns `test_auth_rls_postgres.py` into a *positive* enforcement test (it goes
  green **because** RLS blocks the cross-tenant read), not a skipped/failing one.

## Consequences
- **Positive:** Tenant isolation becomes real in every environment; the Gate-2 RLS test passes and
  proves enforcement against the production role; RLS_Strategy §4/§7 partially realized; a
  bypass-containment assertion (`app_rw` lacks `BYPASSRLS`) can be added to the validation gate.
- **Negative / obligations:** Every future migration that adds a tenant table must grant `app_rw`
  (enforced by the grant-coverage check + `ALTER DEFAULT PRIVILEGES`). Two connection identities to
  manage. Dev password handling for `app_rw` (documented; real secrets via secret_reference/ADR-0011
  in prod).
- **Follow-ups:** add the append-only `UPDATE/DELETE`-denied test and the bypass-containment test to
  the Phase-13 isolation suite (RLS_Strategy §7); land `app_worker`/`app_reconciler`/`rls_bypass`
  with their subsystems.

## Change set (to apply upon approval — not yet implemented)
1. `backend/migrations/versions/0003_database_roles.py` + `backend/migrations/sql/0003_database_roles.sql`
   (create `app_rw`; grants; revokes on append-only tables; `ALTER DEFAULT PRIVILEGES`). Forward-only;
   idempotent role creation (`DO $$ ... IF NOT EXISTS`).
2. `docs/Schema.sql` — add the §16 role-model block (current-state reference; `0001` snapshot unchanged).
3. `docker-compose.dev.yml` — provision the `app_rw` login role for Gate 2.
4. `backend/.env.example` — document the owner (migration) URL vs the `app_rw` (runtime) URL.
5. `backend/tests/integration/test_auth_rls_postgres.py` — connect/`SET ROLE` as `app_rw`; keep the
   skip only when no Postgres URL is present, so Gate 2 runs it (0 skipped).
6. `scripts/validate.*` + `docs/Local_Validation_Guide.md` — run the RLS test in Gate 2; add the
   bypass-containment + grant-coverage checks.
7. Doc updates: `RLS_Strategy.md` (§4 status → realized-in-part, cite ADR-0014), `Database_Design.md`,
   `Data_Dictionary.md` (role model), `Security_Traceability.md`, ADR index in `docs/adr/README.md`.

## Requirements satisfied
- Non-functional: **NFR-SEC07** (DB-enforced tenant isolation), least-privilege; realizes
  RLS_Strategy §4/§5/§7; upholds ADR-0002, ADR-0009 (deny-by-default), ADR-0011 (secret handling).

## Review notes
Revisit when the metering/reconciliation/archival milestones land (add `app_worker`,
`app_reconciler`, `rls_bypass`), or if deployment adopts managed-Postgres role tooling (e.g., IAM
auth) that changes how the runtime role authenticates.
