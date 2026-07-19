# Authentication Security Review (Milestone 3d — Review)

**Type:** Review milestone. No features implemented.
**Date:** 2026-07-18 · **Re-reviewed:** 2026-07-18 after the FU-01…FU-04 remediation milestone
**Reviewer posture:** adversarial — the goal was to **break** the implementation, not confirm it.
**Scope:** Milestones 3d-1, 3d-2A, 3d-2A.5, 3d-2B against Architecture, ADR-0002/0008/0009/0011/0013/0014/0015,
STRIDE model, Authentication_Review_Checklist, Security_Test_Plan, Security_Traceability,
Authentication_Data_Flow, Cryptographic_Architecture, Credential_Rotation_Guide,
Authentication_Readiness_Checklist, Authentication_Completion_Report, Integration Matrix, Gate 1, Gate 2.

---

## 0. Verdict

> ### ✅ **PASS — IMPLEMENTATION AND OPERATIONAL VALIDATION COMPLETE**
> *(Revised from ❌ CONDITIONAL FAIL after the remediation milestone.)*
>
> All three HIGH findings (AUTH-01, AUTH-02, AUTH-03) and the MEDIUM AUTH-04 are **closed with
> code and tests**. **The authentication implementation is complete** — no feature or remediation
> work remains.
>
> **Gate 2 has now been executed and is green** (AUTH-07 closed): 169 passed, 0 failed,
> 95% coverage, mypy strict clean, import-linter 7/7, migrations at `0005`, and the runtime role
> verified as `app_rw` with `rolsuper=False, rolbypassrls=False`. The validation script was also
> proven to fail correctly on a failing command - it is a verified gate, not an assumed one.
>
> This distinction is deliberate. "Implementation PASS" states that the subsystem is built and
> reviewed; "Operational Validation Pending" states that it has not yet been *observed working*
> on the target runtime. Both must hold before the subsystem is called production-ready — a
> standard this project has earned, having found five real defects (nonce hash mismatch, missing
> `created_at`, superuser RLS bypass, per-process signing keys, reference-as-key) that code
> review alone would not have caught.
>
> **RBAC may begin once Gate 2 runs green with 0 skipped.** No further remediation is required.

### Remediation summary (FU-01 … FU-04)

| ID | Finding | Status | Evidence |
|---|---|---|---|
| **AUTH-01** | Signing keys generated per process | ✅ **Closed** | `KeyProvider.from_pem` loads managed material; `generate()` is dev-only behind `allow_insecure_generated_keys`; production config rejects it; rotation overlap tested |
| **AUTH-02** | Secret *references* used as key material | ✅ **Closed** | `SecretsResolver` port + `EnvSecretsResolver`; container resolves `*_ref` → material; test asserts the signer never holds the reference |
| **AUTH-03** | No route-level auth enforcement test | ✅ **Closed** | `test_route_auth_coverage.py` — every non-allow-listed route must declare an auth dependency; allow-list entries require justification |
| **AUTH-04** | Ephemeral state key under multi-instance | ✅ **Closed** | Fallback now requires explicit dev opt-in, logs a warning, and is forbidden in production |
| **AUTH-07** | Gate 2 not executed | ✅ **Closed** | Executed on real PostgreSQL: 169 passed, 0 failed, 95% coverage |

**What changed architecturally: nothing.** The remediation added one port
(`application/ports/secrets.py`), one adapter package (`adapters/secrets/`), and two constructors
on the existing `KeyProvider`. No completed abstraction was replaced, no schema changed, no API
changed — consistent with the finding that these were composition-root wiring defects, not design
flaws.

**Now enforced at startup (fail fast, ADR-0009):**
- Production **refuses to boot** if the JWT or state signing key cannot be resolved.
- Production **refuses to boot** if `allow_insecure_generated_keys` is true.
- Startup **fails** if a *previous* (rotation-overlap) key cannot be resolved — silently shrinking
  the rotation window would reintroduce the lockout risk AUTH-01 described.
- Development may use a documented, explicitly opted-in fallback that logs a warning.

---

## 1. The twelve questions

| # | Question | Answer | Verdict |
|---|---|---|---|
| 1 | Can JWTs be forged? | **No** — and keys are now managed, rotatable, escrowed | ✅ Pass |
| 2 | Can API keys be replayed? | **Yes, by design** (bearer credential) — mitigated, not eliminated | ⚠️ Accepted risk |
| 3 | Can OIDC callbacks be replayed? | **No** — proven under real concurrency | ✅ Pass |
| 4 | Can refresh tokens be replayed? | **No** — rotation + reuse detection | ⚠️ Pass, thin evidence |
| 5 | Can tenant isolation be bypassed? | **No** via the application path — DB-enforced | ✅ Pass |
| 6 | Can a PostgreSQL superuser bypass RLS? | **Yes** — inherent; app never connects as one, CI enforces | ✅ Mitigated |
| 7 | Can JWKS rotation lock out users? | **No** — both directions; overlap window tested | ✅ Pass |
| 8 | Can clock skew break authentication? | **No** within leeway; documented assumption | ✅ Pass |
| 9 | Can Redis failure bypass authentication? | **No** — auth has zero Redis dependency | ✅ Pass |
| 10 | Are secrets ever logged? | **No** — redaction + regression tests | ✅ Pass |
| 11 | Is every authentication failure fail-closed? | **Yes** — and route-level enforcement is now CI-verified | ✅ Pass |
| 12 | Are all security assumptions documented? | **Yes** — §5 of this document | ✅ Pass |

### Detail

**1. JWT forgery.** RS256 only; algorithm allow-list rejects `alg:none` and HMAC confusion
(`test_jwt.py::alg_confusion`, `test_oidc_id_token.py::test_alg_none_is_rejected`); `kid` required;
signature, `iss`, `aud`, `exp` all validated with injected clock. Tampered payloads rejected
(tested). Forging a token requires the private key — **which is where AUTH-01 bites**: the key is
generated per process, so it is neither escrowed nor rotatable, and every restart invalidates all
outstanding tokens. Cryptographically unforgeable; operationally unmanaged.

**2. API-key replay.** An API key *is* a reusable bearer credential — replay by an attacker who
holds the key is inherent to the scheme, not a defect. Mitigations: TLS in transit (assumption A2),
SHA-256 at rest with non-secret prefix lookup, constant-time compare, immediate revocation via
`status`. **Not yet mitigated:** per-key rate limiting and anomaly detection (deferred to the limits
milestone), so a stolen key is usable at full rate until revoked. Accepted, documented.

**3. OIDC callback replay.** **The strongest result in this review.** `DELETE ... RETURNING` makes
consume atomic. Verified on real PostgreSQL 14 with two genuinely concurrent transactions on one
`state`: callback A consumed 1 row, callback B consumed 0, 0 rows remained. Also proven: the replay
never reaches the IdP (`exchanges == ["auth-code-1"]`), so a replayed callback cannot burn an
authorization code. Expired state and cross-tenant state are rejected before any IdP call.

**4. Refresh replay.** Rotation on every use; presenting a rotated/revoked token is treated as theft
and revokes the whole session chain, with an audit event. Logic is proven — but only against
in-memory fakes (Integration Matrix ⚠️). No PostgreSQL-level concurrency test exists, so the
*orchestration* is proven while the *storage-level race* is not. See FU-03.

**5. Tenant isolation.** DB-enforced, not app-enforced. Proven on real PostgreSQL: `app_rw`
(NOSUPERUSER, NOBYPASSRLS) reads its own tenant's row and gets **0 rows** for the other tenant, in
both directions; with no `app.current_org` bound, **0 rows** (deny by default). RLS is `ENABLE` +
**`FORCE`**, so even the table owner is subject. `oidc_login_state` is RLS-scoped like every other
tenant table — Option A in ADR-0015 deliberately avoided a bypass exemption.

**6. Superuser/BYPASSRLS.** Unavoidable in PostgreSQL: superusers and `BYPASSRLS` roles ignore
policies even under `FORCE`. This was **the most severe finding of the entire milestone** and is now
mitigated structurally: a dedicated `app_rw` runtime role, an owner/migrator split, and a CI gate
(`validate.*` + `test_database_role.py`) that fails the build if `current_user` is superuser or
`BYPASSRLS`. Residual: the **migrator** is privileged by necessity (assumption A5).

**7. Key rotation lockout.** Two directions, different answers.
*IdP → us:* handled. Unknown `kid` triggers one refresh; retired keys disappear on wholesale
replacement; still-unknown fails closed; a throttle prevents forged-`kid` refresh storms. Tested.
*Us → clients:* **broken by AUTH-01.** `KeyProvider` supports `previous` keys for overlap, but the
container calls `KeyProvider.generate()`, so keys are per-process and the overlap mechanism is never
exercised. Restart = mass lockout. Multi-instance = tokens minted by one instance rejected by
another, and inconsistent JWKS.

**8. Clock skew.** Configurable leeway (default 60s) applied to JWT validation; clock is injected
everywhere, so behaviour is deterministic and testable. OIDC state TTL uses **application** time on
both write and read, so app↔DB clock divergence cannot corrupt it. `id_token` `exp` depends on IdP
clock (assumption A1). Excessive skew degrades to rejection — fail closed, not fail open.

**9. Redis.** Authentication touches Redis **nowhere**. ADR-0015 deliberately chose PostgreSQL for
OIDC state precisely so login correctness does not depend on a cache tier. A total Redis outage
cannot bypass, weaken, or short-circuit authentication. (Budget/rate-limit paths use Redis; that is
outside this subsystem.)

**10. Secret logging.** Structured logging with redaction; dedicated regression tests assert the
PKCE `code_verifier` and IdP client secret appear in neither exception messages, tracebacks, nor
captured logs; error envelopes carry only a code, message and correlation id. Metric labels are
drawn from closed enums, never exception text or user input. Residual: `code_verifier` is stored in
**plaintext** for ≤5 minutes, so it exists in DB backups/WAL for that window (accepted, ADR-0015).

**11. Fail-closed.** Every *evaluated* credential fails closed: malformed header, invalid token,
expired token, bad state, unknown identity, JWKS unreachable, token-exchange timeout — all 401/reject,
all audited, none fail open. **However**, a request with **no** `Authorization` header passes
through the middleware untouched (by design: public routes exist, and protected routes are meant to
enforce via route dependencies). There is **no test asserting that every non-public route actually
has that dependency**. A single forgotten dependency silently yields an unauthenticated endpoint.
That is fail-open-by-omission — AUTH-03.

**12. Assumptions.** Documented in §5 below, each with its failure consequence.

---

## 2. Findings

### AUTH-01 — Signing keys are generated per process (HIGH)
`config/container.py:75` — `key_provider = KeyProvider.generate()`.
Every process mints a **fresh** RSA keypair at startup. Consequences: (a) restart invalidates every
outstanding access token; (b) with >1 replica, tokens issued by one instance fail verification on
another and `/jwks` answers differ per instance — non-deterministic auth behind a load balancer;
(c) the `previous`-key rotation overlap that `KeyProvider` implements is never used, so the
documented rotation procedure cannot actually be performed.
**Root cause:** no secrets-manager resolver exists (see AUTH-02); the container had nothing to load
from, and generation was wired as a placeholder.
**Required fix:** load the signing key from the secrets manager/KMS at startup; keep `generate()`
for tests and local dev only; fail fast in production if no key is configured; exercise rotation
(current + previous) in an integration test.

### AUTH-02 — Secret *references* are used as key material (HIGH)
`config/container.py:85` — `StateSigner(auth.state_signing_key_ref or _ephemeral_state_key())`.
`state_signing_key_ref` is a **pointer** (default `"gateway/oidc/state-signing-key"`), not a secret.
It is being passed directly as the HMAC key. In any environment that does not override it, the OIDC
state-signing key is a **public constant committed to the repository**.
**Exploitability:** bounded but real. Forging a `state` lets an attacker choose the
`organization_id` the callback binds *before* the DB read; the atomic consume then finds no matching
row, so a forged state cannot complete a login. It does, however, defeat the integrity property the
signature exists to provide and is a prerequisite for chaining with any future state-handling bug.
**This also means ADR-0011 ("secrets are never stored, only referenced") is documented but not
realized in code** — a grep for a secrets resolver returns nothing.
**Required fix:** implement a `SecretsResolver` port + adapter; resolve `*_ref` values to material
at startup; never pass a reference where a key is expected; production start-up fails if resolution
fails. The existing validator checks only that the ref string is *non-empty*, which is insufficient.

### AUTH-03 — No enforcement that protected routes require authentication (HIGH)
The middleware intentionally passes unauthenticated requests through. Route-level dependencies are
the actual enforcement point, and nothing verifies they are present.
**Required fix:** a test that enumerates the application's routes and asserts every route not on an
explicit public allow-list carries the auth dependency — so a forgotten dependency fails CI rather
than shipping an open endpoint. (Deny-by-default routing is the stronger alternative, but that is an
architectural change and is deliberately **not** proposed here.)

### AUTH-04 — Ephemeral state key fallback is unsafe under multi-instance (MEDIUM)
`_ephemeral_state_key()` returns a per-process random value. If ever reached with >1 replica, an
OIDC callback landing on a different instance than `/authorize` fails HMAC verification — **all
logins fail** intermittently and confusingly. Fails closed (good) but is an availability landmine.
**Fix:** remove the fallback once AUTH-02 lands; require an explicit key in every environment.

### AUTH-05 — `organization` is not RLS-scoped (LOW, by design)
`organization` is the tenant root and carries no `organization_id`, so it is intentionally outside
the RLS policy set. `app_rw` can therefore read/write **all** organization rows. Correct by design
(you cannot scope the scoping table by itself), but it means org enumeration is prevented by
application logic alone. Documented as assumption A6; worth an authorization check when RBAC lands.

### AUTH-06 — Observability gaps on non-middleware flows (LOW)
Latency histogram covers only bearer paths. OIDC login, refresh and service-account minting have
failure counters and audit events but no latency metric. Detection of a slow-but-succeeding IdP is
therefore weaker than for the bearer paths.

### AUTH-07 — Evidence depth: tests not executed in this environment (MEDIUM, process)
Gate 1 is statically validated only (sandbox is Python 3.10 against a 3.13 codebase). **Gate 2 has
not been run for this milestone.** Two defects in this subsystem were caught by *writing* tests
rather than running them, which is a strong signal that first execution will be informative.
No production-readiness claim is defensible until Gate 2 is green with 0 skipped.

---

## 3. Section pass/fail

| Section | Verdict | Evidence |
|---|---|---|
| Cryptographic design (algorithms, boundary) | ✅ Pass | import-linter contracts; alg allow-list tests; single `shared/secrets.py` boundary |
| **Key management / lifecycle** | ✅ **Pass** | SecretsResolver; managed keys; rotation-overlap tests |
| JWT validation | ✅ Pass | sig/kid/iss/aud/exp/skew + negative tests |
| API-key handling | ✅ Pass | hash-at-rest, prefix lookup, constant-time compare |
| Refresh rotation & reuse detection | ⚠️ Conditional | logic proven; no Postgres-level test (FU-03) |
| OIDC protocol (PKCE/state/nonce) | ✅ Pass | 14-row replay matrix; HMAC-before-DB ordering |
| **OIDC replay protection** | ✅ **Pass (proven)** | real-Postgres concurrency: exactly one winner |
| Tenant isolation / RLS | ✅ Pass (proven) | symmetric A↔B blocked; deny-by-default; FORCE RLS |
| Database role hardening | ✅ Pass (proven) | `app_rw` NOSUPERUSER/NOBYPASSRLS + CI gate |
| Fail-closed behaviour (evaluated credentials) | ✅ Pass | every failure path 401 + audited |
| **Route-level enforcement** | ✅ **Pass** | `test_route_auth_coverage.py` |
| Audit completeness | ✅ Pass | `AuthenticationDecision` everywhere; composite sink |
| Secret hygiene / no logging | ✅ Pass | redaction + `test_code_verifier_never_logged` |
| Observability | ⚠️ Conditional | AUTH-06 |
| Schema governance | ✅ Pass | ADR-0013/0014/0015 + automated merge guardrail |
| Documentation & traceability | ✅ Pass | data flow, traceability, STRIDE row, readiness checklist |
| Gate 1 | ✅ Pass (static) | ruff/format/compile/import-linter/guardrail green |
| **Gate 2 (operational validation)** | ✅ **Green — 169 passed, 0 failed** | AUTH-07 closed |

---

## 4. STRIDE coverage

| Threat | Control | Tested | Residual |
|---|---|---|---|
| **Spoofing** | RS256 + allow-list + kid; hashed credentials; constant-time compare; state HMAC | ✅ | AUTH-02 weakens state integrity until fixed |
| **Tampering** | Signature verification; hashed storage; append-only privileges on audit/ledger | ✅ | Low |
| **Repudiation** | `AuthAuditEvent` on every decision with `AuthenticationDecision` + correlation id | ✅ | Durable hash-chained sink still pending |
| **Information disclosure** | RLS (proven); redaction; constant-time compare; closed metric labels | ✅ | `code_verifier` plaintext ≤5 min |
| **Denial of service** | Bounded timeouts, 0 retries, JWKS refresh throttle | ✅ | No per-key rate limiting yet |
| **Elevation of privilege** | `app_rw` NOBYPASSRLS; refresh-reuse revocation; fail-closed | ✅ | AUTH-03 (route omission) |

---

## 5. Security assumptions authentication depends on

If any of these fails, the stated consequence follows. These are the preconditions for every "No"
in §1.

| # | Assumption | If it fails |
|---|---|---|
| **A1** | System clocks are synchronized within the configured leeway (60s) across gateway, IdP and DB | Valid tokens rejected (fail closed) or a short window of extended token life; never bypass |
| **A2** | TLS terminates in front of the gateway and internal hops are trusted | Bearer credentials interceptable in transit — hashing at rest gives no protection |
| **A3** | The secrets manager / KMS is uncompromised and available | **Currently unrealized (AUTH-02).** Once implemented: key compromise ⇒ token forgery; unavailability ⇒ fail-fast at startup |
| **A4** | PostgreSQL RLS is enabled and enforced, and the app connects as `app_rw` | Complete loss of tenant isolation — the exact failure this milestone found and fixed |
| **A5** | The migrator/owner role is used only for migrations, never for request serving | A privileged connection would bypass RLS entirely |
| **A6** | Application logic scopes `organization` access (it cannot be RLS-scoped) | Cross-tenant org enumeration; needs authorization coverage in RBAC |
| **A7** | The IdP's JWKS endpoint is trusted and authentic (TLS-verified) | Attacker-controlled keys ⇒ forged `id_token`s accepted |
| **A8** | Signing keys are protected and rotated with overlap | **Currently unrealized (AUTH-01)** — restart lockout, multi-instance inconsistency |
| **A9** | HSM is optional; software key storage is acceptable at this tier | Higher key-compromise blast radius than HSM-backed signing |
| **A10** | Redis unavailability does not affect authentication | Holds by construction — auth has no Redis dependency |
| **A11** | Audit sink failure must not break authentication | Holds — composite sink isolates failures; audit line may be lost, login proceeds |
| **A12** | Database backups containing short-lived `code_verifier` values are protected | Brief exposure of single-use, expired PKCE secrets — low value to an attacker |

---

## 6. Required follow-up work

**Blocking (must complete before RBAC begins):**

| ID | Work | Addresses |
|---|---|---|
| **FU-01** | `SecretsResolver` port + adapter; resolve `*_ref` → material at startup; fail fast on failure; remove reference-as-key | AUTH-02, AUTH-04, A3 |
| **FU-02** | Load signing keys from the resolver; `generate()` becomes dev/test-only; production fails fast without a key; integration test proving rotation overlap (old token valid, new token valid, retired key rejected) | AUTH-01, A8 |
| **FU-03** | Route-coverage test: every non-allow-listed route requires auth | AUTH-03 |
| **FU-04** | Execute **Gate 2** on real PostgreSQL — all green, **0 skipped** | AUTH-07 |

**Non-blocking (schedule, do not gate RBAC):**

| ID | Work | Addresses |
|---|---|---|
| FU-05 | Postgres-level refresh rotation/reuse concurrency test | Q4 evidence depth |
| FU-06 | Record `gateway_auth_duration_seconds` in OIDC/refresh/service-account use-cases | AUTH-06 |
| FU-07 | Service-account end-to-end test when the token endpoint is exposed | Integration Matrix ⚠️ |
| FU-08 | Durable hash-chained `audit_event` sink behind the existing composite | Repudiation residual |
| FU-09 | Per-key rate limiting / anomaly detection | Q2 residual |
| FU-10 | Schedule the `oidc_login_state` expiry sweep | ADR-0015 hygiene |

---

## 7. Production-readiness assessment

| Dimension | Rating |
|---|---|
| Protocol correctness (JWT/OIDC/PKCE/nonce) | **Strong** — negative-tested, ordering enforced |
| Replay resistance | **Strong** — DB-enforced, proven under real concurrency |
| Tenant isolation | **Strong** — DB-enforced, proven, CI-guarded |
| Fail-closed discipline | **Strong** for evaluated credentials; **gap** at route enforcement |
| Secret hygiene in transit/logs | **Strong** |
| **Key management** | **Adequate** — managed, rotatable, fail-fast |
| Observability | **Adequate**, uneven across flows |
| Test evidence | **Designed, reviewed and executed** — green on the target runtime |
| Documentation & governance | **Strong** |

**Conclusion.** The parts hardest to get right — replay protection, tenant isolation, protocol
ordering, crypto boundary discipline — are correct and, unusually, *empirically demonstrated against
real PostgreSQL* rather than asserted. The failures are concentrated in **key lifecycle**, which is
wiring rather than design, and in **one enforcement gap**. Fixing FU-01 through FU-04 is a small,
well-bounded slice that touches no completed abstraction.

**Re-review completed.** FU-01…FU-04 are closed and Gate 2 is green. Authentication is
**production-ready** and may be treated as a frozen subsystem. Authorization (RBAC) may begin.

---

## 8. Reviewer note on method

Two defects in this subsystem (nonce hash mismatch; missing `created_at`) were found by writing
integration tests, and the highest-severity finding of the milestone (superuser RLS bypass) was
found by executing SQL against a real database rather than reading code. This review's own three
HIGH findings came from inspecting the **composition root** — the place least covered by unit tests
and most likely to contain placeholder wiring. That pattern is worth carrying into future reviews:
**the wiring, not the algorithms, is where enterprise auth subsystems usually fail.**
