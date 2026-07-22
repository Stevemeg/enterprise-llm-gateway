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
| **Phase 4 Slice 4 — MCP Gateway** | **Foundation** | **✅ COMPLETE** | **✅ 272 passed, 0 skipped, 96%** |
| **Phase 4 Stabilization — validation parity** | Stabilization | **✅ COMPLETE** | **✅ guard sets identical in both scripts** |
| **Phase 4 Slice 5 — RBAC Foundation** | **Capability** | **✅ COMPLETE** | **✅ 294 passed, 0 skipped, 95%** |
| **Phase 4 Slice 6 — Routing Engine** | **Capability** | **✅ COMPLETE** | **✅ 307 passed, 0 skipped, 96%** |
| **Phase 4 Slice 7 — Provider Execution** | **Capability** | **✅ COMPLETE** | **✅ Gate 1 + Gate 2 PASS: 315 passed, 0 skipped, 96% coverage** |
| **Phase 4 Slice 8 — Usage Metering, Cost Accounting & Budget Enforcement** | **Capability** | **✅ COMPLETE** | **✅ Gate 1 + Gate 2 PASS: 352 passed, 0 skipped, 96% coverage** |
| **Phase 4 Slice 9 — Persistent Usage Ledger & Atomic Budget Settlement** | **Capability** | **✅ COMPLETE** | **✅ Gate 1 + Gate 2 PASS: 397 passed, 0 skipped, 96% coverage** |
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

### Slice 4 — MCP Gateway — ✅ COMPLETE

| Component | Module | Role |
|---|---|---|
| MCP server simulation | `adapters/mcp/fake_server.py` | Scriptable stand-in; no networking, auth or retries |
| MCP gateway | `adapters/mcp/in_memory_gateway.py` | Implements `McpGateway`; maps MCP -> `ToolDescriptor` |
| First consumer | `application/tools/mcp_provisioner.py` | `discover -> register -> resolve -> invoke -> result` |
| Guard | `scripts/check_mcp_construction.py` | Only the composition root may construct a gateway |

`required_permissions` is supplied by deployment configuration and **never** read from MCP
metadata - a remote server must not declare its own authorization bar.

### Slice 5 — RBAC Foundation — ✅ COMPLETE

| Component | Module | Role |
|---|---|---|
| Port (RBAC-owned) | `application/ports/authorization.py` | `PermissionResolver`; unknown principal -> empty set |
| Declaration | `application/authorization/requirements.py` | Producer-owned; `declare()`, `PermissionRequirement` |
| Enforcement | `adapters/pipeline/authorization_stage.py` | Sole interpreter of RBAC keys in `attributes` |
| Resolvers | `adapters/authorization/{null,in_memory}_resolver.py` | Rule 4 pair |
| Guard | `scripts/check_resolver_construction.py` | Only the composition root may construct a resolver |

An undeclared requirement is denied: a route nobody classified is not a public route.

### Slice 6 — Routing Engine — ✅ COMPLETE

Three orchestration layers, one job each:

| Component | Module | Role |
|---|---|---|
| Agent orchestrator | `application/agents/runtime.py` | Sequences agents; **sole** `RoutingDecision` author |
| Routing orchestrator | `application/routing/engine.py` | Supplies candidates, resolves the selection |
| Pipeline adapter | `adapters/pipeline/routing_stage.py` | Transports the result (refactored to depend on the engine) |
| Port (capability-owned) | `application/ports/routing.py` | `RoutingEngine`, `RoutingExecution`, `RoutingIntegrityError` |
| Catalog | `application/routing/catalog.py` | `ProviderCatalog` + `InMemoryProviderCatalog`, tenant-keyed |
| Composition root | `config/container.py` | Constructs the routing graph; catalog starts empty |
| Guards | `scripts/check_routing_engine.py` | K: construction confined · L: sole `AgentRuntime` caller |

`RoutingExecution` is limited to `{decision, provider}`; `RoutingDecision` remains the only
explanation. `RoutingIntegrityError` is an exception, never an explainable outcome.

### Slice 7 — Provider Execution — ✅ COMPLETE

Rule 5 **not triggered**: `RoutingDecision` and `RoutingExecution` are unchanged; neither carries
a request payload. `InferenceRequest` is a new, capability-owned typed object (Rule 3) passed to
`ProviderExecutor.execute()` alongside — never inside — the `RoutingExecution`.

| Component | Module | Role |
|---|---|---|
| Port (capability-owned) | `application/ports/providers.py` | `ProviderClient`, `InferenceRequest`, `ProviderResponse` |
| Provider orchestrator | `application/providers/provider_executor.py` | `ProviderExecutor`; turns a routed selection into one provider call |
| Validation implementation 1 (Rule 4) | `adapters/providers/in_memory_client.py` | `InMemoryProviderClient`; deterministic, always succeeds |
| Validation implementation 2 (Rule 4) | `adapters/providers/fake_client.py` | `FakeProviderClient`; scriptable, exercises failure paths |
| Composition root | `config/container.py` | Constructs `provider_client` + `provider_executor` (Guard 1) |
| Guard 1 (new) | `scripts/check_provider_construction.py` | Construction of `InMemoryProviderClient`/`FakeProviderClient`/`ProviderExecutor` confined to the composition root |
| Guard 2 (new) | `pyproject.toml` import-linter | `in_memory_client` and `fake_client` mutually independent |
| Guard L (reused, unchanged) | `scripts/check_routing_engine.py` | `AgentRuntime` remains reachable only from the routing engine — proven to also catch `ProviderExecutor` |

`ProviderExecutor` never reaches `AgentRuntime` and never re-decides a routing outcome: an unrouted
`RoutingExecution` (any outcome but `SELECTED`, or no resolved provider) is refused before the
client is called — `not_routed: <outcome>` is data, not an exception, matching `McpResult`'s
fail-as-data convention. All three guards (1, 2, reused L) were proven by deliberate violation and
restoration before Gate 1 closed. Tests: `test_provider_executor.py` (9), `test_container.py`
wiring (1).

**Gate 1 + Gate 2: PASS — 315 passed, 0 skipped, 96% coverage, mypy strict clean (167 files),
import-linter 21 kept / 0 broken.** Alembic at head (`0005_rls_nullif_org_guc`); runtime role
verified `app_rw`, `rolsuper=False`, `rolbypassrls=False`. All Postgres-backed integration and
security tests (RLS isolation, OIDC state store, database role, default privileges) executed
against real PostgreSQL 16 + pgvector, none skipped.

### Slice 8 — Usage Metering, Cost Accounting & Budget Enforcement — ✅ COMPLETE

Rule 5 **not triggered against Tier 1** (zero diff on `domain/`, `ports/routing.py`,
`pipeline.py`, `tools.py`, `mcp.py`, `agents.py`, `application/agents/cost.py`). **Triggered and
satisfied** against the Slice-7 capability-owned `ProviderResponse`: an additive
`usage: ProviderUsage | None = None` field, consumed by the new `CostAccountant` — every Slice-7
construction remains valid unchanged. No migration added; `docs/Schema.sql`'s `budget`,
`reservation`, `price_table`, `usage_ledger` are documented but not yet migrated, so this slice
proves the architecture via capability-owned in-memory ports instead, matching every prior
capability slice's pattern.

| Component | Module | Role |
|---|---|---|
| Port (capability-owned) | `application/ports/money.py` | `Money` — `Decimal` + ISO-4217 currency, 8dp/`ROUND_HALF_EVEN` quantization (the project's first established rounding rule) |
| Port (capability-owned) | `application/ports/pricing.py` | `PricingPort`, `ModelPrice` — input/output price per 1k tokens, global (not tenant-scoped) |
| Port (capability-owned) | `application/ports/budget.py` | `BudgetPort`, `BudgetSnapshot`, `BudgetUnavailableError`, `UnsupportedCurrencyError` — hard budgets only, no `limit_kind` |
| Port (widened, Rule 5) | `application/ports/providers.py` | `ProviderUsage` added; `ProviderResponse.usage: ProviderUsage \| None` |
| Cost orchestrator | `application/accounting/cost_accountant.py` | `CostAccountant`; usage × price → `CostRecord`; raises `MissingUsageError`/`MalformedUsageError`/`UnknownPriceError` (defects, never budget outcomes) |
| Budget orchestrator | `application/accounting/budget_enforcer.py` | `BudgetEnforcer`; `CostRecord`'s `Money` × `BudgetSnapshot` → `BudgetDecision` (`ALLOWED`/`EXCEEDED`/`UNAVAILABLE`) |
| Validation implementation (Rule 4) | `adapters/pricing/static_price_table.py` | `StaticPriceTable`; deterministic, seeded at construction, sole implementation |
| Validation implementation (Rule 4) | `adapters/budget/in_memory_budget_store.py` | `InMemoryBudgetStore`; process-local, idempotent `record()` keyed by `correlation_id`, sole implementation |
| Composition root | `config/container.py` | Constructs `pricing_port`, `budget_port`, `cost_accountant`, `budget_enforcer` (Guard 1); both adapters start empty |
| Guard 1 (new) | `scripts/check_accounting_construction.py` | Construction of `StaticPriceTable`/`InMemoryBudgetStore`/`CostAccountant`/`BudgetEnforcer` confined to the composition root |
| Guard B (new) | `pyproject.toml` import-linter | `gateway.application.providers` forbidden from importing `gateway.application.accounting` |
| Guard L (reused, unchanged) | `scripts/check_routing_engine.py` | Proven a second time against a file it predates: `AgentRuntime` reference in `cost_accountant.py` caught with zero script changes |

Three of six candidate enforcement properties were evaluated and **deliberately not built**:
"executor can't import pricing/budget adapters" and "accounting depends on ports not adapters"
are already redundant with the blanket "application is framework-free and inward-only" contract;
"pricing/budget adapters mutually independent" is not applicable — exactly one implementation
exists per port, so an independence contract would have nothing to be independent from. Recorded
in [Architecture_Evidence_Log.md](Architecture_Evidence_Log.md), not silently skipped.

**Documented limitations (not omissions):** `BudgetPort.snapshot()`/`.record()` are two separate
awaits — deterministic accounting of already-incurred cost, not atomic concurrency-safe
enforcement (ADR-0004 explicitly rejects this shape as the sole hot-path mechanism). Idempotency
is process-local, keyed by `correlation_id` (the only stable per-execution identifier the
architecture provides today) — prevents double-charging on retry within one process; does not
survive a restart or coordinate across replicas.

Tests: `test_money.py` (6), `test_cost_accountant.py` (11), `test_budget_enforcer.py` (10),
`test_in_memory_budget_store.py` (4), plus `test_provider_executor.py` (+2) and
`test_container.py` (+1) for the widened/wired seams.

**Gate 1 + Gate 2: PASS — 352 passed, 0 skipped, 96% coverage, mypy strict clean (181 files),
import-linter 22 kept / 0 broken.** Alembic at head (`0005_rls_nullif_org_guc`); runtime role
verified `app_rw`, `rolsuper=False`, `rolbypassrls=False`. All Postgres-backed integration and
security tests executed against real PostgreSQL 16 + pgvector, none skipped.

### Slice 9 — Persistent Usage Ledger & Atomic Budget Settlement — ✅ COMPLETE

Rule 5 **not triggered against Tier 1** (zero diff on `domain/`, `ports/routing.py`,
`pipeline.py`, `tools.py`, `mcp.py`, `agents.py`, `application/agents/cost.py`,
`docs/adr/0016-*.md`). Genuine hard-budget enforcement requires reservation *before* provider
execution — confirmed and represented capability-locally (no Tier-1 change, no Redis): a new
`BudgetLedgerPort` gates `ProviderExecutor.execute()` via `ReservationService`. New **ADR-0017**
adopted: PostgreSQL-transactional reserve/commit (a single atomic conditional `UPDATE`) as the
current, verified mechanism, scoping — not reversing — ADR-0004's Redis Lua decision (that
rejection was a hot-path performance finding, not a correctness one; this project has no
load-testing milestone yet). A new migration (`0006_budget_ledger`) was required, but deliberately
does **not** reuse the pre-existing `budget`/`reservation`/`usage_ledger` tables from
`0001_initial.sql` — those model unconsumed hierarchical scope and a provider/model catalog FK,
and type their request identity as a globally-unique `uuid`, incompatible with
`InferenceRequest.correlation_id`'s tenant-local `str` identity. See ADR-0017 and
[Architecture_Evidence_Log.md](Architecture_Evidence_Log.md) for the full analysis.

| Component | Module | Role |
|---|---|---|
| Port (capability-owned, new) | `application/ports/ledger.py` | `BudgetLedgerPort`, `ReservationOutcome`, `ReservationResult`, `SettlementDetail`, `LedgerUnavailableError`, `UnknownReservationError` |
| Estimator (new) | `application/accounting/estimator.py` | `estimate_usage()` — deterministic, conservative, character-based pre-call token estimate (no tokenizer exists) |
| Shared cost math (extracted) | `application/accounting/cost_accountant.py` | `compute_cost()` factored out so `ReservationService`'s estimate and `CostAccountant`'s actual cost round identically (Rule 3) |
| Reservation orchestrator (new) | `application/accounting/reservation_service.py` | `ReservationService`; sequences `reserve()` → (caller calls `ProviderExecutor.execute()`) → `settle()`/`release()` |
| Validation implementation (Rule 4, real) | `adapters/ledger/sql_budget_ledger.py` | `SqlBudgetLedger`; atomic conditional `UPDATE ... WHERE ... RETURNING` (reserve), `SELECT ... FOR UPDATE` (settle/release), and a `pg_advisory_xact_lock` keyed on `(organization_id, correlation_id)` (reserve, closes the same-id concurrent-duplicate race) against real PostgreSQL |
| Validation implementation (Rule 4, fast double) | `adapters/ledger/in_memory_budget_ledger.py` | `InMemoryBudgetLedger`; process-local, documented as NOT proving atomicity |
| SQLAlchemy Core tables (new) | `adapters/persistence/ledger_tables.py` | `org_budget`, `budget_reservation`, `cost_ledger` |
| Migration (new) | `migrations/versions/0006_budget_ledger.py` + `sql/0006_budget_ledger.sql` | Creates the three new tables, RLS (ENABLE+FORCE+policy), append-only `REVOKE` on `cost_ledger` |
| Composition root | `config/container.py` | Constructs `ledger_port` (`SqlBudgetLedger` if `rls_enabled` else `InMemoryBudgetLedger`) and `reservation_service` (Guard 1, extended) |
| Guard 1 (extended, unmodified logic) | `scripts/check_accounting_construction.py` | `TARGETS`/`IMPLEMENTATIONS` extended with the three new classes — same script, same pattern as Slice 8 |
| Guard C (new) | `pyproject.toml` import-linter | `SqlBudgetLedger`/`InMemoryBudgetLedger` mutually independent |
| Guard B (reused, unchanged) | `pyproject.toml` import-linter | `ReservationService` lives under `gateway.application.accounting`, already covered by Slice 8's "provider execution does not depend on accounting" |
| Migration guardrail (reused, unchanged) | `scripts/check_migration_guardrails.py` | Generic `organization_id`-column detection caught all three new tables with zero script changes |

Of the six candidate enforcement properties evaluated (see Architecture_Evidence_Log.md), four were
already covered by prior slices' guards with **zero modification** — the strongest guard-reuse
result of any slice so far. Only the ledger-adapter independence contract (Guard C) and the
construction-guard extension were genuinely new, and the extension reused Slice 8's exact script.

**Documented limitations (not omissions):** not yet at ADR-0004's original ≤5ms/≥10k-records/s
hot-path target at full SaaS scale (correctness is proven; that specific NFR is not claimed); no
reservation-expiry reconciler (a crash between provider execution and settlement holds the
reservation until the same `correlation_id` is retried — the same deferred obligation ADR-0004
itself left to a later milestone); pricing remains `StaticPriceTable`, unchanged; project/api_key-
scoped budgets remain out of scope (no consumer).

Tests: `test_estimator.py` (4), `test_in_memory_budget_ledger.py` (13),
`test_reservation_service.py` (7), plus `test_container.py` (+2) for the wired seams (unit); 19
tests in `test_budget_ledger_postgres.py` (integration) covering reservation outcomes,
idempotency, four independent concurrency proofs against real connections (different-id race,
N-way race, same-id concurrent-duplicate reservation, concurrent duplicate settlement),
cross-tenant RLS isolation, monetary precision round-trip at maximum/minimum representable
amounts, and append-only enforcement by grant.

**Pre-commit architectural review found and fixed two genuine concurrency defects** (see
Architecture_Evidence_Log.md): `settle()`/`release()` lacked a row lock on the reservation status
check (two concurrent `settle()` calls for the same `correlation_id` could double-book spend), and
`reserve()`'s idempotency lookup raced its own atomic budget update for a brand-new
`correlation_id` (a concurrent duplicate could be wrongly denied as `EXCEEDED`). Fixed with
`SELECT ... FOR UPDATE` and a `pg_advisory_xact_lock` respectively; both proven by new concurrency
tests; full validation re-run after each fix.

**Gate 1 + Gate 2: PASS — 397 passed, 0 skipped, 96% coverage, mypy strict clean (192 files),
import-linter 23 kept / 0 broken.** Alembic at head (`0006_budget_ledger`); runtime role verified
`app_rw`, `rolsuper=False`, `rolbypassrls=False`. All Postgres-backed integration/security tests,
including the new concurrency and append-only-enforcement tests, executed against real PostgreSQL
16 + pgvector, none skipped.

