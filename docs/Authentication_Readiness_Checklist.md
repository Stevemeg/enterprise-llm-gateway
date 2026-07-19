# Authentication Readiness Checklist (Deployment)

**Phase:** 5 — Backend · Milestone 3d-2B
**Last updated:** 2026-07-18
**Purpose:** an *operational* pre-flight for staging/production. Not a design document — every
line is something an operator verifies before or during a deploy. Design rationale lives in
[Authentication_Architecture.md](Authentication_Architecture.md) and the ADRs.

Legend: ☐ verify per environment · **[auto]** = enforced by code/CI (still confirm it ran).

## Cryptography
- ☐ RSA signing keypair generated for the environment (never shared across environments)
- ☐ `kid` set and rotation procedure configured — see [Credential_Rotation_Guide.md](Credential_Rotation_Guide.md)
- ☐ JWKS endpoint reachable from clients/IdP; serves the **current** key
- ☐ **Previous signing key retained** through the overlap window (rotation must not log users out)
- ☐ Clock-skew leeway configured (`GATEWAY_AUTH__CLOCK_SKEW_LEEWAY_SECONDS`, default 60s)
- ☐ Signing keys sourced from the secrets manager — never from env literals or the repo (ADR-0011)
- ☐ **[auto]** Algorithm allow-list rejects `alg:none`/HMAC confusion

## Database
- ☐ `app_rw` role exists and the app connects **as it** (`GATEWAY_DATABASE__URL`)
- ☐ `app_rw` is `NOSUPERUSER` **and** `NOBYPASSRLS` — **[auto]** `validate.*` bypass-containment gate
- ☐ Migrations run as the **owner/migrator**, not `app_rw` (`GATEWAY_MIGRATION_DATABASE__URL`)
- ☐ RLS **enabled** and **FORCED** on every tenant table — **[auto]** migration guardrail
- ☐ `ALTER DEFAULT PRIVILEGES` verified — **[auto]** `test_default_privileges.py`
- ☐ Migration head current (`alembic current` == `0004_oidc_login_state`)
- ☐ Expired `oidc_login_state` sweep scheduled (or accepted as pending — read path already fails closed)

## OIDC
- ☐ `redirect_uri` **exactly** matches the value registered at the provider (exact-match, not prefix)
- ☐ PKCE enabled (`S256`) — **[auto]** asserted in tests
- ☐ Nonce enabled and verified by hash — **[auto]**
- ☐ **State signing key configured** from the secrets manager (`GATEWAY_AUTH__STATE_SIGNING_KEY_REF`);
      production start-up **fails fast** if unset. A per-process ephemeral key would break logins
      across multiple instances — confirm this is a real reference, not the dev fallback.
- ☐ JWKS URI reachable; cache healthy; TTL = 10 min; unknown-`kid` refresh works against the real IdP
- ☐ IdP client secret stored as a reference, not inline
- ☐ Timeouts confirmed: connect 2s / read 5s / total 7s / **0 retries**

## Runtime
- ☐ `/metrics` exposed and scraped; `gateway_auth_duration_seconds` present after first login
- ☐ Audit sink configured and shipping (`auth_audit` events reaching the log pipeline)
- ☐ Secrets manager reachable; start-up fails fast if a required secret is missing
- ☐ TLS terminated in front of the gateway; HTTP disabled or redirected
- ☐ Correlation IDs present on requests and on 401 bodies
- ☐ Log redaction active — spot-check that no token/verifier/secret appears in logs

## Validation
- ☐ **Gate 1** passed (ruff, format, mypy, import-linter, migration guardrail, pytest)
- ☐ **Gate 2** passed on real PostgreSQL — **0 skipped**
- ☐ Coverage ≥ target on the authentication path
- ☐ Authentication Security Review passed with no open High/Critical findings

## Rollback triggers
Roll back the deploy if any of these appear after release:
- ☐ `gateway_auth_duration_seconds{result="failure"}` rises sharply vs. baseline
- ☐ `gateway_oidc_jwks_fetch_failures_total` climbing (IdP/JWKS unreachable ⇒ logins fail closed)
- ☐ Any 5xx on the auth path (auth must fail *closed* with 401, never 500)
- ☐ Cross-tenant data visible in any report (stop immediately; RLS regression)
