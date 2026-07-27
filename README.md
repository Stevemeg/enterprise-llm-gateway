# Enterprise LLM Gateway & Cost Router

A multi-tenant control plane between your applications and LLM providers, enforcing
**who may call a model, which provider serves the request, and whether the budget allows it —
before a single token is spent.**

`986 tests` · `0 skipped` · `98% coverage` · `mypy --strict` · `47 machine-enforced architecture contracts` · `PostgreSQL row-level security`
Python 3.13 · FastAPI · PostgreSQL · Redis · async end to end.

## Why this exists

Calling a provider SDK directly works until it meets a real organisation. Then the questions stop
being about prompts: which tenant made this call and can they see anyone else's data, are they
allowed to use this model, what happens when the provider returns 500s at 2am, who pays, and why
did the router pick *that* provider — can you prove it afterwards? This is the layer that answers
them, with tenant isolation enforced by the database rather than by application code remembering
to filter.

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

    PG[("PostgreSQL — RLS FORCE on 34 tables<br/>budgets · cache · pricing · RBAC · audit")]
    RD[("Redis<br/>shared rate-limit buckets")]
    RES -.-> PG
    CACHE -.-> PG
    SETTLE -.-> PG
    I3 -.-> PG
    I4 -.-> RD
```

Layering is enforced by 47 import-linter contracts, so the diagram cannot silently drift from the
code: delivery cannot reach a provider client, the rate limiter cannot reach the budget ledger, and
a streamed request cannot reach the retry loop.

## Key capabilities

| Capability | What is implemented |
|---|---|
| **Authentication** | API-key and JWT credentials, JWKS publication, signing-key rotation with an overlap window. |
| **Authorization** | Fail-closed RBAC — an endpoint must declare the permission it needs, and an unwired backend denies everything. |
| **Explainable routing** | A typed routing decision that **cannot be constructed without its reasoning trace**, confined to one construction site by an AST guard. |
| **Provider execution** | Real HTTP against any OpenAI-compatible endpoint, typed error taxonomy, explicit timeouts. Unconfigured means **fail closed**, never a fabricated answer. |
| **Hard budget enforcement** | Reserve → commit in PostgreSQL, row-locked and idempotent, gating unary and streamed calls alike. |
| **Cost accounting** | Settled against the provider's **actual** token counts and effective-dated pricing, so a historical charge stays reproducible. |
| **Tenant isolation** | `ENABLE` + `FORCE` row-level security on 34 tables, runtime role proven `NOSUPERUSER` / `NOBYPASSRLS`. |
| **Caching** | **Exact-match** (not semantic), tenant-scoped, TTL-expiring. A hit costs nothing and never reaches a provider. |
| **Resilience** | Three-state circuit breaker per (tenant, provider), bounded retry, health-aware ranking. |
| **Streaming** | Server-Sent Events with a structurally enforced commit boundary. |
| **Distributed rate limiting** | Redis token bucket shared across replicas via an atomic Lua script; degrades instead of failing. |
| **Evaluation** | Deterministic, observational checks on completed non-streaming inferences; never alters an outcome. |
| **Observability** | 16 Prometheus series with runtime-bounded labels, request-id-correlated logs, hash-chained audit trail. |

### Routing

Typed, explainable routing with deterministic health-aware provider selection. A decision cannot
exist without its reasoning trace, so routing is auditable by construction rather than by
convention. Ranking is health-tiered — healthy providers preferred over recovering ones, open
circuits excluded — and live circuit state feeds it, so a failing provider is routed around and
re-admitted automatically. An internal agent runtime produces the decision.

There is **no** cost-optimised, latency-optimised or learned routing; those are design targets, not
current behaviour.

## Request lifecycle

The money path: a budget refusal happens **before** the provider is contacted, and a provider failure returns the money.

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

## Hard budget & cost accounting

**Estimate → reserve → execute → settle actual usage, or release on failure.**

The cost is estimated against effective-dated pricing, then **held in a PostgreSQL ledger inside a
row-locked transaction**. If the tenant's budget cannot cover it the request is refused there and
the provider is never contacted — the difference between a budget *limit* and a budget *report*.
Only a reserved request reaches a provider. Settlement closes the hold against the provider's
**actual** reported token usage, and any failure returns the hold, so a failed call costs nothing.

Doing this transactionally buys two properties. **Crash safety:** a process that dies mid-request
leaves a hold that TTL reconciliation reclaims with `FOR UPDATE SKIP LOCKED`, so concurrent
reconcilers take disjoint work and cannot double-credit. **No invented charges:** if a provider
completes but reports no usage, the hold is released and the caller told the answer is
untrustworthy, rather than being billed an estimate.

## Security & multi-tenancy

API key / JWT → fail-closed RBAC → PostgreSQL `FORCE` RLS → restricted runtime role → hash-chained
audit.

- **Authentication is the only identity source.** The verified principal is attached in exactly one
  place; nothing downstream may derive tenancy from a header or body.
- **Authorization fails closed** — no RBAC backend means every request is denied.
- **Isolation is the database's job.** 34 tenant tables carry `ENABLE` + `FORCE` row-level security,
  and validation asserts at runtime that the application's role is `NOSUPERUSER` / `NOBYPASSRLS` —
  a superuser connection would silently defeat every policy, so the gate checks rather than assumes.
  Migrations run as a separate owner role; the application cannot run DDL.
- **Audit records are hash-chained** per tenant, so an edited or deleted entry is detectable, and
  **errors disclose nothing** — provider text is never echoed, and refusals never name the control
  that refused or the limit that was hit.

## Resilience & distributed ingress

A typed error taxonomy separates *retryable* (timeout, rate-limited, server error) from *permanent*
(malformed, unauthenticated), so a caller's bad requests can never trip a healthy provider's
breaker. Retry is bounded and reuses the whole coordinated path, so it cannot bypass the budget
gate; circuit breaking is per (tenant, provider), so one noisy tenant cannot blind another; and the
cache is written **only** after a complete, settled success.

Rate limiting is the one piece of runtime state shared **across replicas**: a per-tenant token
bucket keyed by the authenticated organisation — nothing a caller can spoof. Refill-and-take runs as
a **single atomic Lua script**, so concurrent replicas cannot lose an update and over-admit under
exactly the load that makes a limit matter, and time comes from the Redis server inside that script
so one skewed clock cannot mint tokens for the deployment. Keys are namespaced, TTL'd, and carry no
prompt, credential or content. On a Redis outage it **degrades rather than fails**: the local bucket
keeps enforcing the same policy per replica, the degradation surfaces on `/healthz`, and the
PostgreSQL-backed budget control is unaffected. Verified against real Redis, including a
cross-process test where three independent OS processes share one bucket and admit exactly the
configured burst.

**Known limitation:** circuit-breaker state is process-local, so each replica learns provider health
independently. Sharing it requires changing a synchronous interface — evaluated and deliberately
deferred rather than bolted on (`docs/adr/0021-distributed-runtime-state-scope.md`).

## Streaming

Server-Sent Events on the same endpoint via `"stream": true`, running the *same* admission chain as
the unary path, so the flag cannot be used to get a different answer from a control. Everything that
can fail before the first byte returns an ordinary JSON error with a real status code; once a chunk
is delivered the only honest ending is a terminal error event. That **commit boundary** is enforced
by an import contract — the streaming package physically cannot reach the retry loop — rather than
by a flag someone could misread. Streamed responses are not evaluated, not deduplicated, and have
no pre-first-chunk failover.

## Engineering evidence

| Signal | Value |
|---|---|
| Tests | **986 passing, 0 skipped** |
| Coverage | **98%** |
| Type checking | `mypy --strict`, clean |
| Architecture contracts | **47** import-linter contracts, 0 broken |
| Structural guards | **16** AST/consistency guard scripts |
| Integration realism | validated against **real PostgreSQL and real Redis** in Docker |
| Runtime DB role | asserted `NOSUPERUSER` / `NOBYPASSRLS`; schema at Alembic head `0007_rbac_seed_audit_chain` |

More than a test count: **architectural boundaries are machine-enforced.** Import contracts and AST
guards fail the build when a layer reaches somewhere it shouldn't — delivery touching an adapter, a
component building its own rate limiter, a metric label that could carry a tenant id. Every guard is
proven to fail on a deliberate violation, because a check that cannot fail is worse than no check.
Validation is three-state (`PASS`/`FAIL`/`INCOMPLETE`), so a run that skipped the integration tests
reports as unverified rather than green.

## Quick start

```bash
git clone <repo-url> && cd "Enterprise LLM Gateway & Cost Router"
cp backend/.env.example backend/.env
docker compose -f docker-compose.dev.yml up -d      # PostgreSQL (pgvector) + Redis

# migrations run as the OWNER role — the app's runtime role is denied DDL by design
cd backend && GATEWAY_DATABASE__URL="postgresql+asyncpg://gateway:gateway@localhost:5432/gateway" \
  uv run alembic upgrade head

cd .. && ./scripts/run-dev.sh                       # http://localhost:8000
curl localhost:8000/healthz                         # {"status":"ok", ...}
./scripts/validate.sh                               # full suite (validate.ps1 on Windows)
```

**`/v1/inference` requires a credential that already exists in the database, and there is no public
login or bootstrap endpoint.** The gateway verifies API keys and JWTs but nothing in the HTTP
surface issues one, so the endpoints above work immediately while inference fails closed with `401`
until a credential is seeded. The authenticated path *is* covered end to end by
`backend/tests/integration/test_authenticated_inference_postgres.py`, which seeds an organisation
and API key directly against PostgreSQL; doing so outside the tests means writing those rows
yourself. A real gap in the demo path, not a documentation oversight.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/inference` | Unary or streamed inference (`"stream": true`) |
| `GET` | `/healthz` `/readyz` `/livez` `/metrics` | Health, readiness, liveness, Prometheus |
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
`502` provider failed · `503` dependency unavailable, nothing served.

> `docs/api/OpenAPI.yaml` describes a much broader **aspirational** control-plane contract that is
> not implemented. Treat the table above as the live API.

## Tech stack & repository structure

**Runtime** — Python 3.13 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · asyncpg · Alembic ·
PostgreSQL · Redis · HTTPX · PyJWT · `cryptography` · structlog · `prometheus-client` · Uvicorn.
**Dev** — pytest · pytest-asyncio · pytest-cov · mypy · ruff · import-linter · Docker Compose.

```
backend/src/gateway/
  domain/        # pure types; depends on nothing
  application/   # ports + use cases; no framework imports
  adapters/      # PostgreSQL, Redis, provider HTTP, crypto
  delivery/      # FastAPI routes and middleware; translates only
  config/        # composition root — the only place implementations are chosen
backend/tests/      # unit · integration (real Postgres/Redis) · security
backend/migrations/ # Alembic + reviewed SQL
docs/               # architecture, ADRs, requirements, evidence
scripts/            # validate.sh/.ps1, run-dev, architecture guards
```

Dependencies point inward only and the build enforces it: `application` imports no framework,
`adapters` cannot import `delivery`, and only `config` may construct a concrete implementation.

## Limitations & future work

Stated plainly, because a system that documents only its strengths is not worth trusting.

- **No credential bootstrap endpoint** (see Quick start) and **no admin/control-plane API** —
  providers, budgets, pricing and RBAC are managed by migration or direct SQL.
- **One provider adapter shape** — any OpenAI-compatible HTTP endpoint; no native Anthropic,
  Bedrock or Vertex clients.
- **Routing is health-tiered only** — no cost, latency or learned routing.
- **Circuit-breaker state is process-local** — not shared across replicas.
- **Caching is exact-match** — no semantic or near-duplicate matching.
- **Evaluation is deterministic and observational** — no LLM judge; results are not persisted.
- **Streaming** — no evaluation, deduplication, or pre-first-chunk failover.
- **No distributed tracing and no CI pipeline** — Prometheus metrics and structured logs only;
  validation runs locally through `scripts/validate.sh` / `.ps1`.

**Future work** — distributed circuit health · native provider adapters · admin/control-plane API ·
semantic caching · cost- and latency-aware routing · request tracing. No dates promised.

## Architecture decisions

Recorded as ADRs in **[`docs/adr/`](docs/adr/)** — including why reserve/commit lives in PostgreSQL
rather than Redis, and why the semantic cache tier was deliberately *not* built. Two worth reading:

- **Narrowing proven-vacuous interfaces** — removing protocol methods and a field that survived with
  zero callers, rather than leaving interfaces describing behaviour the system never had.
- **Distributed runtime state** — why shared rate limiting fit behind an existing interface while
  shared circuit breaking did not, and the decision to stop rather than force it.

## License

Licensing has not been finalized. No LICENSE file is currently provided.
