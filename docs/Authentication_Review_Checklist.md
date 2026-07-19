# Authentication Review Checklist

**Phase:** 5 — Backend · Security-review artifact
**Last updated:** 2026-07-15

Checklist for the **Authentication Security Review** held after Milestone 3d completes and before RBAC
(Milestone 4). Each item maps to a control in [Security_Traceability.md](Security_Traceability.md) and a
test in [Security_Test_Plan.md](Security_Test_Plan.md). Status: ✅ implemented + tested · ⏳ pending
(Milestone 3d-2). Use during the review; every ⏳ must become ✅ before authentication is signed off.

## JWT
- [x] Signature validation (RS256) — `test_jwt.py`, `test_token_service.py`
- [x] Algorithm allow-list; `alg:none` / HMAC alg-confusion rejected — `test_jwt.py`
- [x] `kid` handling (select key; unknown kid rejected) — `test_jwt.py`, `test_key_provider.py`
- [x] Clock-skew leeway — `test_jwt.py`
- [x] Expiry enforced — `test_jwt.py`
- [x] Issuer validated — `test_jwt.py` (wrong issuer ⇒ reject)
- [x] Audience validated — `test_jwt.py::wrong_audience`
- [x] Replay: unique `jti` per token; short TTL — `test_jwt.py`
- [ ] (Optional) `jti` denylist break-glass path — deferred (documented, ADR follow-up)

## API keys
- [x] SHA-256 hashing (no plaintext stored) — `test_api_keys.py`
- [x] Timing-safe comparison — `test_secrets.py`, `test_api_keys.py`
- [x] Prefix lookup (non-secret) then hash verify — `test_authenticate_api_key.py`
- [x] Inactive / expired / wrong-secret rejected — `test_authenticate_api_key.py`
- [ ] Rotation (issue new, revoke old, grace) — repository lands 3d-2

## Refresh tokens
- [x] Rotation on every use — `test_session_usecases.py`
- [x] Reuse detection → session revoked + audit — `test_session_usecases.py`
- [x] Revocation (logout revokes chain) — `test_session_usecases.py`
- [x] Expiry enforced — `test_session_usecases.py`
- [x] Hashed storage (only SHA-256 persisted) — by construction (`shared.secrets`)
- [ ] Persisted via SQLAlchemy repo against real schema — 3d-2

## Service accounts
- [x] Client-secret constant-time verification — `test_authenticate_service_account.py`
- [x] Disabled account rejected — `test_authenticate_service_account.py`
- [x] Credential storage schema decided (ADR-0013) + migration 0002
- [ ] SQLAlchemy `service_account_credential` repo + rotation — 3d-2

## Middleware
- [x] Public routes without credential pass — `test_authentication_middleware.py`
- [x] Protected routes attach principal — `test_authentication_middleware.py`
- [x] Invalid headers → 401 — `test_authentication_middleware.py`
- [x] Missing header → pass-through (route dependency enforces) — `test_authentication_middleware.py`
- [x] Correlation IDs in 401 body + logs — `test_authentication_middleware.py`
- [x] Audit events per decision (authenticated / rejected) — middleware + sink
- [ ] Wired into the production app factory — 3d-2

## OIDC
- [ ] PKCE (code_verifier / code_challenge) — 3d-2
- [ ] `state` single-use (CSRF for callback) — 3d-2
- [ ] `nonce` single-use (replay) — 3d-2
- [ ] id_token signature via IdP JWKS — 3d-2
- [ ] JWKS fetch + cache + refresh-on-unknown-kid — 3d-2
- [ ] Issuer + audience validation of id_token — 3d-2

## Tenant isolation (persistence)
- [x] Runtime connects as least-privilege `app_rw` (NOSUPERUSER, NOBYPASSRLS) — ADR-0014, migration 0003
- [x] Migrations run as a separate owner/migrator (not the runtime role) — `validate.*`
- [x] CI bypass-containment: runtime role is not superuser / not BYPASSRLS — `test_database_role.py`, `validate.*`
- [x] RLS enabled **and** forced on tenant tables; cross-tenant read blocked (A↔B) — `test_auth_rls_postgres.py`
- [x] Deny-by-default with no tenant context — `test_auth_rls_postgres.py`
- [x] New tenant tables auto-grant to `app_rw` — `test_default_privileges.py`
- [x] Merge guardrail: tenant table ⇒ ENABLE+FORCE RLS + policy — `scripts/check_migration_guardrails.py`

## Cross-cutting
- [x] Fail closed on every auth failure (401) — middleware + use-cases
- [x] No secrets/tokens logged (redaction) — `test_logging.py`
- [x] Single audited crypto boundary (import-linter) — 2 contracts kept
- [x] Structured audit events with correlation id — `test_logging_audit_sink.py`
- [ ] End-to-end integration on real Postgres (Gate 2) — after 3d-2

## Sign-off
Authentication is signed off when every box is ✅, coverage of the auth path is ~100%, and the
[Security review](Security_Traceability.md) records no open High/Critical findings.
