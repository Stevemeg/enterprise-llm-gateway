# Backend Implementation Guide (The Constitution)

**Phase:** 4→5 boundary — Backend governance · Draft for approval
**Last updated:** 2026-07-15

The binding rules for all backend code. It operationalizes **ADR-0001** (Clean/Hexagonal + async
FastAPI), realizes the [Architecture](Architecture.md) and [API](api/OpenAPI.yaml) against the
[Schema](Schema.sql), and is the single source of truth for structure, boundaries, and style. **Every
pull request must comply**; deviations require an ADR. No `.py` file exists yet — this document is
written **before** code, by design.

> Guiding law: **dependencies point inward. The domain knows nothing about frameworks, providers,
> HTTP, SQL, or deployment mode.** If a rule here conflicts with convenience, the rule wins.

## 1. Complete folder structure

```
backend/
├── README.md · ARCHITECTURE.md · CONTRIBUTING.md · STYLE_GUIDE.md
├── pyproject.toml            # deps + tool config (uv/ruff/mypy/pytest); Python 3.13
├── src/
│   └── gateway/
│       ├── domain/                      # Layer 0 — pure business core (no I/O, no frameworks)
│       │   ├── models/                  # entities & value objects (Tenant, Budget, RoutingDecision, Money…)
│       │   ├── services/                # pure domain services (routing rules, budget math)
│       │   ├── events.py                # domain events (names/payloads)
│       │   └── errors.py                # DomainError hierarchy (framework-free)
│       ├── application/                 # Layer 1 — use-cases & ports (orchestration; no I/O impls)
│       │   ├── ports/                   # interfaces (Protocols/ABCs): LLMProviderPort, CachePort,
│       │   │                            #   BudgetPort, EventBusPort, EmbeddingPort, AuthorizationPort,
│       │   │                            #   SecretsPort, UnitOfWork, *Repository
│       │   ├── usecases/                # one class/callable per use-case (CreateChatCompletion, CreateBudget…)
│       │   ├── dto/                     # application DTOs (not HTTP, not ORM)
│       │   └── errors.py                # ApplicationError hierarchy
│       ├── adapters/                    # Layer 2 — implement application ports (the only I/O)
│       │   ├── providers/               # openai/ anthropic/ bedrock/ azure/ generic (LLMProviderPort)
│       │   ├── persistence/             # repositories, SQLAlchemy Core, UoW, RLS session, models mapping
│       │   ├── cache/                   # redis_exact, pgvector_semantic (CachePort)
│       │   ├── embeddings/              # local_model, external_api (EmbeddingPort)
│       │   ├── eventbus/                # redis_streams, kafka (EventBusPort)
│       │   ├── secrets/                 # kms, vault, sealed (SecretsPort)
│       │   └── identity/                # oidc_jwks, jwt (auth verification)
│       ├── delivery/                    # Layer 3 — inbound entrypoints (framework-facing)
│       │   ├── http/
│       │   │   ├── routers/             # FastAPI routers per resource (mirror OpenAPI tags)
│       │   │   ├── schemas/             # Pydantic request/response models (mirror OpenAPI)
│       │   │   ├── middleware/          # pipeline (see §14)
│       │   │   ├── dependencies.py      # FastAPI DI wiring → application ports
│       │   │   └── errors.py            # map Application/DomainError → Error envelope (API_Error_Model)
│       │   ├── workers/                 # metering, audit, embeddings, analytics, alerts (EventBus consumers)
│       │   ├── scheduler/               # reconciler, budget resets, partition mgmt, health probes
│       │   └── ops/                     # health/readiness/liveness, /metrics
│       ├── config/                      # composition root & settings (the ONLY place modes/backends wire)
│       │   ├── settings.py              # typed settings (env/Secrets); profile: saas | self_hosted
│       │   ├── container.py             # DI container / composition root
│       │   └── bootstrap.py             # app + worker factories, startup validation (fail-fast)
│       ├── observability/               # OTel, Prometheus, structured logging setup
│       └── shared/                      # cross-cutting primitives ONLY (types, ids, time, result) — no business logic
├── migrations/                          # Alembic; realizes Schema.sql (Migration_Strategy.md)
├── tests/                               # unit/ integration/ e2e/ contract/ load/  (mirrors src)
└── scripts/                             # dev/ops helper scripts
```

Rationale: the four layers map 1:1 to the [C4 component](architecture/C4/03-component.md) and
[C4 code](architecture/C4/04-code.md) diagrams; `config/` is the **composition root** where — and only
where — deployment mode and backend choices are resolved (ADR-0001, NFR-D01).

## 2. Clean Architecture boundaries (the four layers)

| Layer | Package | May depend on | Must NOT import | Contains |
|-------|---------|---------------|-----------------|----------|
| **0 Domain** | `domain/` | (only `shared/` primitives + stdlib) | application, adapters, delivery, FastAPI, SQLAlchemy, redis, httpx | entities, value objects, pure domain services, domain errors/events |
| **1 Application** | `application/` | `domain/`, `shared/` | adapters, delivery, any framework/driver | use-cases, **ports** (interfaces), DTOs, UoW interface |
| **2 Adapters** | `adapters/` | `application/` (ports), `domain/`, `shared/` | delivery, other adapters' internals | port implementations (DB, providers, cache, bus, secrets, identity) |
| **3 Delivery** | `delivery/` | `application/`, `domain/` (types), `shared/` | adapters' internals (uses ports via DI) | FastAPI routers, schemas, middleware, workers, ops |
| **Composition** | `config/` | everything | — (it is the wiring point) | settings, DI container, bootstrap |

The **Dependency Rule**: arrows point inward (3→2→1→0). `config/` is the exception — it imports outward
to *assemble* the graph, and nothing imports `config/` except the entrypoints.

## 3. Dependency rules (enforced, not aspirational)
- Enforced in CI by **`import-linter`** contracts (Phase 11) encoding the table in §2; a violating import
  fails the build (NFR-M02/M05).
- **Ports over implementations:** application/delivery depend on **interfaces** in `application/ports`,
  never on a concrete adapter. Concretes are injected by `config/container.py`.
- **No cross-adapter imports:** the Redis cache adapter never imports the provider adapter, etc. Shared
  needs go through a port or `shared/`.
- **`shared/` is leaf-only:** primitives (typed ids, `Result`, clock, UUIDv7) with **zero** business
  logic and no inward/outward domain knowledge.
- **Framework isolation:** FastAPI/Pydantic live in `delivery/http`; SQLAlchemy in `adapters/persistence`;
  httpx in `adapters/providers`; redis in `adapters/cache|eventbus`. None leak inward.

## 4. Module ownership
Each top-level module maps to an owning role (see [System_Context](System_Context.md) §7) and the
subsystems in [Architecture_Implementation_Map](Architecture_Implementation_Map.md):

| Module | Owner role | Realizes |
|--------|-----------|----------|
| `domain/`, `application/` | Principal/Platform Engineer | core use-cases & rules |
| `adapters/providers` | LLMOps | ADR-0003 provider layer |
| `adapters/persistence` | Database Architect | ADR-0002 tenancy/RLS, repositories |
| `adapters/cache`, `adapters/embeddings` | LLMOps | ADR-0006/0007 |
| `adapters/eventbus`, `delivery/workers`, `delivery/scheduler` | Platform/SRE | ADR-0005 |
| `adapters/secrets`, `adapters/identity`, authz | Security Architect | ADR-0008/0011 |
| `delivery/http` | Platform Engineer | API contract (OpenAPI) |
| `observability/`, `delivery/ops` | SRE | NFR-O |
| `config/` | Principal Engineer | ADR-0001 composition, NFR-D01 |

CODEOWNERS (Phase 11) encodes this for review routing.

## 5. Service boundaries (processes)
One codebase → multiple **process roles** from one image, selected by `config/bootstrap.py` (ADR-0001/0005):

| Process | Entry | Responsibility |
|---------|-------|----------------|
| **api** | `delivery/http` (ASGI) | inference + admin HTTP/SSE (hot path) |
| **worker** | `delivery/workers` | EventBus consumers: metering, audit, embeddings, analytics, alerts |
| **scheduler** | `delivery/scheduler` | reconciler, budget resets, partition automation, health probes |

All are **stateless** (state in Postgres/Redis), horizontally scalable (NFR-S02). They share
`domain/`+`application/`; they differ only in which delivery adapter runs. Extraction into separate
deployables later requires only a new bootstrap target, not a rewrite.

## 6. Repository pattern
- One **repository interface per aggregate** in `application/ports` (e.g., `BudgetRepository`,
  `ApiKeyRepository`, `ProviderRepository`), returning **domain objects**, not ORM rows.
- Implementations live in `adapters/persistence` using **SQLAlchemy Core** (explicit SQL/statements, no
  lazy-loading surprises on the hot path) — the ORM/declarative layer is avoided in the domain (ADR-0001).
- Repositories **always operate within the tenant-scoped session** (RLS `SET LOCAL app.current_org`) — see
  [RLS_Strategy](RLS_Strategy.md); a repository never accepts a raw `organization_id` to "trust"; the
  session context is the boundary.
- Append-only aggregates (`usage_ledger`, `audit_event`) expose **append-only repositories** (no update/
  delete methods) — mirrors the DB grants (DB-DEC-06).
- Queries that don't map to an aggregate (analytics/list projections) use **read-only query services**
  (see §8 CQRS), not the write repositories.

## 7. Unit of Work pattern
- A `UnitOfWork` port (`application/ports`) wraps a **single transaction boundary** per use-case:
  ```
  async with uow:                     # opens tx, SET LOCAL app.current_org
      repo = uow.budgets              # repositories bound to this tx
      ...                             # domain mutations
      await uow.commit()              # or rollback on exception
      # domain events collected during the tx are published AFTER commit
  ```
- The UoW: (a) opens the DB transaction, (b) binds the **tenant/RLS context**, (c) exposes repositories,
  (d) collects **domain events** and hands them to the `EventBusPort` **after** commit (outbox-style),
  keeping the hot path non-blocking (ADR-0005, NFR-P06).
- **No provider/network call inside the UoW** (ADR-0004 / [Query_Performance_Guide](Query_Performance_Guide.md)
  §10): the provider call happens outside any open transaction. Reserve (Redis) and commit (async) are
  separate short units — never one long transaction around model latency.

## 8. CQRS usage (deliberately light)
- We apply a **pragmatic command/query split**, not full CQRS with separate stores:
  - **Commands** (writes/use-cases) go through `application/usecases` + repositories + UoW (domain rules,
    transactions, events).
  - **Queries** (reads: lists, usage analytics, audit browse) use **dedicated read-only query services**
    in `adapters/persistence/queries` returning DTOs/projections — they may read replicas and
    `usage_rollup` (denormalized) for performance (FR-086), bypassing the aggregate load path.
- **No event-sourcing, no separate read DB** in v1 (the `usage_ledger`/`usage_rollup` split already gives
  a read model). Introducing heavier CQRS later requires an ADR. This keeps write correctness (budgets,
  audit) strict while making reads fast.

## 9. Dependency Injection strategy
- **Composition root** = `config/container.py`. It is the **only** place concrete adapters are constructed
  and bound to ports, chosen by `settings.profile` (`saas`|`self_hosted`) and backend config (e.g.,
  `eventbus=redis_streams|kafka`, `embeddings=local|external`).
- **Constructor injection** everywhere; use-cases receive ports as constructor args. No global singletons,
  no service-locator, no importing concretes in business code.
- **FastAPI** wiring: `delivery/http/dependencies.py` exposes `Depends(...)` providers that resolve from
  the container — thin glue only. Workers/scheduler resolve from the same container via `bootstrap.py`.
- **Lifespan-scoped** resources (DB pool, Redis pool, provider clients, OTel) are created once at startup,
  **request-scoped** context (tenant, request id) is created per request.
- A lightweight DI approach (explicit container / `dependency-injector`-style or hand-rolled) — chosen in
  Phase 5; the **rule** (constructor injection + single composition root) is fixed here regardless.

## 10. Configuration system
- **Typed settings** (`config/settings.py`) via Pydantic-Settings: load from env + mounted files;
  **secrets are fetched via `SecretsPort`**, never read as plaintext env (ADR-0011, NFR-SEC03).
- **Profiles:** `deployment_mode = saas | self_hosted` gates multi-region, external telemetry, embedding
  default, etc. — resolved once, in the composition root (NFR-D01).
- **Fail-fast validation** at startup (`bootstrap.py`): required settings/secrets present, DB/Redis
  reachable, migrations at expected head — else the process refuses to start (FR-146, ADR-0009 row 16).
- **Precedence:** explicit env > mounted config file > safe defaults. No secret values in defaults or logs.
- Config is **immutable per process**; runtime-changeable behavior (provider enable/disable, flags) lives
  in the DB (`configuration`, `feature_flag`), not process config.

## 11. Exception hierarchy
Three tiers, mapped to the API error model at the edge only:

```
GatewayError (base)
├── DomainError                 # domain/errors.py — invariant violations (framework-free)
│   ├── BudgetExceededError
│   ├── ResidencyViolationError
│   ├── InvalidRoutingPolicyError
│   └── ...
├── ApplicationError            # application/errors.py — use-case failures
│   ├── AuthorizationDeniedError
│   ├── NotFoundError
│   ├── ConflictError
│   ├── ValidationError
│   └── IdempotencyConflictError
└── InfrastructureError         # adapters — I/O failures
    ├── ProviderError / ProviderUnavailableError
    ├── BudgetStoreUnavailableError
    ├── CacheUnavailableError
    └── SecretsUnavailableError
```
- Domain/application layers **raise typed exceptions**; they never build HTTP responses.
- **`delivery/http/errors.py`** is the single translator: maps each exception to the `Error` envelope
  (`type`/`code`/status) per [API_Error_Model](API_Error_Model.md), attaches `request_id`, and applies the
  **fail-open/closed** decision ([ADR-0009](adr/0009-fail-open-fail-closed-matrix.md)) — e.g.,
  `BudgetStoreUnavailableError` on a hard-limited scope → 503 fail-closed; a `CacheUnavailableError` is
  swallowed (miss) upstream, never reaching the client.
- No bare `except:`; never swallow an exception without logging + a decision; never leak internals to
  clients (FR-010).

## 12. Logging strategy
- **Structured JSON** logs (`observability/logging.py`), one event per line, correlated by
  **`request_id`** and **trace context** (FR-080/082/083). No `print`.
- **PII handling per `governance_policy`** (store/hash/drop) — prompts/responses are never logged raw
  unless policy permits (FR-118); a redaction filter enforces this centrally.
- **Levels:** `DEBUG` (dev only), `INFO` (lifecycle + request summary), `WARNING` (degradations, fail-open
  events), `ERROR` (handled failures), `CRITICAL` (startup/again-closed). Secrets/keys/tokens are **never**
  logged (a formatter denylist enforces this; CI scans for violations).
- **Context propagation:** a contextvar carries `request_id`, `organization_id` (id only), `principal` into
  every log line without threading them manually.
- Logs go to stdout (12-factor); shipping/retention is infra (NFR-O, self-host keeps in-cluster).

## 13. Middleware pipeline (HTTP, ordered)
Order matters; each is thin and single-purpose (`delivery/http/middleware/`):
1. **RequestContext** — generate/accept `X-Request-Id`, start trace span, bind logging context.
2. **SecurityHeaders** — set HSTS/nosniff/etc. ([API_Governance](API_Governance.md) §7).
3. **BodyLimits/Timeouts** — max body size, request timeout.
4. **Authentication** — resolve principal (API key or JWT); **fail closed** on failure (ADR-0009).
5. **TenantContext** — establish `organization_id`; will bind RLS session in the UoW.
6. **Authorization** — RBAC/scope check for admin routes (deny-by-default).
7. **RateLimit** — token-bucket check (429 + headers) before expensive work.
8. **Idempotency** — for mutating POSTs, short-circuit replays.
9. **Router/handler** — the endpoint (opens UoW, calls use-case).
10. **ErrorTranslation** (outermost catch) — map exceptions → `Error` envelope; ensure `X-Request-Id` on
    every response.
Observability (metrics/trace finalize) wraps the whole stack. Governance (PII/residency) is enforced
inside the **inference use-case**, not as generic middleware, because it needs request semantics.

## 14. Background worker architecture
- **Consumers** (`delivery/workers`) subscribe to `EventBusPort` consumer groups (Redis Streams default,
  ADR-0005): `metering`, `audit`, `embeddings`, `analytics`, `alerts`.
- Each consumer is **idempotent** (dedupe by `event_id`), acks on success, retries with backoff, and routes
  poison messages to a **dead-letter stream**; DLQ depth is alerted (NFR-A05/O).
- **Scheduler** (`delivery/scheduler`) runs periodic jobs: budget **reconciler** (Redis↔ledger, ADR-0004),
  period **resets**, **partition** create/detach ([Partitioning_Strategy](Partitioning_Strategy.md)),
  active **health probes**, retention **prune/archive**.
- Workers reuse the **same domain/application/adapters**; they are just a different delivery. They set
  tenant context per event (from the event's `organization_id`) and honor RLS.
- No business logic lives only in a worker — it lives in `application/usecases`, invoked by the worker.

## 15. Testing strategy (test-first)
- **Layout mirrors `src/`**; pyramid: many **unit** (domain/application with fakes for ports — no I/O),
  fewer **integration** (adapters against real Postgres+Redis via testcontainers, incl. **RLS isolation**
  and **budget concurrency** tests), **contract** (handlers vs OpenAPI schemas + SDK mock), **e2e**
  (full inference path incl. streaming/failover/governance), **load/chaos** (Phase 13).
- **Ports enable pure unit tests:** use-cases are tested with in-memory fake adapters; the domain needs no
  I/O (NFR-M04).
- **Coverage ≥90% meaningful** where practical (Quality Gates §12); the concurrency/isolation/fail-mode
  tests are mandatory gates (RISK-T03/T05, NFR-SEC07). Full plan: [API_Testing_Strategy](API_Testing_Strategy.md).
- **Test doubles** are fakes (behavioral), not brittle mocks, for ports; mocks only at true I/O edges.

## 16. Code style rules
- **Python 3.13**, fully **type-annotated**; **mypy strict** must pass (no `Any` on public signatures,
  no untyped defs). **Pydantic v2** at boundaries only. Dependencies & virtualenvs via **uv**.
- **Formatting/lint:** `ruff` (lint + import order + `ruff format`); zero warnings gate. Line length 100.
- **Async everywhere on the request path**; no blocking I/O in async handlers (blocking calls go to a
  thread/executor and are justified).
- **Naming:** `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE` consts; module names match
  the folder domain. Ports named `<Thing>Port`; adapters `<Backend><Thing>Adapter`
  (e.g., `RedisLuaBudgetAdapter`) — matches [C4 code](architecture/C4/04-code.md).
- **Functions small & pure where possible**; no hidden global state; explicit dependencies via
  constructors. Docstrings on public classes/functions; comments explain *why*, not *what*.
- **Immutability:** value objects are frozen; prefer returning new objects to mutation.
- **Errors:** raise typed exceptions (§11); never `assert` for control flow; no silent failures.
- **Imports:** absolute within `gateway.*`; enforce layer rules (§3) via import-linter; no wildcard
  imports.
- Full details + examples in [`backend/STYLE_GUIDE.md`](../backend/STYLE_GUIDE.md).

## 17. Definition of Done (per PR, Phase 5+)
Complies with layers/imports (§2/§3); has tests (§15) with green Quality Gates (coverage, ruff,
mypy, security scan); updates docs/ADR if behavior/contract changed; no secret in code/logs; touches only
its module's ownership or has the owner's review (§4). CI enforces all of it (Phase 11).

## 18. Traceability
ADR-0001 (architecture/runtime), ADR-0002/0004/0005/0008/0009/0011 (patterns realized), NFR-M01..M06,
NFR-D01, NFR-P06, NFR-SEC03. Backend docs: [`backend/ARCHITECTURE.md`](../backend/ARCHITECTURE.md),
[`backend/CONTRIBUTING.md`](../backend/CONTRIBUTING.md), [`backend/STYLE_GUIDE.md`](../backend/STYLE_GUIDE.md),
[`backend/README.md`](../backend/README.md).
