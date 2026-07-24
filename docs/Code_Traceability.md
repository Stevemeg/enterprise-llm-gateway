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
| **Phase 4 Slice 10 — Semantic-Safe Response Caching & Request Deduplication** | **Capability** | **✅ COMPLETE** | **✅ Gate 1 + Gate 2 PASS: 440 passed, 0 skipped, 96% coverage** |
| **Phase 4 Slice 11 — Reflection / Retry Layer** | **Capability** | **✅ COMPLETE** | **✅ Gate 1 + Gate 2 PASS: 485 passed, 0 skipped, 97% coverage** |
| **Phase 4 Slice 12 — Evaluation Pipeline** | **Capability** | **✅ COMPLETE** | **✅ Gate 1 + Gate 2 PASS: 520 passed, 0 skipped, 97% coverage** |
| **Phase 4 Slice 13 — Policy Engine Foundation** | **Capability** | **✅ COMPLETE** | **✅ Gate 1 + Gate 2 PASS: 546 passed, 0 skipped, 97% coverage** |
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

### Slice 10 — Semantic-Safe Response Caching & Request Deduplication — ✅ COMPLETE

Rule 5 **not triggered against Tier 1** (zero diff on `domain/`, `ports/routing.py`, `pipeline.py`,
`tools.py`, `mcp.py`, `agents.py`, `application/agents/runtime.py`, `docs/adr/0016-*.md`).
`RoutingDecision`/`RoutingExecution`/`InferenceRequest`/`ProviderResponse` are all unmodified.
Caching and request deduplication were confirmed to be different concepts (content-keyed vs.
correlation-keyed identity) before any code was written — see Architecture_Evidence_Log.md. New
**ADR-0018** adopted: PostgreSQL-backed exact-match caching plus process-local deduplication as the
current, verified mechanism, scoping — not reversing — ADR-0006's two-tier (Redis exact +
`pgvector` semantic) decision (no Redis client, embedding pipeline, or event-bus consumer exists
anywhere in this codebase; building either now would be speculative infrastructure with no active
consumer). **No new migration required** — unlike Slice 9's finding for the budget/reservation
tables, the pre-existing `semantic_cache_entry` table (`0001_initial.sql`) already fits exact-match
caching exactly, already RLS-protected, already granted to `app_rw`.

| Component | Module | Role |
|---|---|---|
| Port (capability-owned, new) | `application/ports/cache.py` | `ResponseCachePort`, `CacheKey`, `CachedResponse`, `CacheUnavailableError` — fails **open**, not closed (contrast `BudgetLedgerPort`) |
| Cache-key canonicalization (new) | `application/execution/cache_key.py` | `compute_cache_key()` — deterministic SHA-256 over `(organization_id, provider, model, canonical payload)`; deliberately excludes `correlation_id` |
| Deduplicator (new, concrete, not a port) | `application/execution/deduplicator.py` | `RequestDeduplicator`; process-local `asyncio.Task`-based single-flight coalescing keyed on `(organization_id, correlation_id)` |
| Coordinator (new) | `application/execution/inference_coordinator.py` | `InferenceCoordinator`; the first real, tested caller of the full cache → dedup → reserve → execute → settle/release sequence `ReservationService`/`ProviderExecutor` had left to "a future delivery-layer handler" |
| Shared crypto primitive (extended) | `shared/secrets.py` | `sha256_bytes()` added alongside the existing `sha256_hex()` — routes the new cache-key digest through the project's single audited crypto boundary |
| Validation implementation (Rule 4, real) | `adapters/cache/sql_response_cache.py` | `SqlResponseCache`; TTL-expiring, tenant-bound via `AsyncUnitOfWork`, against real PostgreSQL |
| Validation implementation (Rule 4, fast double) | `adapters/cache/in_memory_response_cache.py` | `InMemoryResponseCache`; process-local, documented as NOT proving RLS |
| SQLAlchemy Core table (new, reused table) | `adapters/persistence/cache_tables.py` | Points at the pre-existing `semantic_cache_entry`; only the columns this slice uses are declared |
| Composition root | `config/container.py` | Constructs `cache_port` (`SqlResponseCache` if `rls_enabled` else `InMemoryResponseCache`), `deduplicator`, `inference_coordinator` (new Guard 1) |
| Guard 1 (new script) | `scripts/check_execution_construction.py` | Construction of the two cache adapters, `RequestDeduplicator`, `InferenceCoordinator` confined to the composition root — classified NEW (new capability boundary), not an extension of Slice 8/9's accounting-construction script |
| Guard (new) | `pyproject.toml` import-linter | `SqlResponseCache`/`InMemoryResponseCache` mutually independent |
| Guard (new) | `pyproject.toml` import-linter | `gateway.adapters.cache` forbidden from importing accounting, the ledger adapters, or authorization |
| Guard (new) | `pyproject.toml` import-linter | `gateway.application.execution` forbidden from importing authorization |
| `RoutingDecision` construction (reused, unchanged) | `scripts/check_routing_decision_construction.py` | Whole-repo AST scan with no per-slice allowlist to update — proven to catch a planted violation in `inference_coordinator.py` with zero script changes |
| `AgentRuntime` sole-caller (reused, unchanged) | `scripts/check_routing_engine.py` Guard L | Proven the same way |
| Application framework-free (reused, general) | `pyproject.toml` import-linter | Pre-existing blanket contract, proven to catch `import sqlalchemy` planted in `deduplicator.py` |

A `DeduplicationPort` protocol was considered and rejected as premature: exactly one correct
implementation exists (process-local coalescing), and a `Protocol` with no second implementation to
prove substitutability would be exactly the speculative abstraction Rule 4/GP-1 warn against —
`RequestDeduplicator` is a concrete class, mirroring `ReservationService`/`ProviderExecutor`.

**Documented limitations (not omissions):** exact-match only, no near-duplicate/semantic-similarity
caching (deferred to ADR-0006's Tier 2, pending evidence); no cross-process deduplication guarantee
(`RequestDeduplicator` is process-local — Slice 9's ledger idempotency still prevents
double-*charging* across processes, but not a double provider *call*); no "cache stampede"
protection across different `correlation_id`s with identical content (deduplication is
correlation-keyed, not content-keyed, by design); no explicit purge/invalidation beyond TTL expiry;
`hit_count`/`prompt_fingerprint` on the reused table are not populated.

Tests: `test_cache_key.py` (9), `test_in_memory_response_cache.py` (7), `test_deduplicator.py` (7),
`test_inference_coordinator.py` (12), plus `test_container.py` (+2) for the wired seams (unit); 8
tests in `test_response_cache_postgres.py` (integration) covering hit/miss, TTL expiry, a malformed
stored entry failing open, cross-tenant RLS isolation (including a deliberately colliding raw key),
and a connection outage failing open with `CacheUnavailableError`.

**Gate 1 + Gate 2: PASS — 440 passed, 0 skipped, 96% coverage, mypy strict clean (206 files),
import-linter 26 kept / 0 broken.** Alembic head unchanged at `0006_budget_ledger` (no migration
this slice); runtime role verified `app_rw`, `rolsuper=False`, `rolbypassrls=False`. All
Postgres-backed integration/security tests, including the new cache RLS/TTL/outage tests, executed
against real PostgreSQL 16 + pgvector, none skipped.

### Slice 11 — Reflection / Retry Layer — ✅ COMPLETE

Rule 5 **not triggered against Tier 1** (zero diff on `domain/`, `ports/routing.py`, `pipeline.py`,
`tools.py`, `mcp.py`, `agents.py`, `application/agents/runtime.py`, `application/routing/engine.py`,
`docs/adr/0016-*.md`). **Triggered and satisfied** against the Slice-7/8 capability-owned
`ProviderResponse`: an additive, optional `error_category: ProviderErrorCategory | None = None`,
consumed by the new retry classifier — every prior construction remains valid unchanged, exactly
the shape of Slice 8's `usage` addition to the same port. **No new ADR** — this slice contradicts no
existing Accepted decision, so a companion ADR (as Slices 9 and 10 needed) would be ceremony rather
than governance. **No migration.**

Analysing retry semantics also surfaced a **genuine pre-existing defect in Slice 9's ledger**,
reachable from Slice 10's coordinator with no reflection involved: `reserve()`'s idempotent-replay
branch matched any existing row regardless of `status`, so `reserve → release → reserve` returned
`RESERVED` while holding nothing (verified empirically against real Postgres: `reserved=0E-8`, and
the full limit still admissible to a competing request). Fixed in both ledger adapters and covered
by regression tests. See [Architecture_Evidence_Log.md](Architecture_Evidence_Log.md).

| Component | Module | Role |
|---|---|---|
| Port (widened, Rule 5) | `application/ports/providers.py` | `ProviderErrorCategory` (TIMEOUT/RATE_LIMITED/SERVER_ERROR/INVALID_REQUEST/AUTHENTICATION); `ProviderResponse.error_category`. No `UNKNOWN` member — "not classified" is already `None` |
| Time abstraction (extended) | `shared/clock.py` | `Sleeper` protocol + `AsyncioSleeper`; separate from `Clock` because reading time and elapsing it are different capabilities |
| Retry policy + classifier (new) | `application/reflection/retry_policy.py` | `RetryPolicy` (typed bounds, validates `max_attempts >= 1`, exponential backoff, no jitter), `RetryVerdict`, `classify()` — fail-closed: only positively-transient outcomes retry |
| Reflection orchestrator (new) | `application/reflection/reflective_executor.py` | `ReflectiveExecutor`, `AttemptRecord`, `ReflectionResult`; bounded loop over `InferenceCoordinator`, its **only** collaborator |
| Test double (extended) | `adapters/providers/fake_client.py` | Per-call `sequence` — a provider-keyed dict answers every call identically and cannot express "fails twice, then succeeds" |
| Ledger defect fix | `adapters/ledger/{sql,in_memory}_budget_ledger.py` | A `released` reservation is now genuinely re-held (new `_hold` helper), not replayed as a phantom hold |
| Composition root | `config/container.py` | Constructs `sleeper`, `retry_policy`, `reflective_executor` (Guard 1, extended) |
| Guard (new) | `pyproject.toml` import-linter | `gateway.application.reflection` forbidden from `application.providers`, `application.accounting`, `ports.ledger`, `application.routing.engine` — with `allow_indirect_imports = true`, because reflection → coordinator → those is the *intended* path and only a direct reach-around is a violation |
| Guard 1 (reused, extended) | `scripts/check_execution_construction.py` | `TARGETS`/`IMPLEMENTATIONS` extended with `ReflectiveExecutor`/`RetryPolicy` — same script, same pattern as Slice 9's extension of the accounting guard |
| `RoutingDecision` construction (reused, unchanged) | `scripts/check_routing_decision_construction.py` | Proven to catch a planted construction in `reflective_executor.py` with zero script changes |
| Guard L (reused, unchanged) | `scripts/check_routing_engine.py` | Proven the same way against an `AgentRuntime` reference |
| Application framework-free (reused, general) | `pyproject.toml` import-linter | Pre-existing blanket contract, proven to catch an adapter import planted in `reflective_executor.py` |

**Responsibility boundaries held.** Reflection decides *whether another attempt is warranted* and
nothing else. It does not reroute (provider selection stays with `ProviderAgent`/`AgentRuntime` —
building rerouting would require a second `RoutingDecision` for one logical request, i.e. two
explanations, so it was deliberately not built), does not construct or mutate `RoutingDecision`
(carried through frozen and asserted identical by `is`), does not call `AgentRuntime`, does not
invoke provider adapters, does not author cost, and cannot bypass `ProviderExecutor` or the budget
gate — every attempt goes back through `InferenceCoordinator`, structurally enforced by the new
contract rather than by review.

**Attempt identity.** Each attempt executes under `<correlation_id>#<attempt>` so it reserves,
settles or releases independently (Slice 9 keys on `(organization_id, correlation_id)`; reusing the
bare id would have made attempt 2's `settle` a swallowed duplicate — a provider call the tenant was
never charged for). This is safe against both Slice-10 identities *because* Slice 10 kept them
separate: cache identity ignores `correlation_id` entirely, and deduplication identity uses it, so
N concurrent duplicates derive the same attempt id and coalesce at every attempt — 3 duplicate
callers × 3 attempts is 3 provider calls, not 9.

**Documented limitations (not omissions):** no rerouting; no cross-process retry coordination
(process-local dedup, inherited from Slice 10); a `committed` reservation still replays as
`RESERVED` (a caller defect whose exposure is an under-charge, not an overspend); reflection is
constructed and tested but not yet wired into a request path (no inference endpoint exists yet);
one deployment-wide `RetryPolicy`, no per-tenant variant (Rule 5 — no consumer).

Tests: `test_retry_policy.py` (16), `test_reflective_executor.py` (20), `test_clock.py` (4), plus
`test_container.py` (+2) for the wired seams and 3 ledger regression tests (2 Postgres, 1 in-memory).
No test sleeps in real wall-clock time: the sleeper is injected and records the delays it was asked
for, so backoff is asserted exactly (`[100ms, 200ms, 400ms]`) rather than approximately.

**Gate 1 + Gate 2: PASS — 485 passed, 0 skipped, 97% coverage, mypy strict clean (212 files),
import-linter 27 kept / 0 broken.** Alembic head unchanged at `0006_budget_ledger` (no migration
this slice); runtime role verified `app_rw`, `rolsuper=False`, `rolbypassrls=False`. All
Postgres-backed integration/security tests, including the new ledger regression tests, executed
against real PostgreSQL 16 + pgvector, none skipped.

### Slice 12 — Evaluation Pipeline — ✅ COMPLETE

Rule 5 **not triggered** — against Tier 1 *or* any capability-owned port. Unlike Slice 11 (which
had to add `ProviderErrorCategory`), evaluation needed **no new field anywhere**: it reads
`ExecutionOutcome` and `ProviderResponse.ok/content/usage` exactly as they already exist. Zero diff
on `domain/`, all Tier-1 ports, `agents/`, `routing/`, ADR-0016. **No migration, no persistence** —
no consumer needs evaluation history, so none was built (GP-1).

**Evaluation is Tier-2 as ADR-0016 predicted, but deliberately *not* by implementing
`PipelineStage`.** It is post-hoc, needing the finished result; a stage's `after_response` would
have to smuggle a rich typed object through the opaque `dict[str, Any]` attributes bag (Rule 3
violation, and strictly weaker than the typed alternative), and no pipeline runner exists to
execute stages anyway (Rule 4). The stage seam is untouched — Slice 13 is the capability that
genuinely consumes it.

| Component | Module | Role |
|---|---|---|
| Port (capability-owned, new) | `application/ports/evaluation.py` | `Evaluator`, `EvaluationInput`, `EvaluationResult`, `EvaluationOutcome` (PASSED/FAILED/ERROR/NOT_APPLICABLE) |
| Evaluator 1 (new) | `application/evaluation/response_completeness.py` | A response reported `ok` must carry content — `content` is `Any` with a `None` default, so an adapter can report success while delivering nothing, which Slice 10 would then cache and Slice 9 settle money against |
| Evaluator 2 (new) | `application/evaluation/usage_consistency.py` | Executed successes must report usage (else settlement is impossible); cache hits must not (nothing was spent). Observes an existing invariant, in both directions, that nothing else checks |
| Runner (new) | `application/evaluation/runner.py` | `EvaluationRunner`, `EvaluationReport`; declared-order execution, per-evaluator error isolation |
| Composition root | `config/container.py` | Constructs `evaluators` + `evaluation_runner` (Guard 1, extended) |
| Guard (new) | `pyproject.toml` import-linter | `gateway.application.evaluation` forbidden from providers, accounting, ports.ledger, routing.engine, reflection, authorization (`allow_indirect_imports` — only a direct reach-around is a violation) |
| Guard (new) | `pyproject.toml` import-linter | Evaluator implementations mutually independent |
| Guard 1 (reused, extended) | `scripts/check_execution_construction.py` | `EvaluationRunner` added — it owns *which* evaluators run; the two pure evaluators are deliberately NOT confined (NOT APPLICABLE: stateless, no configuration authority) |
| `RoutingDecision` / Guard L (reused, unchanged) | `check_routing_decision_construction.py`, `check_routing_engine.py` | Both proven against `evaluation/runner.py` |

**Result vocabulary is four states because three would lie.** "The evaluator failed" and "the
evaluated thing failed" are separate operational facts (`evaluation_degraded` vs `target_failed`);
`NOT_APPLICABLE` exists because both evaluators genuinely need to say "outside what I judge" — a
budget denial delivered no response to assess, and reporting that as PASSED would inflate quality
metrics with requests nobody evaluated.

**Documented limitations:** not persisted; not wired into a request path (no inference endpoint
exists); synchronous only, no background dispatch; no LLM judge (external dependency and
non-determinism to prove a seam two pure functions already prove); the `EXECUTED + usage=None`
branch is defence in depth, unreachable through the coordinator because `CostAccountant` rejects
such a response at settlement first — discovered by a failing test and recorded rather than hidden.

Tests: `test_evaluators.py` (24), `test_evaluation_runner.py` (14), plus `test_container.py` (+3).

**Gate 1 + Gate 2 at Slice-12 completion: PASS — 520 passed, 0 skipped, 97% coverage, mypy strict
clean (219 files), import-linter 29 kept / 0 broken.** All new modules at 100% line coverage.

### Slice 13 — Policy Engine Foundation — ✅ COMPLETE

Rule 5 **not triggered**. `PolicyStage` implements the Tier-1 `PipelineStage` protocol
**byte-for-byte unchanged**, consumes only pre-existing `StageContext` fields
(`organization_id`, `correlation_id`, `attributes["request"]`), and expresses every outcome in the
existing `StageAction` vocabulary. **This is the cleanest confirmation of ADR-0016's Tier-2
demotion of Policy Engine.** No migration. **No new ADR** — nothing here contradicts an Accepted
decision.

**Three-way boundary, settled before code:**

| Component | Question | Owns |
|---|---|---|
| RBAC (`AuthorizationStage` + `PermissionResolver`) | *May this **principal** perform this action?* | identity → permissions → declared requirement |
| `PolicyAgent` (inside `AgentRuntime`) | *Which **providers/regions** is this eligible for?* | routing-time eligibility |
| **Policy Engine** (this slice) | *Is this **request** permitted at all?* | identity- and provider-independent admissibility |

| Component | Module | Role |
|---|---|---|
| Port (capability-owned, new) | `application/ports/policy.py` | `PolicyEnginePort`, `PolicyQuery`, `PolicyVerdict`, `PolicyEffect` (ALLOW/DENY only), `PolicyEngineUnavailableError`, `REQUEST_PAYLOAD_KEY` |
| Engine (new) | `adapters/policy/local_policy_engine.py` | `LocalPolicyEngine` — deterministic max-request-size policy over a canonical JSON encoding |
| Stage (new) | `adapters/pipeline/policy_stage.py` | `PolicyStage` — implements `PipelineStage` unchanged, beside `AuthorizationStage` |
| Composition root | `config/container.py` | Constructs `policy_engine` + `policy_stage` |
| Guard (new) | `pyproject.toml` import-linter | Policy consumers depend on `PolicyEnginePort` only (Guard G's shape, applied to policy) |
| Guard (new) | `pyproject.toml` import-linter | `gateway.adapters.policy` forbidden from routing, agents, providers, accounting, ports.ledger, reflection, evaluation, adapters.authorization |
| Guard G (reused, unchanged) | `pyproject.toml` | Already forbids `adapters.pipeline` → `adapters.authorization`; proven to catch a violation planted in `policy_stage.py`, so no policy-specific duplicate was added |
| `RoutingDecision` / Guard L (reused, unchanged) | AST scans | Proven against `policy_stage.py` and `local_policy_engine.py` |

**First policy chosen from data that actually exists.** Model-capability, environment and
data-classification policies were all rejected: no org policy store, no capability catalog and no
data classification exist, and inventing one to justify the Policy Engine would be exactly the
speculative infrastructure GP-1 forbids. Maximum request size survives because the payload already
flows through `StageContext.attributes["request"]` (the convention `AgentRoutingStage` established
in Slice 6, now named as a declared constant), and Slice 9's estimator already derives reservations
from payload length — so an unbounded payload is simultaneously a cost problem and an abuse vector,
rejected before both the budget reservation and the provider call.

**Fail-closed, proven four ways** (not merely documented): engine outage, engine defect (any escaped
exception), a verdict that is not a `PolicyVerdict` (a remote engine can deserialize into something
unexpected — "unexpected" must not become "allowed"), and a missing tenant. `PolicyEffect` has no
`UNAVAILABLE` member deliberately: an engine that could not decide has not produced an effect, and
modelling "no answer" as a kind of answer is what lets an outage quietly become a verdict.

**Denial and outage both block but stay distinguishable in the audit trail** (`policy_denied` +
rule + measurements vs `policy_unavailable`) while the **caller sees an identical generic reason** —
naming the rule or threshold would be a reconnaissance aid, the same reasoning
`AuthorizationStage` applies to permission names.

**OPA: DEFERRED, explicitly.** No OPA server, no Rego bundle, no distribution mechanism, no
deployment configuration, no consumer needing externally-authored policy. An adapter built now
would be a fake integration whose parity tests compare a stub against itself — the same
evidence-first posture ADR-0017 took toward Redis Lua and ADR-0018 toward the pgvector tier. When a
real consumer exists it implements `PolicyEnginePort` beside `LocalPolicyEngine` and **the stage
does not change**.

**Documented limitations:** one policy, one engine (no rule composition, DSL, admin API or policy
database — none has a consumer); `PolicyStage` is composed and tested but **not wired into a
request path**, because no pipeline runner exists to execute stages around an inference — like
`AuthorizationStage` before it, this is the largest outstanding debt across Slices 5–13; no policy
caching (no performance requirement, and invalidation is not free); policy does not consult
evaluation results (no consumer, and coupling would collapse two deliberately independent
capabilities).

Tests: `test_policy_engine.py` (26), plus `test_container.py` (+3).

**Gate 1 + Gate 2 (combined, both slices present): PASS — 546 passed, 0 skipped, 97% coverage,
mypy strict clean (224 files), import-linter 31 kept / 0 broken.** Alembic head unchanged at
`0006_budget_ledger` (no migration in either slice); runtime role verified `app_rw`,
`rolsuper=False`, `rolbypassrls=False`. All Postgres-backed integration/security tests executed
against real PostgreSQL 16 + pgvector, none skipped.

### Slice 14 — Request Admission Pipeline — ✅ COMPLETE

Rule 5 **not triggered** — against Tier 1 *or* any capability-owned port. Zero diff on `domain/`,
`ports/pipeline.py`, all other Tier-1 ports, `agents/`, ADR-0016. **No migration, no persistence** —
admission decides and stores nothing.

**Foundation, and the one milestone where "no ADR" is correct rather than suspect.** ADR-0016
invariant 5 has always specified CI enforcement of "stage **registration + ordering**"; the protocol
shipped in Slice 1 and three stages implement it, but **nothing had ever executed one**. This slice
supplies the missing artifact, so no seam is born and no ADR is written. Before it,
`AuthorizationStage` (Slice 5) was **not constructed anywhere in the codebase at all**, and
`PolicyStage` (Slice 13) was constructed but never run.

*(Note: `Phase4_Master_Execution_Plan.md` and `AIOS_Architecture.md` do not exist in this repo —
ADR-0016 anticipates the former but it was never committed. The roadmap was reconciled from
ADR-0016's tier tables plus the evidence log; see the Slice-14 evidence record.)*

| Component | Module | Role |
|---|---|---|
| Runner (new) | `application/pipeline/runner.py` | `RequestPipeline`, `AdmissionOutcome`, `StageRecord`, `GENERIC_BLOCK_REASON` — registration, ordering, first-block-wins, fail-closed normalisation |
| Composition root | `config/container.py` | Constructs `permission_resolver`, `authorization_stage`, `request_pipeline` (authorization → policy → agent_routing) |
| Guard (new) | `scripts/check_pipeline_construction.py` | Only the composition root may assemble the admission chain — the component that decides *which controls run at all* |
| Guard (new) | `pyproject.toml` import-linter | `gateway.application.pipeline` forbidden from authorization, ports.policy, routing, agents, providers, execution, accounting, ports.ledger, reflection, evaluation. **No** `allow_indirect_imports`: this package has no sanctioned collaborator, so any path is a violation |
| Guard I (reused, first real subject) | `scripts/check_resolver_construction.py` | Never vacuous, but **unexercised** until now — no resolver was constructed anywhere in `src/gateway`. Re-proven |
| `RoutingDecision` / Guard L (reused, unchanged) | AST scans | Both proven against `application/pipeline/runner.py` |

**Fail closed in four distinct ways**, each tested: a BLOCK verdict; a stage that raises; a stage
returning something that is not a `StageResult`; and a stage that blocks with no reason —
`StageResult` documents that invariant but has no `__post_init__` enforcing it, a gap nothing could
observe until a runner existed. Fixed **in the consumer, not the Tier-1 type**, as a deliberate
Rule 5 outcome.

**Ordering derived, not assumed.** Routing runs last because it is the only admission stage with a
real downstream effect (it invokes the engine, which runs the five-agent chain); authorization and
policy are pure decisions. Policy-before-authorization was considered and rejected: it would
evaluate a deployment's limits for a caller who may not act, and a policy denial discloses that a
threshold exists.

**Stages cannot communicate through the context** — each receives its own copy of
`StageContext.attributes`, so neither a stage nor a caller crafting an attribute shaped like a
stage's annotation can influence a control that runs later.

**Documented limitations:** `after_response`/`on_error` still executed by nothing (no consumer in
this slice); the default composed pipeline **denies every request** (`NullPermissionResolver` grants
nothing, no endpoint declares a requirement) — the fail-closed direction, asserted rather than
assumed; no HTTP endpoint.

Tests: `test_request_pipeline.py` (32), plus `test_container.py` (+5).

**Gate 1 + Gate 2 at Slice-14 completion: PASS — 583 passed, 0 skipped, 97% coverage, mypy strict
clean (227 files), import-linter 32 kept / 0 broken.** `runner.py` at 100% line coverage.

### Slice 15 — Served Inference Path — ✅ COMPLETE

Rule 5 **not triggered against Tier 1** (zero diff on `domain/`, `ports/pipeline.py`, all other
Tier-1 ports, `agents/`, ADR-0016). Rule 5 **triggered and satisfied on a capability-owned port**:
`ROUTING_EXECUTION_KEY` moved into `application/ports/routing.py`, first consumer
`application/serving/inference_service.py`. Recorded in the evidence log, **not** a new ADR — same
shape as `ProviderUsage` (Slice 8) and `ProviderErrorCategory` (Slice 11). No migration.

**Capability milestone: it composes and owns nothing.**

    admit (authorization → policy → routing)   Slice 14
      → reflect (bounded retry)                Slice 11
        → coordinate (cache → reserve → execute → settle/release)   Slices 9, 10
      → evaluate the final result, once        Slice 12

| Component | Module | Role |
|---|---|---|
| Service (new) | `application/serving/inference_service.py` | `InferenceService`, `ServedInference`, `RoutingTransportError` — holds the order; contributes no judgement |
| Port constant (Rule 5) | `application/ports/routing.py` | `ROUTING_EXECUTION_KEY`, beside the `RoutingExecution` it names |
| Transport fix | `adapters/pipeline/routing_stage.py` | Now annotates the whole `RoutingExecution`, not just `.decision` |
| Composition root | `config/container.py` | Constructs `inference_service` from the *same* pipeline, executor and evaluator chain it wired |
| Guard (reused-extended) | `scripts/check_pipeline_construction.py` | `InferenceService` added; per-file exemptions replaced with per-class ones after the extension was found to have weakened the guard |
| Guard (new) | `pyproject.toml` import-linter | `gateway.application.serving` forbidden from routing.engine, agents, providers, accounting, ports.ledger, execution, ports.authorization (`allow_indirect_imports` — reflection is the sanctioned path) |
| `RoutingDecision` / Guard L (reused, unchanged) | AST scans | Proven against `serving/inference_service.py` |

**A real defect in Slice 6's transport, exposed by the first end-to-end integration.**
`AgentRoutingStage` published `execution.decision` and dropped `execution.provider` — yet
`RoutingExecution.routed` means "SELECTED *and* a provider was resolved", so the annotation could
report a chosen provider while carrying nothing able to call it. Invisible for nine slices because
nothing executed the pipeline. Fixed at the smallest correct boundary: transport the whole object.

**A guard extension that silently weakened the guard it extended.** Adding `InferenceService` also
added its file to a **per-file** exemption list, letting that file construct a `RequestPipeline`
unnoticed. Caught by *re-proving the Slice-14 target after the extension* (exit 0 where exit 1 was
required); fixed by exempting each defining module for its own class only. The same flat-list
weakness exists in four earlier construction guards, none currently exposed — recorded as debt.

**A refusal is not dressed as a provider failure.** `reflection`/`evaluation` are `None` for a
refused request rather than a synthesized `ProviderResponse(ok=False)`, so "denied at admission",
"routed nowhere", "denied by budget" and "the provider failed" stay four distinguishable facts. For
the same reason a refusal is **not evaluated**: emitting `NOT_APPLICABLE` verdicts for rejected
traffic would make every quality metric a function of how much traffic was rejected.

**Documented limitations:** still no HTTP endpoint (deliberately — an endpoint pulls in
request/response schemas, the API error model and streaming, none of which this slice's evidence
speaks to); the default deployment still denies everything; **`PipelineStage.after_response` and
`on_error` remain unexecuted** — Slice 15 turned out *not* to be their first consumer, because
pushing a typed `ReflectionResult` through the opaque `attributes` bag is the same Rule 3 violation
Slice 12 rejected.

Tests: `test_inference_service.py` (20), `test_agent_routing_stage.py` (+1), plus
`test_container.py` (+3).

**Gate 1 + Gate 2 (combined, both slices present): PASS — 606 passed, 0 skipped, 97% coverage, mypy
strict clean (230 files), import-linter 33 kept / 0 broken.** Alembic head unchanged at
`0006_budget_ledger` (no migration in either slice); runtime role verified `app_rw`,
`rolsuper=False`, `rolbypassrls=False`. All Postgres-backed integration/security tests executed
against real PostgreSQL 16 + pgvector, none skipped.

### Slice 16 — Production Observability — ✅ COMPLETE

Rule 5 **not triggered** — against Tier 1 *or* any capability-owned port. Zero diff on `domain/`,
all Tier-1 ports, `agents/`, ADR-0016. **No migration.** **No new ADR** — and that is a determination,
not an omission.

**Reclassified Foundation → Capability.** ADR-0016 defines Foundation as *creating an extension
point*; this slice creates none (no port, no substitutable implementation, no seam), and Rule 1's
admission test fails because observability was added with **zero interface changes**. Everything a
telemetry ADR would decide — mechanism, exposition route, layer boundary, and the cardinality policy
itself — was already Accepted and already written in `observability/metrics.py`. This slice extends
an established mechanism and converts its **written** policy into **enforced** policy.

| Component | Module | Role |
|---|---|---|
| Vocabulary + recorders (extended) | `observability/metrics.py` | 11 request-path metric families; `record_*` functions owning runtime bounding, failure isolation and dependency direction |
| Port (relocated) | `application/ports/execution.py` | `ExecutionOutcome` — moved out of a concrete orchestrator (see the finding below) |
| Instrumentation (owner-local) | `pipeline/runner.py`, `serving/inference_service.py`, `execution/inference_coordinator.py`, `providers/provider_executor.py`, `reflection/reflective_executor.py`, `evaluation/runner.py`, `routing/engine.py`, `accounting/reservation_service.py` | each records only the facts it owns |
| Guard (new) | `scripts/check_metric_cardinality.py` | label names ⊆ allowlist; no direct `.labels()` on a request-path metric; no forbidden identifier into a `record_*` call |

**A genuine pre-existing defect, exposed by the first instrumentation.** Adding metrics to
`InferenceCoordinator` broke *"ports declare contracts only"* via
`ports.evaluation → execution.inference_coordinator → observability.metrics → prometheus_client`.
The cause was placement, not instrumentation: `ExecutionOutcome` lived **inside a concrete
orchestrator**, making a **port** import an orchestrator to name a vocabulary — the only outcome
enum in the codebase placed that way (`ReservationOutcome`, `ProviderErrorCategory`,
`EvaluationOutcome`, `StageAction` all live in ports; `RoutingOutcome` in domain). Fixed by
relocating the enum to `ports/execution.py` and repointing 10 importers. An `ignore_imports` entry
was rejected: it would have weakened a correct contract to accommodate a misplaced type.

**Cardinality is bounded at runtime, not by convention.** A value outside its allowlist becomes
`"unknown"` rather than minting a new series — the property that holds under a defect, which no
static guard can provide. `unclassified` (a real state: `error_category is None`) is kept distinct
from `unknown` (a value outside the vocabulary).

**Observability is not a correctness dependency.** Recording is failure-isolated, proven both at the
recorder and end-to-end with a deliberately exploding metric returning an identical served result.

**Documented limits, stated rather than implied:** the forbidden-identifier check is name-based and
**partially heuristic** (it cannot see through an alias); `stage`, `evaluator` and `provider` are
**configuration-bounded, not enum-bounded** (none request-supplied — pinned by a test that sends an
attacker-chosen provider in the payload); `model` is deliberately not a label (no controlled
vocabulary, cardinality unprovable); no tracing, dashboards, alert rules or SLOs.

Tests: `test_observability_metrics.py` (29), plus `test_app.py` (+1). Prometheus isolation by
**delta** via the public `REGISTRY.get_sample_value`, not registry resets.

**Gate 1 + Gate 2 at Slice-16 completion: PASS — 636 passed, 0 skipped, 97% coverage, mypy strict
clean (232 files), import-linter 33 kept / 0 broken.** All 606 pre-existing tests pass unmodified,
which is the evidence that this slice changed no business outcome.

### Slice 17 — HTTP Inference Endpoint + Authentication Wiring — ✅ COMPLETE

Rule 5 **not triggered** — against Tier 1 *or* any capability-owned port. `StageContext` already
carried `correlation_id`, `organization_id`, `principal_id` and `attributes`; **no HTTP concern
entered any application type**. Zero diff on `domain/`, all Tier-1 ports, `agents/`, ADR-0016. No
migration. No new ADR.

| Component | Module | Role |
|---|---|---|
| Route (new) | `delivery/http/api/inference.py` | `POST /v1/inference` — translates, delegates to `InferenceService`, maps to `API_Error_Model.md` |
| Authenticator (new) | `adapters/security/token_authenticator.py` | `BearerTokenAuthenticator` over the existing `AccessTokenVerifier` |
| App factory (modified) | `delivery/http/app.py` | `AuthenticationMiddleware` finally added to the chain, with pinned ordering |
| Composition root | `config/container.py`, `config/bootstrap.py` | builds the authenticator; passes it, the audit sink and the inference service to the app |
| Guard (reused-extended) | `tests/security/test_route_auth_coverage.py` | now includes the inference router, probes POST when GET is 405, and is configured so only authentication can refuse |
| Guard (new) | `pyproject.toml` import-linter | `gateway.delivery` forbidden from routing, agents, providers, accounting, ports.ledger, execution, reflection, evaluation, pipeline (`allow_indirect_imports`) |

**A control that existed, was tested, and had never executed.** `AuthenticationMiddleware` shipped
in the authentication milestone; `build_http_app` never added it and did not even accept an
authenticator. Nothing was exposed (every prior route is public by design), but this is the **same
class of debt Slice 14 eliminated for pipeline stages**, recurring one layer out. Both halves were
individually green; nothing asserted they were connected.

**The route-auth guard was vacuous three ways, all found by trying to make it fail:** its app did
not include the route; it only issued `GET` (a POST-only route answers 405, and 405 is not 200); and
with a denying resolver it would have returned 403 either way. Fixed by including the router,
probing POST, and wiring a permissive service so **authentication is the only control that can
refuse**. The planted violation had to be realistic too — deleting the check raises `AttributeError`
(500, not a bypass), so the proof models a fallback to a fabricated identity.

**Middleware ordering is pinned, not commented.** Starlette's `add_middleware` inserts at the front,
so `RequestContextMiddleware` is added *last* to be outermost and establish `request_id` before
authentication stamps it into 401 bodies and audit events. Reversing them degrades the audit trail
without raising — hence a test.

**Fail-closed default kept.** The production endpoint still denies every request
(`NullPermissionResolver`), and **no dev-permissive setting was added** because none was needed:
tests inject collaborators through `build_http_app` exactly as the pre-existing app tests do.
Durable RBAC storage remains **Slice 18**.

**Documented limitations:** JWT credentials only (`CompositeAuthenticator` needs a request-scoped
`ApiKeyRepository` — Slice 18); one deliberately minimal endpoint (no streaming, OpenAI
compatibility, tool-calling, webhooks, pagination, SDKs or rate limiting);
`PipelineStage.after_response`/`on_error` still unexecuted.

Tests: `test_inference_endpoint.py` (23), plus `test_route_auth_coverage.py` (extended).

**Gate 1 + Gate 2 (combined, both slices present): PASS — 659 passed, 0 skipped, 97% coverage, mypy
strict clean (236 files), import-linter 34 kept / 0 broken.** Alembic head unchanged at
`0006_budget_ledger`; runtime role verified `app_rw`, `rolsuper=False`, `rolbypassrls=False`.
