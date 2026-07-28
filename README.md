<div align="center">

# Enterprise LLM Gateway & Cost Router

**A multi-tenant control plane for LLM inference** — provider routing, hard budget
enforcement, tenant isolation, resilience and observability, built on a
ports-and-adapters architecture whose boundaries are enforced by the build rather
than by convention.

[![CI](https://github.com/Stevemeg/enterprise-llm-gateway/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Stevemeg/enterprise-llm-gateway/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.13-3776AB)](backend/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688)](backend/src/gateway/delivery/http/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-RLS%20enforced-336791)](backend/migrations/)
[![Redis](https://img.shields.io/badge/Redis-shared%20rate%20limiting-DC382D)](backend/src/gateway/adapters/ratelimit/)
[![Tests](https://img.shields.io/badge/tests-989%20passing%20%C2%B7%200%20skipped-brightgreen)](#validation--engineering-quality)
[![Coverage](https://img.shields.io/badge/coverage-98%25-brightgreen)](#validation--engineering-quality)
[![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)](backend/pyproject.toml)
[![Architecture](https://img.shields.io/badge/architecture-47%20enforced%20contracts-blue)](backend/pyproject.toml)

[Architecture](#architecture) ·
[Request Lifecycle](#request-lifecycle) ·
[Quick Start](#quick-start) ·
[Validation](#validation--engineering-quality) ·
[Security](#security--tenant-isolation) ·
[ADRs](docs/adr/) ·
[Limitations](#known-limitations--deliberate-deferrals)

</div>

---

## What this is

An HTTP gateway that sits between applications and LLM providers and owns the questions a
provider SDK does not answer: **who is calling, whether they may, which provider should serve it,
whether the budget allows it, what it actually cost, and what to do when the provider fails.**

It is **enterprise-oriented, not production-deployed** — there is no cloud deployment and no live
provider account in this repository. What it does have is a complete serving runtime, validated
against real PostgreSQL and real Redis, with architectural boundaries the build refuses to let
you cross.

## Why it exists

Calling a provider SDK directly works until it meets a real organisation. Then the questions stop
being about prompts:

- Which tenant made this call, and can they reach anyone else's data?
- Are they allowed to use this model at all?
- What happens when the provider starts returning 500s at 2am?
- Who pays, and what stops one team burning the quarterly budget in an afternoon?
- Why did the router pick *that* provider — and can you prove it afterwards?

This is the layer that answers them, with tenant isolation enforced by the database rather than by
application code remembering to filter.

## Architecture

```mermaid
flowchart TB
    C["Client"] --> ING

    subgraph ING["Ingress middleware"]
        direction TB
        I1["Request context"] --> I2["Size limit · 413"] --> I3["Authentication<br/>API key / JWT"] --> I4["Rate limit · 429"]
    end

    ING --> PIPE

    subgraph PIPE["Admission pipeline — first block wins"]
        direction TB
        P1["Authorization<br/>fail-closed RBAC"] --> P2["Policy"] --> P3["Routing<br/>agent runtime"]
    end

    PIPE -->|refused| DENY["403 — no routing,<br/>no spend, no provider call"]
    PIPE -->|admitted<br/>unary or streamed| CACHE{"Cache hit?"}
    CACHE -->|hit| HIT["Return cached<br/>no reservation, no spend"]
    CACHE -->|miss| RES["Budget reservation — HARD GATE"]
    RES -->|denied| B402["402 — provider never called"]
    RES -->|reserved| PROV["LLM provider<br/>OpenAI-compatible HTTP"]
    PROV --> CB["Circuit breaker"] --> OK{"succeeded?"}
    OK -->|yes| SETTLE["Settle actual usage<br/>then write cache"] --> EVAL["Evaluation<br/>non-streaming only"]
    OK -->|no| REL["Release the hold<br/>nothing is charged"]

    OBS["Prometheus · structured logs · hash-chained audit"]
    EVAL --> OBS
    REL --> OBS
    HIT --> OBS
    DENY --> OBS
    B402 --> OBS
    CB -.->|health feeds routing| P3

    PG[("PostgreSQL — RLS FORCE on every tenant table<br/>budgets · cost ledger · cache · pricing · RBAC · audit")]
    RD[("Redis<br/>shared rate-limit buckets")]
    RES -.-> PG
    CACHE -.-> PG
    SETTLE -.-> PG
    I3 -.-> PG
    I4 -.-> RD
```

Layering is enforced by **47 import-linter contracts**, so this diagram cannot silently drift from
the code: delivery cannot reach a provider client, the rate limiter cannot reach the budget ledger,
and a streamed request cannot reach the retry loop.

## Capabilities

Status is deliberately granular. *Distributed* means shared across replicas; *replica-local* means
each process keeps its own copy.

| Capability | Implementation | Status |
|---|---|---|
| **Provider abstraction** | `ProviderClient` / `StreamingProviderClient` ports | Implemented |
| **Provider execution** | Real `httpx` calls to any OpenAI-compatible `/chat/completions` endpoint | Implemented — no vendor SDKs; fails closed when unconfigured |
| **Explainable routing** | 5-agent runtime → typed `RoutingDecision` carrying its reasoning trace | Implemented |
| **Adaptive routing** | `HealthTieredRoutingStrategy` — healthy preferred over recovering, open circuits excluded | Implemented |
| **Circuit breaking** | Three-state breaker per `(tenant, provider)` | Implemented — **replica-local** |
| **Hard budget enforcement** | Reserve → commit in PostgreSQL, row-locked, idempotent | Implemented — **persistent** |
| **Cost accounting** | `Decimal` money, effective-dated pricing, settled on real token counts | Implemented — **persistent** (`cost_ledger`) |
| **Reservation reconciliation** | TTL sweep with `FOR UPDATE SKIP LOCKED` | Implemented — **persistent** |
| **Response caching** | Exact-match, tenant-scoped, TTL | Implemented — **persistent**, exact-match only |
| **Reflection / retry** | Bounded retry through the whole coordinated path | Implemented |
| **Streaming** | Server-Sent Events with a structurally enforced commit boundary | Implemented |
| **Authentication** | API keys + JWT, JWKS publication, signing-key rotation | Implemented |
| **Authorization** | Fail-closed RBAC, permission declared per endpoint | Implemented |
| **Tenant isolation** | `ENABLE` + `FORCE` RLS on every tenant-scoped table and partition (40 tables + 5 partitions today), non-superuser runtime role | Implemented — **enforced by PostgreSQL** |
| **Policy** | `LocalPolicyEngine` as a pipeline stage | Implemented — local/deterministic |
| **Ingress protection** | Per-tenant token bucket + request-size cap | Implemented |
| **Distributed rate limiting** | Redis token bucket, atomic Lua, server-side clock | Implemented — **distributed** |
| **Evaluation** | Two deterministic evaluators, observational | Implemented — non-streaming only |
| **Observability** | 16 Prometheus series, structured logs, hash-chained audit | Implemented |
| **Request deduplication** | `asyncio` single-flight coalescing | Implemented — **replica-local** |

> **On provider integration.** The adapter speaks the OpenAI-compatible wire protocol over `httpx`,
> so it reaches OpenAI, Azure OpenAI, vLLM, Together, Groq or a local runtime once a base URL and
> key are configured. There are **no vendor SDK dependencies** and no native Anthropic/Bedrock/Vertex
> clients. With nothing configured the gateway refuses provider calls rather than fabricating a
> response.

## Request lifecycle

The money path. A budget refusal happens **before** the provider is contacted, and a provider
failure returns the money.

```mermaid
sequenceDiagram
    autonumber
    participant Cl as Client
    participant GW as Gateway
    participant PG as PostgreSQL
    participant PR as Provider

    Cl->>GW: POST /v1/inference
    GW->>GW: ingress → authorize → policy → route
    GW->>PG: cache lookup (tenant-scoped)
    alt cache hit
        PG-->>Cl: 200 — zero spend, provider untouched
    else cache miss
        GW->>PG: reserve(estimated cost) — row-locked
        alt budget exhausted
            PG-->>Cl: 402 — provider is never called
        else hold placed
            GW->>PR: invoke
            alt provider succeeds
                PR-->>GW: response + real token usage
                GW->>PG: settle(actual cost), write cache
                PG-->>Cl: 200
            else provider fails
                PR-->>GW: error
                GW->>PG: release(hold)
                PG-->>Cl: 502 — nothing charged
            end
        end
    end
```

## Routing & provider execution

Routing is **deterministic and explainable, not predictive.** Five agents run in a fixed order and
each contributes a reasoning step; the result is a typed decision that cannot be constructed
without that trace, confined to a single construction site by an AST guard.

```mermaid
flowchart LR
    REQ["Admitted request"] --> RT["AgentRuntime"]

    subgraph AG["Agents, in order"]
        direction TB
        A1["PlannerAgent"] --> A2["PolicyAgent"] --> A3["CostAgent"] --> A4["HealthAgent"] --> A5["ProviderAgent"]
    end

    RT --> AG
    CB[("CircuitBreaker<br/>per tenant+provider")] -->|circuit state| A4
    A4 -->|healthy / degraded / excluded| A5
    A5 --> STRAT["HealthTieredRoutingStrategy<br/>healthy before recovering"]
    STRAT --> DEC["RoutingDecision<br/>+ reasoning trace"]
    DEC --> EXEC["ProviderExecutor"]
    EXEC --> PC["ProviderClient<br/>OpenAI-compatible HTTP"]
    PC -->|outcome| CB

    classDef stub stroke-dasharray: 4 3
    class A2,A3 stub
```

`HealthAgent` reads live circuit state; `ProviderAgent` ranks what remains. A provider that just
failed repeatedly is routed around automatically and re-admitted automatically once it recovers.

**Stated plainly:** the dashed agents — `PolicyAgent` and `CostAgent` — are deliberate placeholders
that validate the orchestration contract. There is **no** cost-optimised, latency-optimised or
learned routing.

## Cost & budget enforcement

**Estimate → reserve → execute → settle on actual usage, or release on failure.**

```mermaid
flowchart TB
    REQ["InferenceRequest"] --> EST["Estimator<br/>character heuristic, deliberately conservative"]
    EST --> PRICE1["PricingPort<br/>effective-dated price_table"]
    PRICE1 --> RESV["ReservationService.reserve<br/>row-locked PostgreSQL transaction"]

    RESV -->|budget exhausted| DENY["402 — provider never called"]
    RESV -->|hold placed| CALL["ProviderExecutor → provider"]

    CALL -->|ProviderUsage<br/>real prompt/completion tokens| ACC["CostAccountant"]
    PRICE1 --> ACC
    ACC --> MONEY["Money — Decimal, 8 dp,<br/>ROUND_HALF_EVEN"]
    MONEY --> SET["settle()"]
    SET --> LEDGER[("cost_ledger<br/>append-only actual cost")]
    SET --> BUDG[("budget_ledger<br/>hold closed")]

    CALL -->|failure / no usage reported| RELEASE["release() — hold returned,<br/>nothing charged"]
    RELEASE --> BUDG

    STALE["Abandoned hold<br/>process died mid-request"] --> RECON["TTL reconciliation<br/>FOR UPDATE SKIP LOCKED"]
    RECON --> BUDG
```

Three properties are worth calling out:

- **The gate is transactional, not advisory.** Reservation happens inside a row-locked PostgreSQL
  transaction, so concurrent requests cannot each independently admit spend against the same
  budget. That is the difference between a budget *limit* and a budget *report*.
- **Estimates never become charges.** No tokenizer exists here, so the pre-call estimate is a
  deliberately conservative character-based heuristic used *only* to size the hold. Settlement uses
  the provider's **actual** reported token counts. If a provider completes but reports no usage, the
  hold is released and the caller is told the answer is untrustworthy — an estimate is never billed
  as if it were a measurement.
- **Money is exact.** `Decimal` quantized to 8 decimal places with banker's rounding, mirroring the
  `numeric(18,8)` ledger columns. Amounts in different currencies cannot be combined.

## Security & tenant isolation

API key / JWT → fail-closed RBAC → PostgreSQL `FORCE` RLS → restricted runtime role → hash-chained audit.

- **Authentication is the only identity source.** The verified principal is attached in exactly one
  place; nothing downstream may derive tenancy from a header or body.
- **Authorization fails closed.** An endpoint must declare the permission it needs, and an unwired
  RBAC backend denies everything rather than allowing it.
- **Isolation is the database's job.** Every tenant-scoped table carries `ENABLE` + `FORCE`
  row-level security, and validation asserts at runtime that the application's role is
  `NOSUPERUSER` / `NOBYPASSRLS` — a superuser connection would silently defeat every policy,
  so the gate checks rather than assumes.
  Migrations run as a separate owner role; the application cannot execute DDL.
- **Secrets are resolved by reference**, never inlined — the resolver maps `gateway/jwt/signing-key`
  to an environment variable and logs only the reference.
- **Audit records are hash-chained** per tenant, so an edited or deleted entry is detectable, and
  **errors disclose nothing** — provider text is never echoed and refusals never name the control
  that refused.

No external security assessment or certification is claimed.

## Reliability

- A typed error taxonomy separates *retryable* (timeout, rate-limited, server error) from
  *permanent* (malformed, unauthenticated), so a caller's bad requests can never trip a healthy
  provider's breaker.
- Retry is bounded and reuses the whole coordinated path, so it cannot bypass the budget gate.
- The cache is written **only** after a complete, settled success.
- Rate limiting is shared across replicas via Redis: refill-and-take is a **single atomic Lua
  script**, so concurrent replicas cannot lose an update and over-admit, and time comes from the
  Redis server so one skewed clock cannot mint tokens. On a Redis outage it **degrades rather than
  fails** — the local bucket keeps enforcing the same policy per replica, the degradation surfaces
  on `/healthz`, and the PostgreSQL-backed budget control is unaffected.

**Replica-local, stated honestly:** circuit-breaker state and request deduplication are per-process.
Across replicas each learns provider health independently. Sharing circuit state requires changing a
synchronous interface — evaluated and deliberately deferred rather than bolted on
([ADR-0021](docs/adr/0021-distributed-runtime-state-scope.md)).

## Observability

16 Prometheus series with runtime-bounded label vocabularies, structured logs correlated by request
id, and a hash-chained audit trail. Metric labels are constrained by an AST guard: a label that
could carry a tenant id fails the build, because a metric keyed on tenant is both a cardinality
explosion and a data leak. Recording is failure-isolated — a broken metric can never change a
request's outcome.

## Project structure

```
backend/src/gateway/
  domain/          pure types, typed errors — depends on nothing
  application/
    ports/         25 interfaces: the seams capabilities plug into
    agents/        routing agents + AgentRuntime
    accounting/    cost, reservation, reconciliation
    execution/     coordinator, cache key, deduplication
    streaming/     SSE coordinator + commit boundary
    pipeline/      admission chain
    reflection/    bounded retry
    evaluation/    observational evaluators
  adapters/        17 packages: providers, persistence, cache, ledger,
                   health, ratelimit, security, audit, policy, pricing…
  delivery/http/   FastAPI routes + middleware — translates only
  config/          composition root: the sole place implementations are chosen
  observability/   metrics + structured logging

backend/tests/     unit · integration (real PostgreSQL/Redis) · security
backend/migrations/ Alembic + reviewed SQL
docs/              architecture, 22 ADRs, evidence, traceability
scripts/           validate.sh/.ps1, run-dev, 17 architecture guards
```

**Dependencies point inward only, and the build enforces it.** `domain` imports nothing;
`application` imports no framework; `adapters` cannot import `delivery`; and only `config` may
construct a concrete implementation. The port interfaces are what make the gateway substitutable —
the same `RateLimiterPort` is satisfied by an in-process bucket and by the Redis one, and swapping
them is a composition-root decision nothing downstream observes.

## Technology stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.13, asyncio |
| API | FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| Data | PostgreSQL, SQLAlchemy 2 (async), asyncpg, Alembic |
| Distributed state | Redis (`redis.asyncio`, Lua) |
| Provider transport | HTTPX |
| Security | PyJWT, `cryptography` |
| Observability | `prometheus-client`, structlog |
| Testing | pytest, pytest-asyncio, pytest-cov, aiosqlite |
| Architecture enforcement | import-linter, mypy `--strict`, Ruff, 17 AST guard scripts |
| Local services | Docker Compose |

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
git clone https://github.com/Stevemeg/enterprise-llm-gateway.git && cd enterprise-llm-gateway
cp backend/.env.example backend/.env          # application settings only
docker compose -f docker-compose.dev.yml up -d   # PostgreSQL (pgvector) + Redis

# Migrations run as the schema OWNER. The application's runtime role (app_rw) is
# deliberately denied DDL, so the owner URL is supplied for this command only.
cd backend
GATEWAY_DATABASE__URL="postgresql+asyncpg://gateway:gateway@localhost:5432/gateway" \
  uv run alembic upgrade head

cd .. && ./scripts/run-dev.sh                 # http://localhost:8000
```

```bash
curl localhost:8000/healthz
# {"status":"ok","version":"0.1.0","checks":[
#   {"name":"database","status":"ok"},{"name":"shared_rate_limit_state","status":"ok"}]}

./scripts/validate.sh        # full validation suite (validate.ps1 on Windows)
```

**Two database roles, one of which is not an application setting.** `GATEWAY_DATABASE__URL` is the
least-privilege runtime role the gateway connects as. `GATEWAY_MIGRATION_DATABASE__URL` is the
schema owner used by migration and validation tooling — it is a **shell variable**, not a `Settings`
field, so export it rather than putting it in `.env` (the example file documents it as a comment for
that reason).

### Calling the inference endpoint

`POST /v1/inference` requires a credential that already exists in the database, and **there is no
public login or bootstrap endpoint.** The gateway verifies API keys and JWTs but nothing in the HTTP
surface issues one, so the operational endpoints above work immediately while inference fails closed
with `401` until a credential is seeded. The authenticated path is covered end to end by
`backend/tests/integration/test_authenticated_inference_postgres.py`, which seeds an organisation and
API key directly against PostgreSQL. A real gap in the demo path, not a documentation oversight.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/inference` | Unary or streamed inference (`"stream": true`) |
| `GET` | `/healthz` `/readyz` `/livez` | Health, readiness, liveness |
| `GET` | `/metrics` | Prometheus exposition |
| `GET` | `/.well-known/jwks.json` | Public signing keys |

This is the gateway's own schema, not an OpenAI-compatible drop-in.

```bash
curl -X POST localhost:8000/v1/inference \
  -H "Authorization: Bearer <api-key-or-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise this contract clause.", "model": "gpt-4o"}'
```

```json
{"content": "…", "provider": "openai", "cached": false,
 "attempts": 1, "request_id": "req_73dd1b52a8b64ab2b2b1ae15e3745c67"}
```

Every error shares one envelope — a real response from a running instance:

```json
{"error":{"type":"authentication_error","code":"authentication_required",
  "message":"This endpoint requires an authenticated principal.",
  "request_id":"req_73dd…","retryable":false}}
```

`402` budget exhausted · `403` refused by a control · `413` body too large · `429` rate limited ·
`502` provider failed · `503` dependency unavailable.

> `docs/api/OpenAPI.yaml` describes a much broader **aspirational** control-plane contract that is
> not implemented. The table above is the live API.

## Validation & engineering quality

| Gate | Result | What it means |
|---|---|---|
| Tests | **989 passed, 0 skipped** | Unit + integration + security; a skipped integration test is treated as a failure, not a pass |
| Coverage | **98%** | Measured over `src/gateway` |
| Types | `mypy --strict`, clean | 286 files, no implicit `Any` |
| Lint / format | Ruff, clean | |
| Architecture | **47/47 import-linter contracts** | Layering violations fail the build |
| Structural guards | **17/17 AST guards** | Construction boundaries, metric cardinality, RLS, script parity |
| Database | Alembic head `0007_rbac_seed_audit_chain` | Migrations applied as the owner role |
| Runtime DB role | `app_rw`, `rolsuper=False`, `rolbypassrls=False` | Asserted at validation time |
| Gates | **Gate 1 + Gate 2 PASS** | Gate 2 runs against real PostgreSQL and real Redis in Docker |

**Architecture here is executable, not decorative.** Import contracts and AST guards fail the build
when a layer reaches somewhere it shouldn't — delivery touching an adapter, a component building its
own rate limiter instead of receiving the shared one, a metric label that could carry a tenant id.
Every guard has been proven to fail on a deliberate violation, because a check that cannot fail is
worse than no check.

Validation is **three-state** — `PASS` / `FAIL` / `INCOMPLETE` — so a run that could not reach
PostgreSQL reports as unverified rather than green.

GitHub Actions runs [`scripts/validate.sh`](scripts/validate.sh) itself against Dockerised
PostgreSQL and Redis started from this repository's own `docker-compose.dev.yml`. CI defines no
separate, weaker check list: whatever the local gate enforces is what CI enforces, including the
zero-skipped rule and the `NOSUPERUSER`/`NOBYPASSRLS` runtime-role check.

One guard checks that the two validation entrypoints stay in step; another checks that no
production module is silently excluded from the repository by a `.gitignore` rule.

## Architecture decisions

22 ADRs in **[`docs/adr/`](docs/adr/)**. The ones that most shape the system:

| ADR | Decision |
|---|---|
| [0016](docs/adr/0016-enterprise-ai-os-architecture.md) | The governing architecture and its five rules — **frozen**; changes require a superseding ADR |
| [0017](docs/adr/0017-postgres-transactional-budget-reservation.md) | Reserve/commit in PostgreSQL rather than Redis, and why atomicity is claimed only where proven |
| [0018](docs/adr/0018-exact-match-response-cache-and-request-deduplication.md) | Exact-match caching; why the semantic tier was deliberately **not** built |
| [0014](docs/adr/0014-runtime-database-role-rls-enforcement.md) | Non-superuser runtime role so RLS is actually enforced |
| [0020](docs/adr/0020-narrowing-proven-vacuous-tier-1-surface.md) | **Removing** interface surface that survived a whole phase with zero callers |
| [0021](docs/adr/0021-distributed-runtime-state-scope.md) | Why shared rate limiting fit behind an existing port while shared circuit breaking did not — and the decision to stop rather than force it |

The last two are the ones worth reading: they record what was *deleted* and what was *declined*.

## Development history

| Phase | Focus | Status |
|---|---|---|
| Foundation | Requirements, architecture, database design, API contracts | Complete |
| Phase 4 | Enterprise AI gateway architecture | **Complete** — [final review](docs/Phase4_Final_Architecture_Review.md) |
| Phase 5 M1–M2 | Streaming inference; serving correctness and debt closure | **Delivered** |
| Phase 5 M3–M4 | Ingress protection; distributed runtime state | **Delivered** |
| Phase 5 M5 | Operational readiness (tracing, deployment, DR) | **Evaluated and formally not justified** — [plan](docs/Phase5_Master_Execution_Plan.md) |

Phase 4 delivered the agent runtime, routing, provider execution, cost accounting, budget
ledger, caching, reflection, evaluation, policy, RBAC, observability and adaptive routing.

M5 was a conditional milestone. It was assessed against the repository rather than assumed, and
recorded as not justified: tracing has no second hop or replica to trace, the migration story and
config validation already existed, and a DR runbook would document a deployment shape this
repository cannot produce. Not building it was the finding.

## Known limitations & deliberate deferrals

- **No credential bootstrap endpoint** and **no admin/control-plane API** — providers, budgets,
  pricing and RBAC are managed by migration or direct SQL.
- **One provider adapter shape** — any OpenAI-compatible HTTP endpoint; no vendor SDKs, no native
  Anthropic/Bedrock/Vertex clients.
- **Routing is health-tiered only** — no cost, latency or learned routing; policy and cost agents
  are placeholders.
- **Circuit-breaker state and request deduplication are replica-local.**
- **Caching is exact-match** — no semantic or near-duplicate matching, and no embedding pipeline.
- **Evaluation is deterministic and observational** — no LLM judge; results are not persisted.
- **Streaming** has no evaluation, deduplication, or pre-first-chunk failover.
- **No distributed tracing and no cloud deployment** — the gateway is run and validated locally,
  and in CI, against Dockerised PostgreSQL and Redis.
- **Deferred by decision, with triggers recorded:** distributed circuit health, semantic/vector
  cache, OPA policy, ML/bandit routing, enterprise memory, benchmark service.

## What this demonstrates

Ports-and-adapters architecture with machine-enforced boundaries · async Python service design ·
LLM provider abstraction and adaptive routing · transactional correctness in PostgreSQL
(row-locked reserve/commit, `FOR UPDATE SKIP LOCKED` reconciliation) · multi-tenant isolation via
RLS and least-privilege database roles · Redis coordination with atomic Lua · resilience patterns
(circuit breaking, bounded retry, degraded-mode fallback) · cost governance with exact decimal
accounting · SSE streaming with an explicit commit boundary · and a validation strategy that treats
architecture as something to execute rather than describe.

## License

Released under the [MIT License](LICENSE).

---

<div align="center">

**Kona Bharath Vamshidhar Reddy**
B.E. Artificial Intelligence & Machine Learning · Acharya Institute of Technology

[GitHub](https://github.com/Stevemeg) ·
[LinkedIn](https://www.linkedin.com/in/kona-bharath-vamshidhar-reddy/) ·
[konabharath2004@gmail.com](mailto:konabharath2004@gmail.com)

<sub>Every claim in this README is grounded in the repository — nothing here describes a capability that does not exist in the codebase.</sub>

</div>
