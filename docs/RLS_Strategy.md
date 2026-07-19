# Row-Level Security (RLS) Strategy

**Phase:** 3 — Database Architecture · Draft for approval
**Last updated:** 2026-07-15

RLS is the **database-enforced backstop** for tenant isolation, layered under application-level tenant
scoping (defense in depth) per **ADR-0002**. It ensures that a missed `WHERE organization_id = …` in
application code **cannot** leak cross-tenant data (FR-131/132, NFR-SEC07, RISK-T05). This document
defines the session model, policies, role model, append-only enforcement, worker/bypass handling, and
testing.

## 1. Model
- Every **tenant-owned** table has `organization_id uuid NOT NULL` and **`ENABLE` + `FORCE ROW LEVEL
  SECURITY`** (FORCE so even the table owner is subject to policies).
- A single policy per table restricts both **reads** (`USING`) and **writes** (`WITH CHECK`) to the
  session's current organization:

```sql
CREATE POLICY <table>_tenant_isolation ON <table>
  USING      (organization_id = current_setting('app.current_org', true)::uuid)
  WITH CHECK (organization_id = current_setting('app.current_org', true)::uuid);
```

- The application sets the tenant context **once per request/connection**, derived from the
  authenticated principal (admin JWT `tenant` claim) or the validated virtual key's organization:

```sql
SET LOCAL app.current_org = '<organization-uuid>';   -- inside the request transaction
```

`SET LOCAL` scopes it to the transaction so pooled connections never leak context between requests.
The `true` (missing_ok) second arg means an **unset** context yields NULL → the predicate is false →
**deny-by-default** (no rows), which is the safe failure (ADR-0009).

## 2. Tables under RLS
All tenant-owned tables (33 in the `Schema.sql` loop) plus the two partitioned tables get RLS:
`app_user, oauth_identity, service_account, session, refresh_token, membership, project,
project_member, api_key, api_key_scope, provider, model, price_table, provider_health,
routing_policy, routing_policy_rule, prompt_template, prompt_version, embedding,
semantic_cache_entry, budget, reservation, usage_rollup, billing_account, invoice,
rate_limit_policy, governance_policy, notification, configuration, secret_reference, webhook,
webhook_delivery, usage_ledger, audit_event`.

**Not under tenant RLS (global reference data):** `permission`, system `role` (NULL org),
`role_permission`, and NULL-org rows of `feature_flag`/`configuration`. These are read-only reference
data managed by platform migrations, not tenant data. (`role`/`feature_flag`/`configuration` that *are*
org-scoped rows still filter by `organization_id` in queries; a mixed-scope policy that allows
`organization_id IS NULL OR organization_id = current_org` is applied where both global and per-org
rows coexist — documented per-table in Phase 5 wiring.)

## 3. Partitioned tables
RLS is defined on the **parent** (`usage_ledger`, `audit_event`); PostgreSQL applies parent policies to
all partitions, and **new monthly partitions inherit enforcement automatically** — no per-partition
policy maintenance. Time-pruning happens first, then RLS filters by tenant.

## 4. Database role model
Distinct DB roles with least privilege (created in migrations). **`app_rw` is realized in
migration `0003_database_roles` ([ADR-0014](adr/0014-runtime-database-role-rls-enforcement.md));
the application connects as it and Gate 2 asserts it is NOSUPERUSER/NOBYPASSRLS.** The remaining
roles below (`app_worker`, `app_reconciler`, `rls_bypass`) are deferred to their functional
milestones (metering, reconciliation, archival) and land with their own migrations.

| Role | Purpose | Privileges |
|------|---------|-----------|
| `app_rw` | API request path | `SELECT/INSERT/UPDATE/DELETE` on tenant tables **except** no `UPDATE/DELETE` on `audit_event`, `usage_ledger` (append-only); subject to RLS |
| `app_worker` | Workers (metering/audit/embeddings) | `INSERT` on `audit_event`/`usage_ledger`; `SELECT/INSERT/UPDATE` on rollups/jobs; subject to RLS but sets org context per event |
| `app_reconciler` | Budget reconciliation | `SELECT` ledger, read/write `reservation`; subject to RLS |
| `migrator` | Schema migrations | DDL; **not** used at runtime |
| `rls_bypass` (a.k.a. maintenance) | Archival/partition/prune jobs that must cross tenants | `BYPASSRLS`; used **only** by controlled, audited jobs — never by request handlers |

Append-only is enforced by **revoking `UPDATE`/`DELETE`** on `audit_event` and `usage_ledger` from
`app_rw`/`app_worker` (not merely by policy), so immutability holds even against application bugs
(FR-113/114, NFR-SEC09).

## 5. Cross-tenant operations (the few that need it)
- **Platform/admin analytics** across tenants and **archival/partition jobs** use the `rls_bypass` role
  in dedicated, audited processes — **never** the request-serving role.
- **Semantic-cache ANN**: queries run under the tenant context so RLS + `ix_embedding_org` constrain the
  vector search to the tenant's rows; there is no cross-tenant vector search.

## 6. Interaction with connection pooling
Because context is `SET LOCAL` within the request transaction, pooled connections are safe: the setting
is reset at transaction end. A guard in the data layer asserts `app.current_org` is set before issuing
tenant queries (belt-and-suspenders with deny-by-default).

## 7. Testing (Phase 13, gating GA) — NFR-SEC07
- **Isolation test suite:** for every tenant-owned table, attempt reads/writes as tenant A with tenant
  B's ids and assert **zero** rows / rejection — across every API path (AC-US-100).
- **Missing-context test:** with no `app.current_org`, assert **no rows** returned (deny-by-default).
- **Bypass containment:** assert request-serving roles do **not** have `BYPASSRLS`.
- **Append-only test:** assert `UPDATE`/`DELETE` on `audit_event`/`usage_ledger` are denied to app roles.
- **Cross-tenant vector test:** identical prompts from A and B never serve each other's cached response
  (AC-US-032).
These run in CI on every migration ([`Migration_Strategy.md`](Migration_Strategy.md)).

## 8. Threats mitigated
- **Cross-tenant read/write** (STRIDE Information Disclosure / Elevation) — DB-enforced even on app bugs
  (RISK-T05, NFR-SEC07).
- **Audit/ledger tampering** (Tampering) — append-only via grants + hash chain (NFR-SEC09).
- **Context leakage via pooling** — `SET LOCAL` + deny-by-default.

## 9. Requirements traceability
ADR-0002 (isolation), ADR-0009 (deny-by-default/append-only), FR-130..132/113/114, NFR-SEC05/07/09,
RISK-T05. See [`Database_Design.md`](Database_Design.md) DB-DEC-01/06 and the security
[trust boundaries](architecture/security/01-trust-boundaries.md) / [STRIDE](architecture/security/02-threat-model-stride.md).
