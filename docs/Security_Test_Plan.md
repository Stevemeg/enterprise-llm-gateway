# Security Test Plan

**Phase:** 5 — Backend · Living document (started Milestone 3)
**Last updated:** 2026-07-18

Organizes security verification by area and bridges the **STRIDE** threat model
([architecture/security/02-threat-model-stride.md](architecture/security/02-threat-model-stride.md)) to
executable tests. Complements [Security_Traceability.md](Security_Traceability.md) (control→module map).
Status: ✅ implemented · ⏳ planned this/next slice · CI = enforced as a gate in Phase 11.

## 1. Tests by area

| Area | Tests | Status |
|------|-------|--------|
| **JWT** | expiry, audience, issuer, `kid`, algorithm confusion, tampered signature, wrong key, clock-skew, replay (`jti` uniqueness) | ✅ (`test_jwt.py`) |
| **API keys** | hashing (no plaintext), timing-safe verify, wrong/expired/inactive key, rotation | ✅ hashing/verify (`test_api_keys.py`, `test_authenticate_api_key.py`); ⏳ rotation |
| **Refresh tokens** | rotation, **reuse detection / theft**, expired, revoked-session | ✅ (`test_refresh_session.py`) |
| **OAuth / OIDC** | auth-code exchange, `state`/`nonce`/PKCE binding, id_token signature/iss/aud/exp, **replay & rotation matrix (see §1a)** | ⏳ M3d-2B |
| **Sessions** | expiration, logout revocation, per-device revoke | ✅ issue/logout (`test_session_usecases.py`); ⏳ device list |
| **Middleware** | bypass attempts (missing/invalid/expired credential), key-vs-JWT routing, fail-closed | ⏳ next slice |
| **Logging** | secret/PII leakage (redaction) | ✅ (`test_logging.py`) |
| **Audit** | completeness (every auth outcome emits an event), correlation id | ✅ use-case audit (`test_refresh_session.py`); ⏳ sink + middleware |
| **RLS** | tenant isolation (no cross-tenant read/write) | ✅ (`test_rls.py`, `test_uow_sqlite.py`); ⏳ full isolation suite (Postgres, Phase 13) |
| **Rate limits** | abuse / quota exhaustion / per-scope | ⏳ (Milestone: routing/limits) |
| **Secrets** | CSPRNG entropy floor, zeroization, no recoverable secret stored | ✅ (`test_secrets.py`) |

## 1a. OIDC replay & negative test matrix (M3d-2B — required before merge)

The OIDC authorization-code flow is the highest-risk new surface in Milestone 3d-2B. Every row below
is a **mandatory** negative/replay test; the flow may not merge until all are ✅. These realize the
fail-closed rule (§3.2) for federated login and the anti-replay guarantees in
[Authentication_State_Machine.md](Authentication_State_Machine.md).

| # | Attack / condition | Expected result | Realizes |
|---|--------------------|-----------------|----------|
| 1 | **Reused authorization code** (code redeemed twice) | 2nd exchange rejected; no second session minted | Replay / EoP |
| 2 | **Reused `state`** (same state presented twice) | rejected; single-use state consumed on first callback | CSRF / replay |
| 3 | **Reused `nonce`** (id_token nonce seen before) | rejected; nonce single-use per auth request | Replay |
| 4 | **Expired `state`** (past TTL) | rejected as unknown/expired; no session | Replay / DoS |
| 5 | **Expired `nonce`** (auth request TTL elapsed before callback) | rejected | Replay |
| 6 | **Wrong `iss`** (id_token issuer ≠ configured issuer) | rejected before session mint | Spoofing |
| 7 | **Wrong `aud`** (id_token audience ≠ our client_id) | rejected | Spoofing |
| 8 | **Wrong signing key** (id_token signed by key absent from JWKS) | rejected; no `kid` match | Spoofing / Tampering |
| 9 | **Invalid / unreachable JWKS** (malformed or fetch failure) | fail closed — reject, never fail open | Spoofing / DoS |
| 10 | **JWKS rotation** (signing `kid` rotates; old + new keys both honored during overlap) | id_tokens under either valid `kid` verify; retired key rejected after overlap | Availability + Spoofing |
| 11 | **PKCE mismatch** (`code_verifier` ≠ `code_challenge`) | exchange rejected | Interception |
| 12 | **Missing PKCE** (no verifier where challenge was issued) | rejected | Interception |
| 13 | **Tampered id_token** (payload/signature altered) | signature verify fails; rejected | Tampering |
| 14 | **State/nonce store fail-closed** (backing store unavailable) | callback denied, not admitted | Fail-closed (ADR-0009) |

Notes: single-use consumption of `state`, `nonce`, and authorization code must be **atomic** (consume =
delete/mark within the same transaction that admits the callback) so a concurrent replay cannot race a
second success. JWKS rotation (row 10) must honor an explicit overlap window (current + previous key),
mirroring the access-token `KeyProvider` rotation model already implemented in M3d-1.

## 2. Threat → Test mapping (STRIDE)

| Threat | Representative test(s) | Module under test |
|--------|------------------------|-------------------|
| **Spoofing** | JWT signature/kid/alg validation; API-key & service-account secret verification | `test_jwt.py`, `test_api_keys.py`, `test_authenticate_*` |
| **Tampering** | tampered-signature rejection; hashed-storage (no plaintext) | `test_jwt.py`, `test_api_keys.py` |
| **Repudiation** | auth-outcome audit events (reuse detected, refreshed, logout) | `test_refresh_session.py` (+ audit sink, next slice) |
| **Information disclosure** | log redaction; timing-safe compare; secret never returned | `test_logging.py`, `test_secrets.py` |
| **Denial of service** | rate-limit abuse scenarios | ⏳ (limits milestone) |
| **Elevation of privilege** | refresh-reuse → session revoked; expired/revoked credential rejected; (authorization in M4) | `test_refresh_session.py`; RBAC tests (M4) |

## 3. Standing security-test rules (CI gate — Phase 11)
1. **Negative test per public API.** Every security-sensitive module must have **at least one negative
   (failure-mode) test for every public function/method** — not only success paths. (e.g., if the auth
   layer exposes 8 public operations, each has a proving-failure test.) This prevents subtle security
   regressions. See CONTRIBUTING §11.
2. **Fail-closed by default.** Every auth/authorization path has a test asserting it denies on missing/
   invalid input (ADR-0009).
3. **No secret in output/logs.** A scan asserts responses, error bodies, and logs never contain secret
   material (FR-010).
4. **Isolation.** Cross-tenant access attempts must be denied (NFR-SEC07).

## 4. Coverage target
**100% of the authentication code path** covered by unit + failure-mode + security tests before
Milestone 3 closes; tracked in [Code_Traceability.md](Code_Traceability.md) (coverage-by-subsystem).

## 5. Traceability
STRIDE model + [Security_Traceability.md](Security_Traceability.md); ADR-0008/0009; NFR-SEC*. Executed in
CI (Phase 11) and expanded in the Phase-13 security/penetration testing.
