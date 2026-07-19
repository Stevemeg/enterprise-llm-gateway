# Enterprise LLM Gateway — Backend

Production backend for the Enterprise LLM Gateway & Cost Router: an async Python service implementing a
unified, OpenAI-compatible inference API plus routing, semantic caching, hierarchical budgets,
governance, and observability — served from **one codebase** as multi-tenant SaaS or single-tenant
self-hosted.

> **Status:** scaffolding only. This directory currently contains **governance documents**, not code.
> Application code begins in **Phase 5** and must follow the
> [Backend Implementation Guide](../docs/Backend_Implementation_Guide.md) (the constitution).

## Start here
1. [ARCHITECTURE.md](ARCHITECTURE.md) — layers, ports/adapters, processes, dependency rule.
2. [CONTRIBUTING.md](CONTRIBUTING.md) — workflow, PR checklist, testing, CI gates.
3. [STYLE_GUIDE.md](STYLE_GUIDE.md) — code style, typing, naming, errors, logging.
4. [Backend Implementation Guide](../docs/Backend_Implementation_Guide.md) — the authoritative constitution.

## Tech stack (target)
Python 3.13 (managed by **uv**) · FastAPI (ASGI, async) · Pydantic v2 · SQLAlchemy 2.x + asyncpg · Alembic ·
PostgreSQL 16 + pgvector · Redis 7 · structlog · OpenTelemetry/Prometheus · Docker/Kubernetes.
Tooling: `ruff`, `mypy`, `pytest`. Rationale: [Technology_Decisions](../docs/Technology_Decisions.md).

## Planned layout (see ARCHITECTURE.md)
```
src/gateway/{domain, application, adapters, delivery, config, observability, shared}
migrations/  tests/{unit,integration,e2e,contract,load}  scripts/
```

## Processes (one image, three roles)
- **api** — inference + admin HTTP/SSE (hot path)
- **worker** — event consumers (metering, audit, embeddings, analytics, alerts)
- **scheduler** — reconciler, budget resets, partition mgmt, health probes, retention

## Run (Phase 5+, placeholder)
Local dev, migrations, and test commands will be documented here once `pyproject.toml` and the compose/
dev tooling land in Phase 5. Nothing is runnable yet — by design.

## Non-negotiables
- Dependencies point inward; the domain imports no frameworks (ADR-0001).
- Every tenant query is RLS-scoped (ADR-0002); secrets are references only (ADR-0011).
- No secret in code or logs; tests + Quality Gates green before merge.

## References
[Architecture](../docs/Architecture.md) · [ADRs](../docs/adr/) · [Schema](../docs/Schema.sql) ·
[OpenAPI](../docs/api/OpenAPI.yaml) · [API docs](../docs/API_Design_Guide.md).
