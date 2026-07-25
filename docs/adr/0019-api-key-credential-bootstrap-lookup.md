# ADR-0019: API-key credential bootstrap lookup under RLS

- **Status:** Accepted
- **Date:** 2026-07-25
- **Deciders:** Principal Architect, Security Architect
- **Phase:** 4 — AI OS implementation (Slice 18)
- **Relates to:** [ADR-0002](0002-multi-tenant-isolation-model.md) (tenant isolation),
  [ADR-0008](0008-rbac-model.md) (virtual keys), [ADR-0014](0014-runtime-database-role-rls-enforcement.md)
  (`app_rw` is `NOSUPERUSER`/`NOBYPASSRLS`), [ADR-0009](0009-fail-open-fail-closed-matrix.md) row 6
- **Does not amend ADR-0016**, which remains frozen. No Tier-1 protocol changes.

## Context & problem

Authentication must resolve a virtual API key to a principal *before* anything about the caller is
trusted — including which tenant they belong to. `AuthenticateApiKey` therefore looks the key up by
its non-secret prefix and only then verifies the presented secret against the stored hash.

That ordering collides head-on with tenant isolation:

* `api_key` is a tenant-scoped table with `ENABLE` + `FORCE ROW LEVEL SECURITY` and a
  `organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid` policy.
* Per ADR-0014 the application connects as `app_rw`, which is `NOSUPERUSER` + `NOBYPASSRLS`
  precisely so that policy is inescapable.
* At credential-resolution time no tenant is bound, so `app.current_org` is unset (or the empty
  string left behind on a pooled connection), the policy matches **zero rows**, and the lookup
  returns nothing.

The consequence is not a partial failure but a total one: wiring `SqlApiKeyRepository` into
`CompositeAuthenticator` as-is produces an API-key authenticator that fails **every** key while
appearing fully wired — the "implemented, wired, and still non-functional" defect this phase has
repeatedly caught one layer at a time.

The tenant hint that solves the equivalent problem for OIDC (ADR-0015 signs it into the `state`
parameter) has no analogue here: a virtual key is an opaque bearer secret with no carried claims.

## Decision drivers

* FR-094..097 (virtual keys, hashed at rest, looked up by prefix), FR-129 (tenant-scoped authz).
* ADR-0014's runtime role attributes are **not** negotiable — they are the only reason RLS is
  actually enforced (NFR-SEC07). Any solution that relaxes them is rejected by construction.
* ADR-0009 row 6: authentication fails closed.
* NFR-SEC04/SEC05 (deny-by-default, least privilege): the bootstrap path must expose the minimum
  fact required to proceed, and nothing else.

## Options considered

### Option A — Grant `app_rw` `BYPASSRLS`, or connect as a superuser for authentication
Rejected outright. It defeats ADR-0014 globally to solve one lookup, and NFR-SEC07 names exactly
this as the isolation-defeating configuration.

### Option B — Add an RLS policy on `api_key` permitting reads when no tenant is bound
Rejected. A policy that opens up whenever `app.current_org` is unset lets `app_rw` enumerate every
tenant's keys simply by not binding a tenant. It converts a boundary into a formality.

### Option C — Encode the organization id inside the key material
Rejected. It changes the credential format, makes every key self-describing, and couples the
credential encoding to the tenancy model — a migration cost and a coupling paid forever to avoid a
single lookup.

### Option D — Duplicate `(key_prefix -> organization_id)` into a global, non-RLS lookup table
Rejected. Two sources of truth for the same fact, kept consistent by a trigger or by remembering
to write both. Nothing writes `api_key` today, so the duplication would exist before its writer
did — the speculative infrastructure GP-1 forbids.

### Option E — **A narrowly-scoped `SECURITY DEFINER` resolver reachable only through an owner-only policy**
A single SQL function, owned by the schema owner, that maps an exact `key_prefix` to the owning
`organization_id` **and returns nothing else**. Because `api_key` is under `FORCE ROW LEVEL
SECURITY` the owner is *also* subject to its policies, so the function is paired with one
additional policy scoped `TO` the owner role granting `SELECT` only. `app_rw` is not that role, so
`app_rw` cannot use the policy directly — its only access to the fact is by executing the function.

## Decision

Adopt **Option E**. Migration 0007 creates:

1. `gateway_api_key_tenant(p_key_prefix text) RETURNS uuid` — `LANGUAGE sql`, `STABLE`,
   `SECURITY DEFINER`, `SET search_path = pg_catalog, public` (a `SECURITY DEFINER` function
   without a pinned `search_path` is hijackable). Its body is one statement selecting
   `organization_id` from `api_key` for an **exact** `key_prefix` match with `status = 'active'`.
2. `api_key_bootstrap_lookup` — an RLS policy on `api_key`, `FOR SELECT`, scoped `TO` the schema
   owner (resolved as `current_user` at migration time so the production owner need not be named),
   `USING (true)`. The owner needs it because `FORCE ROW LEVEL SECURITY` subjects the owner to
   policies too; relying on owner privileges alone would work only where the owner happens to be a
   superuser, which is true in dev and must not be assumed in production.
3. `REVOKE ALL ON FUNCTION ... FROM PUBLIC` then `GRANT EXECUTE ... TO app_rw`.

Authentication is then a **two-phase** operation, implemented by
`TenantScopedApiKeyRepository` (an `ApiKeyRepository`):

* **Phase 1 (tenant resolution, no tenant context):** execute the function. `NULL` ⇒ unknown or
  inactive prefix ⇒ the repository returns `None` and authentication fails closed with a 401.
* **Phase 2 (everything else, inside the tenant's RLS context):** open a
  `AsyncUnitOfWork(tenant_id=<resolved org>)` and perform the ordinary, fully RLS-governed read
  via `SqlApiKeyRepository`, returning the record whose hash `AuthenticateApiKey` then verifies in
  constant time.

### What the bootstrap path discloses, precisely

Exactly one bit of information: *which organization owns this exact prefix*, to a caller who
already holds the prefix. It cannot enumerate (no wildcards, no listing, exact match only), cannot
read the hash, the scopes, the expiry or the name, and cannot reach any other table. Possession of
the secret is still proven afterwards, in the tenant's own context, by constant-time comparison.

## Consequences

- **Positive:** `app_rw` keeps `NOSUPERUSER` + `NOBYPASSRLS` verbatim — ADR-0014 is untouched. The
  exception is one function with one narrow projection, greppable and auditable, rather than a role
  attribute whose blast radius is the entire schema. Everything after tenant resolution runs under
  ordinary RLS. No credential format change, no duplicated data.
- **Negative:** a `SECURITY DEFINER` function is a privileged surface and must be reviewed as one;
  its `search_path` is pinned for that reason. It is also the first sanctioned RLS exception in the
  system, so it establishes a precedent that must not be widened casually — hence this ADR rather
  than a comment in a migration.
- **Bounded:** this pattern is authorised for **credential bootstrap only** — resolving a tenant
  from a presented credential before a tenant is known. Any further `SECURITY DEFINER` addition
  requires its own ADR.

## Requirements satisfied

- Functional: FR-094, FR-095, FR-096, FR-097, FR-129.
- Non-functional: NFR-SEC04, NFR-SEC05, NFR-SEC07 (preserved, not relaxed).

## Review notes

Revisit if a key-issuance API is added: the issuance path could store a tenant-resolvable key
identifier in the credential itself, at which point Option C becomes cheap and this function could
be retired. Until a writer for `api_key` exists, that trade cannot be evaluated honestly.
