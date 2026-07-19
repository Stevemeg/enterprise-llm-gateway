# Code Traceability

**Phase:** 5 — Backend Implementation · Living document
**Last updated:** 2026-07-15 (Milestone 3 — design)

Maps every implemented backend module to the ADRs, requirements, and tests that justify and verify it.
Updated on **every** implementation milestone (Backend_Implementation_Guide.md §17, CONTRIBUTING §10).
Source: `backend/src/gateway/`. Layer legend: D=domain, A=application, X=adapters, L=delivery,
C=config, O=observability, S=shared.

## Milestone 1 — Foundation (skeleton, config, logging, DI)

| Module | Layer | ADR | FR | NFR | Tests |
|--------|-------|-----|----|----|-------|
| `config/settings.py` | C | 0001, 0011 | FR-146 | NFR-M01, NFR-D01, NFR-SEC03 | `test_settings.py`, `test_database_settings.py` |
| `observability/logging.py` | O | 0009 | FR-010, FR-082 | NFR-O01, NFR-O02 | `test_logging.py` |
| `shared/clock.py` | S | 0001 | — | NFR-M04 | `test_health.py` (FixedClock) |
| `shared/types.py` | S | 0001 | FR-080 | NFR-M03 | `test_app.py` |
| `config/container.py` | C | 0001 | FR-141 | NFR-M01, NFR-M02, NFR-D01 | `test_container.py` |
| `config/bootstrap.py` | C | 0001 | — | NFR-M01 | `test_app.py` |
| `delivery/http/app.py` | L | 0001 | — | NFR-M02 | `test_app.py` |
| `delivery/http/middleware/request_context.py` | L | 0009 | FR-080, FR-083 | NFR-O01 | `test_app.py` |
| `delivery/http/ops/health.py` | L | 0011 | FR-141 | NFR-A02, NFR-O03 | `test_health.py` |
| `delivery/http/ops/router.py` | L | 0005 | FR-080, FR-081 | NFR-O03 | `test_app.py` |
| `application/ports/health.py` | A | 0009 | FR-141 | NFR-O03 | `test_health.py` |

## Milestone 2 — Database Infrastructure

| Module | Layer | ADR | FR | NFR | Tests |
|--------|-------|-----|----|----|-------|
| `config/settings.py` → `DatabaseSettings` | C | 0002, 0010 | FR-146 | NFR-SEC03, NFR-S05 | `test_database_settings.py` |
| `adapters/persistence/engine.py` | X | 0001, 0002 | — | NFR-S01, NFR-S02, NFR-A03 | `test_engine.py` |
| `adapters/persistence/rls.py` | X | 0002 | FR-130, FR-131, FR-132 | NFR-SEC07 | `test_rls.py` |
| `adapters/persistence/uow.py` | X | 0002, 0004 | FR-063, FR-130 | NFR-P06, NFR-M02 | `test_uow_sqlite.py` |
| `adapters/persistence/health.py` | X | 0009 | — | NFR-A02, NFR-O03 | `test_db_health.py` |
| `application/ports/unit_of_work.py` | A | 0002, 0004 | FR-063 | NFR-M01, NFR-M02 | `test_uow_sqlite.py` |
| `application/ports/repository.py` | A | 0002 | FR-070, FR-113 | NFR-M02, NFR-SEC09 | (impls in later milestones) |
| `migrations/env.py` + `versions/0001_initial_schema.py` | — | 0002 | FR-070..077, FR-130..134 | NFR-S04, NFR-D01 | `test_alembic_config.py` |
| `config/container.py` (DB wiring) | C | 0001, 0002 | FR-141 | NFR-A02, NFR-D01 | `test_app.py`, `test_container.py` |

## Milestone 3 — Authentication

### 3a — Cryptographic core (implemented)

| Module | Layer | ADR | FR | NFR | Tests |
|--------|-------|-----|----|----|-------|
| `shared/secrets.py` (crypto boundary: CSPRNG, SHA-256, timing-safe, zeroize) | S | 0008, 0011 | FR-097 | NFR-SEC03, NFR-SEC04 | `test_secrets.py` |
| `domain/errors.py`, `domain/auth/errors.py` | D | 0008, 0009 | FR-090..097 | NFR-M01 | `test_jwt.py` (raises) |
| `adapters/security/keys.py` (RSA keygen, kid) | X | 0008 | FR-093 | NFR-SEC04 | `test_keys.py` |
| `adapters/security/jwt.py` (RS256 issue/verify, alg allow-list, skew) | X | 0008 | FR-090, FR-091 | NFR-SEC01/04, NFR-P01 | `test_jwt.py` |
| `adapters/security/jwks.py` (JWKS document) | X | 0008 | FR-092, FR-093 | NFR-SEC04 | `test_jwks.py` |
| `adapters/security/api_keys.py` (generate/hash/verify) | X | 0008, 0011 | FR-094, FR-097 | NFR-SEC03/04 | `test_api_keys.py` |

Enforced by two new import-linter contracts (primitives only in `shared.secrets`; jwt/cryptography
never in business logic) — the audited crypto boundary.

### 3c — Auth application logic (implemented)

| Module | Layer | ADR | FR | NFR | Tests |
|--------|-------|-----|----|----|-------|
| `shared/auth_constants.py` | S | 0008 | FR-094 | NFR-M03 | (used by api-key auth) |
| `domain/auth/models.py`, `errors.py` | D | 0008 | FR-090..098 | NFR-M01 | auth use-case tests |
| `application/ports/auth.py` (repos, TokenService, AuditSink) | A | 0008 | FR-090..098 | NFR-M02 | via use-cases |
| `application/auth/authenticate_api_key.py` | A | 0008 | FR-094..097 | NFR-SEC03/04 | `test_authenticate_api_key.py` |
| `application/auth/authenticate_service_account.py` | A | 0008 | FR-098 | NFR-SEC03/04 | `test_authenticate_service_account.py` |
| `application/auth/issue_session.py` | A | 0008 | FR-091 | NFR-SEC05 | `test_session_usecases.py` |
| `application/auth/refresh_session.py` (rotation + reuse detection) | A | 0008 | FR-091 | NFR-SEC05/09 | `test_session_usecases.py` |
| `application/auth/logout.py` | A | 0008 | FR-091 | NFR-SEC05 | `test_session_usecases.py` |

### 3d-1 — Auth verification & enforcement core (implemented)

| Module | Layer | ADR | FR | NFR | Tests |
|--------|-------|-----|----|----|-------|
| `adapters/security/key_provider.py` (rotation + JWKS) | X | 0008 | FR-092, FR-093 | NFR-SEC04 | `test_key_provider.py` |
| `adapters/security/token_service.py` (JWT issue/verify) | X | 0008 | FR-091 | NFR-SEC01/04, NFR-P01 | `test_token_service.py` |
| `adapters/audit/logging_sink.py` (structured auth audit) | X | 0008, 0009 | FR-101 | NFR-SEC09 | `test_logging_audit_sink.py` |
| `application/auth/authenticate_request.py` (composite) | A | 0008 | FR-090..097 | NFR-SEC05 | `test_authentication_middleware.py` |
| `application/ports/auth.py` (AccessTokenVerifier, Authenticator) | A | 0008 | FR-090..097 | NFR-M02 | via middleware |
| `delivery/http/middleware/authentication.py` (fail closed) | L | 0008, 0009 | FR-090..097 | NFR-A04, NFR-SEC05 | `test_authentication_middleware.py` |

### Schema evolution — service-account credential (ADR-0013)

The approved `service_account` table had no credential column, so client-credential auth was
impossible. Resolved explicitly via **ADR-0013**: new `service_account_credential` table
(hashed secret, `client_id`, status, rotation), **Alembic migration 0002**, and updates to
Schema.sql, ERD, Data_Dictionary, Database_Design (DB-DEC-09), Database_Dependency_Map, and
OpenAPI (credential endpoints). The SQLAlchemy repository lands in 3d-2.

### 3d-2A — SQLAlchemy auth repositories (implemented)

| Module | Layer | ADR | FR | NFR | Tests |
|--------|-------|-----|----|----|-------|
| `adapters/persistence/tables.py` (auth Core tables) | X | 0002,0008,0013 | — | NFR-M02 | integration |
| `repositories/auth_repositories.py` (api_key, sa_credential, session, refresh, oauth) | X | 0002,0008,0013 | FR-091,094-098 | NFR-SEC03/07, P06 | `test_auth_repositories_sqlite.py`, `test_auth_rls_postgres.py` |
| `application/ports/auth.py` (+OAuthIdentity/SA-credential repos) | A | 0008,0013 | FR-092,098 | NFR-M02 | via repos |
| `application/auth/authenticate_service_account.py` (→ credential repo) | A | 0013 | FR-098 | NFR-SEC03/04 | `test_authenticate_service_account.py` |

Validated: CRUD, transaction commit, rollback (SQLite via UoW); RLS cross-tenant read blocked (Postgres, Gate 2/CI — skipped in sandbox).

### 3d-2B — OIDC, middleware wiring, container (planned — next slice)

OIDC login, the authentication middleware, SQLAlchemy auth repositories, the concrete JWT-backed
TokenService + KeyProvider, and the audit sink — enumerated in [Security_Traceability.md](Security_Traceability.md) §1
(rows still marked *(M3)*). Filled in as each lands.

## Coverage by subsystem

Test-type coverage per subsystem (✅ present · — not applicable yet · ⏳ planned this/next milestone).
"Performance" = documented perf considerations and/or a perf-sensitive test.

| Subsystem | Unit | Integration | Failure-mode | Security | Performance |
|-----------|:----:|:-----------:|:------------:|:--------:|:-----------:|
| Config | ✅ | — | ✅ | ✅ (safe_url masking) | — |
| Logging | ✅ | — | — | ✅ (redaction) | — |
| DI / Bootstrap | ✅ | ✅ (app wiring) | — | — | — |
| Health / Ops | ✅ | ✅ (via app) | ✅ (raising/failing checks) | — | — |
| Database (engine/pool) | ✅ | ✅ (SQLite) | ✅ (unreachable) | ✅ (RLS statement) | ✅ (pool config) |
| Unit of Work / RLS | ✅ | ✅ (commit/rollback) | ✅ (rollback-on-error) | ✅ (tenant scoping) | ✅ (tx boundary) |
| Alembic / Migrations | ✅ (config) | ⏳ (Postgres in CI) | — | — | — |
| **Auth — crypto core** | ✅ | — | ✅ (expired/tampered/kid/alg-confusion) | ✅ (timing-safe, alg allow-list) | ✅ (stateless verify) |
| **Auth — token/session logic** | ✅ | — | ✅ (reuse/expired/revoked/wrong-secret) | ✅ (constant-time, reuse detection) | ✅ (stateless issue) |
| **Auth — verify/middleware** | ✅ | ✅ (TestClient) | ✅ (invalid/expired/malformed) | ✅ (fail-closed, rotation) | ✅ (stateless verify) |
| **Auth — repositories** | — | ✅ (SQLite; PG in CI) | ✅ (rollback) | ✅ (RLS test, hashed storage) | ✅ (UoW tx) |
| **Auth — OIDC/wiring** | ✅ | ✅ (state store, PG) | ✅ (replay, expiry, tamper) | ✅ (single-use consume, HMAC state) | ✅ (bounded timeouts, 0 retries) |

Targets for Authentication (M3 implementation): **100% of the authentication code path** covered by
unit + failure-mode + security tests, with performance notes on stateless JWT validation (hot path)
and constant-time comparison.

## Verification summary (Milestone 2)
- **DB connection / pool:** `test_engine.py`. **Session/transaction lifecycle:** `test_uow_sqlite.py`.
- **RLS propagation:** `test_rls.py`. **Alembic:** `test_alembic_config.py`. **Failure modes:**
  `test_db_health.py`. All gates green (ruff, mypy --strict, pytest, import-linter ×5).


## Phase 4 — Enterprise AI OS Foundation

Architecture-only milestones. **No business logic, no schema changes, no API changes.** Governed by
[ADR-0016](adr/0016-enterprise-ai-os-architecture.md); empirical results in
[Architecture_Evidence_Log.md](Architecture_Evidence_Log.md).

### Slice 1 — AI OS Foundation — ✅ COMPLETE

| Seam (Tier-1 invariant) | Protocol | Validation implementation (Rule 4) | Enforcement |
|---|---|---|---|
| MCP-compatible execution | `application/ports/mcp.py` | `adapters/mcp/null_gateway.py` | ports carry no transport |
| Tool Registry | `application/ports/tools.py` | `adapters/tools/in_memory_registry.py` | seam adapters independent |
| Explainable routing | `domain/routing/models.py` | — (consumed in Slice 2) | construction guard (Slice 2) |
| Agent lifecycle | `application/ports/agents.py` | `adapters/agents/skeleton.py` | protocol conformance tests |
| Pipeline stage | `application/ports/pipeline.py` | `adapters/pipeline/noop_stage.py` | protocol conformance tests |

Contracts added: domain is innermost · ports declare contracts only · seam adapters independent.
Each observed failing on a deliberate violation. **Gate 2: 189 passed, 0 skipped, 95%.**

### Slice 2 — Agent Runtime — ✅ COMPLETE

| Component | Module | Tests | Enforcement |
|---|---|---|---|
| AgentRuntime (sole `RoutingDecision` construction site) | `application/agents/runtime.py` | `test_agent_runtime.py` (11) | Guard 1 — AST construction scan |
| PlannerAgent | `application/agents/planner.py` | ✅ | Guards 2-4 |
| Policy / Cost / Health / Provider agents (stubs) | `application/agents/{policy,cost,health,provider}.py` | ✅ | Guards 2-4 |
| Agent scaffolding | `application/agents/base.py` | ✅ | — |
| Pipeline integration (first consumer of the seam) | `adapters/pipeline/routing_stage.py` | `test_agent_routing_stage.py` (6) | protocol conformance |

**Guards (all observed failing before being trusted):** 1 `RoutingDecision` single construction
site (AST scan, wired into `validate.ps1`) · 2 agents may not orchestrate · 3 agent
implementations mutually independent · 4 agents depend on protocols/domain only.

**Gate 2: PASS — 206 passed, 0 skipped, 95% coverage, mypy strict clean (138 files),
import-linter 13 kept / 0 broken.**

**Rule 5 event:** `PipelineStage` gained `@runtime_checkable`, driven by its first consumer.
No members added; no superseding ADR required. Recorded in the evidence log.

## Milestone status

| Milestone | Type | Status | Gate 2 |
|---|---|---|---|
| M1 Foundation | — | ✅ Complete | ✅ |
| M2 Database Infrastructure | — | ✅ Complete | ✅ |
| M3 Authentication | — | ✅ Complete + Security Review closed | ✅ 169 → 189 |
| Phase 4 Slice 1 — AI OS Foundation | Foundation | ✅ Complete | ✅ 189 passed, 0 skipped |
| Phase 4 Slice 2 — Agent Runtime | Foundation | ✅ Complete | ✅ 206 passed, 0 skipped, 95% |
| **Phase 4 Slice 3 — Tool Registry** | **Foundation** | **✅ COMPLETE** | **✅ 252 passed, 0 skipped, 95%** |
| MCP Gateway | Foundation | ⏳ | — |
| RBAC | Capability | ⏳ | — |

### Slice 3 — Tool Registry — ✅ COMPLETE

First milestone with a **pre-registered prediction** (written before implementation), so its result
is genuine evidence rather than hindsight. Central question — *can `ToolRegistry` support multiple
implementations with no protocol change?* — answered **yes**. Rule 5 **not triggered**;
`application/ports/tools.py` unchanged.

| Component | Module | Tests |
|---|---|---|
| Registry backend 1 | `adapters/tools/in_memory_registry.py` | parity suite |
| Registry backend 2 (manifest-seeded) | `adapters/tools/static_manifest_registry.py` | parity suite + manifest loading |
| First consumer | `application/tools/catalog.py` | `test_tool_catalog.py` (10, both backends) |
| Parity / conformance | — | `test_tool_registry_parity.py` (14, both backends) |

**Guards (all observed failing before being trusted):** A consumers depend on the protocol only
(import-linter) · B registry implementations mutually independent (import-linter) · C construction
confined to the composition root (AST scan, `scripts/check_registry_construction.py`, wired into
`validate.ps1`).

**Gate 2: PASS — 252 passed, 0 skipped, 95% coverage, mypy strict clean, import-linter 15 kept / 0 broken.**

**Known limitation:** Guard C constrains no production code until a composition-root wiring exists;
its violation proof demonstrates it bites. Recorded in the evidence log.
