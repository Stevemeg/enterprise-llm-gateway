# Authentication Completion Report (Milestone 3d)

**Phase:** 5 — Backend · Milestone 3d (3d-1, 3d-2A, 3d-2A.5, 3d-2B)
**Status:** Implementation complete — **pending the Authentication Security Review** and Gate 2 execution
**Last updated:** 2026-07-18

## 1. What was built

| Area | Delivered | Key artifacts |
|---|---|---|
| Crypto core | Single crypto boundary; RS256 JWT w/ `kid`, algorithm allow-list, skew leeway; API-key + secret hashing; CSPRNG; zeroization | `shared/secrets.py`, `adapters/security/{jwt,key_provider,api_keys,token_service}.py` |
| Persistence | 6 auth tables + repositories; RLS-scoped; SQLite + Postgres portable | `adapters/persistence/{tables,repositories}` |
| DB hardening | `app_rw` least-privilege runtime role; owner/migrator split; append-only privileges; merge guardrail | ADR-0014, migration `0003`, `check_migration_guardrails.py` |
| OIDC | Auth-code + PKCE(S256), HMAC-signed state, nonce-by-hash, JWKS cache w/ rotation + throttle, bounded timeouts | ADR-0015, migration `0004`, `adapters/security/{oidc_state,jwks_cache,oidc_provider}.py` |
| Request lifecycle | One immutable `AuthenticationContext`; central `AuthenticationDecision`; fail-closed middleware | `domain/auth/models.py`, `delivery/http/middleware/authentication.py` |
| Observability | Auth latency histogram; JWKS/token-exchange failure counters; structured audit sink (composite) | `observability/metrics.py`, `adapters/audit/composite_sink.py` |
| Wiring | Auth object graph in the composition root; auth settings with fail-fast production invariants | `config/container.py`, `config/settings.py` |

## 2. Authentication Integration Matrix

Coverage per flow. **Reported honestly — ⚠️ marks a real gap, not an aspiration.**

| Flow | Unit | Integration | Failure | Replay | Audit | Metrics |
|---|---|---|---|---|---|---|
| **JWT** | ✅ | ✅ middleware e2e | ✅ | N/A | ✅ | ✅ |
| **API Key** | ✅ | ✅ middleware e2e | ✅ | N/A | ✅ | ✅ |
| **Service Account** | ✅ | ⚠️ repo-level only | ✅ | N/A | ✅ | ⚠️ |
| **OIDC** | ✅ | ✅ full orchestration | ✅ | ✅ | ✅ | ⚠️ |
| **Refresh** | ✅ | ⚠️ fakes only | ✅ | ✅ reuse detection | ✅ | ⚠️ |

**Gaps and why they exist**

1. **Metrics on non-middleware flows (⚠️).** `gateway_auth_duration_seconds` is recorded in the
   HTTP middleware, so it covers the bearer paths (JWT, API key). OIDC login, refresh, and
   service-account token-mint are **use-case** flows that do not pass through that middleware, so
   they are currently observable only via their failure counters and audit events, not latency.
   *Fix:* record the histogram in those use-cases (small, mechanical).
2. **Service-account integration (⚠️).** Covered by unit tests and repository integration tests,
   but there is no end-to-end client-credentials→token test, because the token-mint endpoint is
   not yet exposed. *Fix:* lands with the admin/API surface milestone.
3. **Refresh integration (⚠️).** Rotation and reuse detection are proven against in-memory fakes,
   not real PostgreSQL. *Fix:* a Postgres refresh-rotation test in the Gate-2 suite.

None of these are correctness or security defects — they are observability and test-depth gaps,
each with a known fix. They are listed as inputs to the Security Review rather than hidden.

## 3. Defects found and fixed during the milestone

| # | Defect | How it was found | Impact if shipped |
|---|---|---|---|
| 1 | Application connected as a **superuser**, so RLS was bypassed entirely | Empirical Postgres test during Gate-2 wiring | **Tenant isolation would have been a no-op** — highest-severity find |
| 2 | `service_account` had no credential column | Design review before implementation | Client-credentials auth impossible |
| 3 | `id_token` nonce compared raw-vs-hash | Writing the end-to-end OIDC test | Every OIDC login would fail closed |
| 4 | `SessionRecord` constructed without `created_at` | End-to-end OIDC test | Runtime `TypeError` on every successful login |
| 5 | Repos set `revoked_at=None` on revoke | Implementation review | Revocation not auditable |

Defects 3 and 4 were invisible to unit tests and surfaced only from integration-level testing.

## 4. Validation status

- **Gate 1 (sandbox):** ruff check + format, compile, import-linter contracts, migration guardrail — green.
  *Caveat:* the sandbox is Python 3.10 against a 3.13 codebase, so tests are **statically validated,
  not executed** here.
- **Gate 2 (developer machine, real PostgreSQL):** **not yet run for this milestone** — required to
  close it. Target: all tests pass, **0 skipped**.
- **Empirically proven on real PostgreSQL:** superuser bypasses RLS while `app_rw` enforces it;
  symmetric tenant isolation; deny-by-default without tenant context; append-only privileges;
  `ALTER DEFAULT PRIVILEGES` on new tables; **concurrent-callback race yields exactly one winner**.

## 5. Exit criteria for Milestone 3d

| Criterion | Status |
|---|---|
| All auth flows implemented, fail closed | ✅ |
| Tenant isolation DB-enforced under the runtime role | ✅ (proven) |
| Single crypto boundary upheld | ✅ (import-linter) |
| Schema changes ADR-governed + guardrailed | ✅ (ADR-0013/0014/0015) |
| Documentation complete | ✅ (this report + data flow + readiness checklist) |
| Gate 1 green | ✅ |
| Gate 2 green, 0 skipped | ⏳ **pending execution** |
| Security Review passed | ⏳ **next milestone** |

## 6. Recommendation

Authentication is **implementation-complete and ready for review**, not yet ready to be called
production-ready. Two things must happen before that claim: **Gate 2 must run green with 0
skipped**, and the **Authentication Security Review** must answer its twelve questions with "No"
or "Mitigated and tested". The three matrix gaps above should be closed or explicitly accepted
during that review. No RBAC work should begin until both are done.
