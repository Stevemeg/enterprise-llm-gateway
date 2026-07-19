# ADR-0015: OIDC login-state storage & RLS bootstrapping

- **Status:** Accepted (2026-07-18, Option A — realized in Milestone 3d-2B, migration 0004)
- **Date:** 2026-07-18
- **Deciders:** Security Architect, Principal Architect, Database Architect
- **Phase:** 5 — Backend (Milestone 3d-2B, OIDC)
- **Affects:** adds one tenant table (`oidc_login_state`) + a `StateStore` port; ADR-0002 (RLS),
  ADR-0008 (auth), ADR-0009 (fail-closed), ADR-0014 (runtime role). Goes through the new
  tenant-table guardrail (`scripts/check_migration_guardrails.py`).

## Context & problem
The OIDC authorization-code flow (with PKCE) is split across two HTTP requests with an
IdP round-trip and a browser redirect in between:

1. **/authorize (initiate):** we generate `state` (CSRF/replay), `nonce` (id_token binding), and a
   PKCE `code_verifier`/`code_challenge`, remember them, and redirect the user to the IdP.
2. **/callback:** the IdP redirects the browser back to our fixed redirect URI with `code` + `state`.
   We must recover what we stored, enforce **single-use** on `state`/`nonce`/`code`, check TTL,
   exchange `code`+`code_verifier` for tokens, verify the `id_token` (iss/aud/exp/**nonce**), and
   only then mint a session.

Three forces make this non-trivial:
- **Single-use is mandatory** (Security_Test_Plan §1a rows 1–5): reused `state`/`nonce`/`code` and
  expired `state`/`nonce` must be rejected. That requires an authoritative, atomically-consumed store
  — a purely stateless signed cookie cannot prevent replay by itself.
- **Durability across instances/restarts:** the callback may land on a different app instance than
  the initiate. In-memory state breaks single-use in any real deployment.
- **RLS bootstrapping:** the callback arrives with **no tenant context** — the browser presents only
  `code`+`state`. But `oidc_login_state` holds tenant data (which org/IdP the login targets), and our
  invariant (ADR-0014, the new guardrail) is that tenant tables are RLS-scoped. To read an RLS-scoped
  row we must set `app.current_org` *before* the read — yet the org is what we're trying to recover.

Decision drivers: FR-090/092 (OIDC login, id_token verification), NFR-SEC04/05 (anti-replay, single
use), ADR-0002 (tenant isolation), ADR-0009 (fail closed), ADR-0014 (no non-RLS tenant data / no
BYPASSRLS on the runtime path), and the just-installed migration guardrail.

## Options considered
### Option A — RLS-scoped `oidc_login_state` + org carried in a signed `state` — **recommended**
`state` sent to the IdP is `payload.hmac` where `payload = b64(organization_id, random_id)` and the
HMAC is computed via the single crypto boundary (`shared.secrets`). On callback we **verify the HMAC
first** (reject tampering), extract `organization_id`, `SET app.current_org`, then look the row up by
`sha256(random_id)` and consume it with `DELETE ... RETURNING` (atomic single-use) under RLS.
- **Pros:** `oidc_login_state` stays a normal RLS-scoped tenant table — uniform with every other
  tenant table, passes the guardrail unchanged; single-use is atomic under RLS; the org hint is
  integrity-protected so it cannot be forged; no new bypass path. Fails closed if the HMAC is invalid.
- **Cons:** slightly more work in the `state` value (HMAC sign/verify) — but it reuses the existing
  crypto boundary, so no new primitive.

### Option B — Non-RLS "pre-authentication" `oidc_login_state`, keyed by unguessable single-use id
The table is exempted from RLS (added to the guardrail's documented exemption list) and looked up by
`sha256(state)` without tenant context; org is a column recovered from the row.
- **Pros:** simplest lookup; no signed-state crypto.
- **Cons:** puts tenant-referencing data **outside** RLS — exactly the posture ADR-0014 and the new
  guardrail were built to prevent; isolation then rests solely on state entropy, not a DB-enforced
  boundary; needs a special-case exemption and a bespoke consume path. Weaker defense-in-depth.

### Option C — Stateless signed/encrypted `state` (store nothing)
Encode org, nonce hash, PKCE challenge, and expiry into a signed (or encrypted) `state` blob.
- **Pros:** no table, no migration.
- **Cons:** cannot enforce **single-use** server-side — replay of a still-valid signed `state`/`code`
  would succeed, failing Security_Test_Plan §1a rows 1–3. Preventing that reintroduces a
  consumed-id store, so it does not actually avoid state. Rejected as a primary design.

## Decision
Adopt **Option A.** Add a tenant-scoped `oidc_login_state` table and a `StateStore` port; the app
persists login state there for 2B, carries the org in an **HMAC-signed `state`**, and consumes rows
atomically under RLS. The port keeps the backing store swappable (Redis in the caching/infra
milestone) without touching the OIDC use-cases.

**Schema (added; forward-only migration `0004_oidc_login_state`):**
```
oidc_login_state(
  id                 uuid pk default gen_random_uuid(),
  organization_id    uuid not null references organization(id) on delete cascade,  -- RLS
  state_hash         bytea not null unique,     -- sha256(random_id); never the raw state
  nonce_hash         bytea not null,            -- sha256(nonce); id_token nonce is verified against this
  code_verifier      text  not null,            -- PKCE secret we send at token exchange; single-use, short TTL
  code_challenge_method text not null default 'S256',
  provider           text  not null,            -- which configured IdP
  redirect_uri       text  not null,            -- our callback URI used (exact-match on return)
  return_to          text,                      -- post-login app destination (validated allow-list)
  created_at         timestamptz not null default now(),
  expires_at         timestamptz not null       -- TTL = 5 minutes (see below); expired ⇒ rejected
)
-- ENABLE + FORCE ROW LEVEL SECURITY; tenant-isolation policy on organization_id (passes the guardrail).
-- Index on expires_at for pruning; unique(state_hash) for single-use lookup.
```
Consume = `DELETE FROM oidc_login_state WHERE state_hash = :h RETURNING *` inside the tenant-scoped
UoW (atomic single-use). `code_verifier` is a transient per-login secret (not a stored credential); it
lives only until consume.

### State TTL (fixed)
**TTL = 5 minutes.** An authorization-code round-trip is interactive and completes in seconds; five
minutes is generous for a slow login yet aggressively bounds the replay window, limits table growth,
and aligns with common IdP `state`/code lifetimes. A row whose `expires_at` has passed is treated as
**absent** (fail closed) even if still physically present. The TTL is a single named constant in the
OIDC settings so it is auditable and testable — not scattered literals.

### Expiration is active, not passive
Expired rows must not accumulate:
- **Read path (authoritative):** consume rejects any row past `expires_at` — correctness never depends
  on the cleaner having run.
- **Cleanup worker (hygiene):** a periodic job runs `DELETE FROM oidc_login_state WHERE expires_at <
  now()` **every minute**, bounded per run, using the maintenance path (never a request handler). The
  `ix_oidc_login_state_expires` index keeps it cheap. The worker itself lands with the background-jobs
  milestone; until then the `StateStore` port exposes `purge_expired(now)` so the delete is implemented
  and unit-tested now, and simply gets scheduled later.

### Concurrency guarantee (why DELETE ... RETURNING)
Two callbacks racing with the same `state` must not both succeed. `DELETE ... RETURNING` makes the
consume **atomic**: exactly one transaction deletes and receives the row; the concurrent one re-evaluates
after the first commits, matches nothing, and returns zero rows ⇒ replay detected and rejected. This is
strictly stronger than a `SELECT`-then-`UPDATE`/flag or a cache TTL, both of which have a check-to-use
window. A **concurrent-callback race test** asserts exactly one winner (Security_Test_Plan §1a row 1).

## Security considerations

### Why `code_verifier` is stored in plaintext (accepted, deliberate)
The PKCE `code_verifier` is the one column here that is **not** hashed. This is intentional and
sound: the token exchange requires presenting the **original** verifier to the IdP, so a hash cannot
be substituted without breaking the protocol. The risk is bounded because a verifier is materially
unlike a password or API key:

| Property | `code_verifier` | Password / API key |
|---|---|---|
| Lifetime | ≤ 5 minutes (TTL) | months–years |
| Reuse | never — single-use | repeatedly |
| Deletion | atomic, on consume | manual/rotation |
| Standalone authority | **none** — useless without the matching `code` + client creds | authenticates directly |

A verifier alone authenticates nothing: an attacker also needs the authorization `code` (single-use,
bound to the same login) and our client credentials. Hashing it would add real protocol complexity
for negligible gain. **Accepted risk**, revisited if the IdP set ever requires longer-lived state.

### Verifier confidentiality obligation (enforced)
Because it is stored in the clear, the verifier must never escape the store:

> The `code_verifier` MUST NOT appear in logs, audit events, exception messages/tracebacks, metrics,
> or API responses.

This is enforced by the existing log-redaction filter plus a dedicated regression test
(`test_code_verifier_never_logged`) so a future logging or error-handling change cannot silently
leak it. The same applies to raw `state` and `nonce` (only their hashes are persisted anyway).

### Network timeout policy for IdP calls (authentication is on the critical path)
| Setting | Value |
|---|---|
| Connect timeout | **2 s** |
| Read timeout | **5 s** |
| Total budget (hard ceiling) | **7 s** |
| Retries | **0** |

Retries are deliberately **zero**. A retry multiplies worst-case login latency and silently masks a
degraded IdP; deterministic failure is preferable on an authentication path (ADR-0009 fail-closed).
The total budget is enforced with `asyncio.timeout`, so connect + read + redirects can never exceed
it even if a per-phase timeout is generous.

Observability on failure (no sensitive values ever):
- Failed **JWKS fetches** increment `gateway_oidc_jwks_fetch_failures_total{reason=...}`.
- Failed **token exchanges** increment `gateway_oidc_token_exchange_failures_total{reason=...}`.
- `reason` comes from a fixed low-cardinality vocabulary (`timeout`, `transport`, `malformed`,
  `unknown_kid`, `rate_limited`) — **never** exception text or user input.
- Timeouts emit a structured log/audit record carrying only the endpoint — never the authorization
  code, `code_verifier`, client secret, or token material.

### IdP JWKS caching policy (id_token verification)
`id_token` signatures are verified against the IdP's published JWKS, cached with:

- **TTL = 10 minutes** — bounds staleness while keeping the login path off the network.
- **Cache hit** (`kid` known and fresh) ⇒ verify locally, no network call.
- **Unknown `kid`** ⇒ **immediate refresh** (handles IdP key rotation without an outage), respecting
  a minimum refresh interval so an attacker cannot use forged `kid`s to force unbounded fetches.
- **Still unknown after refresh, or JWKS unreachable/malformed** ⇒ **fail closed** (reject the login).
  We never fall back to an unverified token or a stale-but-expired key on error (ADR-0009).

## Consequences
- **Positive:** OIDC state is durable, single-use, TTL-bounded, and **RLS-protected like all tenant
  data**; the guardrail stays green with no exemption; the `StateStore` port lets Redis drop in later;
  fail-closed on tampered/expired/unknown state.
- **Negative:** one more table + repository + a small HMAC on the `state` value; a follow-up prune job
  (deferred, noted).
- **Follow-ups (2B):** `StateStore` port + Postgres adapter; JWKS fetch/cache (fail-closed) for
  id_token verification; the §1a replay tests; DI + middleware wiring; `Authentication_Data_Flow.md`;
  Authentication Completion Report. Redis-backed `StateStore` + prune job land in the infra milestone.

## Requirements satisfied
FR-090, FR-092; NFR-SEC04, NFR-SEC05; upholds ADR-0002 (RLS), ADR-0009 (fail closed), ADR-0014
(runtime role / no non-RLS tenant data), and the tenant-table merge guardrail.

## Review notes
Revisit if we later support IdP-initiated login (no prior state row) or move state to Redis — both are
port-level changes, not use-case changes.
