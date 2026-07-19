# C4 — Level 2: Containers

**Scope:** The deployable/runnable units inside the gateway and their interactions.
Back to [Architecture](../../Architecture.md) · [C4 index](README.md).

```mermaid
C4Container
    title Container Diagram — LLM Gateway & Cost Router

    Person(apps, "Client apps", "OpenAI-compatible")
    Person(admin, "Admins")

    System_Boundary(gw, "LLM Gateway") {
        Container(edge, "Edge / API Gateway", "LB + TLS + WAF + rate limit", "Terminates TLS, WAF, coarse rate limiting")
        Container(api, "Inference API Service", "Python/FastAPI (ASGI)", "Hot path: authN/Z, governance, budget reserve, cache, routing, provider call, streaming")
        Container(adminapi, "Admin/Control-plane API", "Python/FastAPI", "Providers, models, policies, budgets, keys, audit; RBAC-guarded")
        Container(ui, "Admin Dashboard", "Next.js/TypeScript", "Config + usage/cost analytics UI")
        Container(workers, "Worker Services", "Python", "metering, audit, embeddings, analytics, alerts (event consumers)")
        Container(sched, "Scheduler/Reconciler", "Python", "Budget resets, Redis↔ledger reconciliation, health probes")

        ContainerDb(pg, "PostgreSQL + pgvector", "Postgres 16", "System of record: tenants, keys, policies, ledger, audit, cache vectors")
        ContainerDb(redis, "Redis", "Redis 7+", "Budget counters (Lua), exact cache, event streams")
        Container(bus, "Event Bus", "Redis Streams / Kafka", "Async event transport")
        Container(embed, "Embedding Backend", "Local model / external", "Vector embeddings for semantic cache")
    }

    System_Ext(providers, "LLM Providers")
    System_Ext(idp, "OIDC IdP")
    System_Ext(secrets, "Secrets Manager")
    System_Ext(otel, "OTel/Prometheus/Grafana")

    Rel(apps, edge, "HTTPS + SSE")
    Rel(admin, edge, "HTTPS")
    Rel(edge, api, "Routes inference")
    Rel(edge, adminapi, "Routes admin")
    Rel(edge, ui, "Serves UI")
    Rel(ui, adminapi, "REST (OIDC/JWT)")
    Rel(api, redis, "Reserve budget (Lua), exact cache")
    Rel(api, pg, "Semantic cache lookup (pgvector), reads")
    Rel(api, embed, "Embed prompt (gated)")
    Rel(api, providers, "Routed model calls")
    Rel(api, idp, "Validate JWT (JWKS)")
    Rel(api, secrets, "Provider creds / signing keys")
    Rel(api, bus, "Publish events (usage, audit, embed, alert)")
    Rel(bus, workers, "Consume (groups, ack, DLQ)")
    Rel(workers, pg, "Ledger, audit, aggregates, vector upsert")
    Rel(adminapi, pg, "CRUD config")
    Rel(sched, redis, "Reconcile / reset")
    Rel(sched, pg, "Reconcile source of truth")
    Rel(api, otel, "Traces/metrics/logs")
    Rel(workers, otel, "Traces/metrics/logs")
```

## Container responsibilities

| Container | Responsibility | Key ADR / FR |
|-----------|----------------|--------------|
| Edge / API Gateway | TLS, WAF, coarse rate limiting, routing to services | NFR-SEC01/08, FR-065 |
| Inference API | The hot path pipeline (§2 Architecture) | ADR-0001/0004/0006/0012 |
| Admin/Control-plane API | Configuration + RBAC-guarded management | ADR-0008, FR-120..129 |
| Admin Dashboard | Next.js UI, same RBAC as API | FR-120..129, NFR-UX01 |
| Workers | Off-path metering/audit/embeddings/analytics/alerts | ADR-0005, FR-070..088/113 |
| Scheduler/Reconciler | Budget resets, reconciliation, probes | ADR-0004, FR-069 |
| PostgreSQL+pgvector | System of record + vectors | ADR-0002/0006 |
| Redis | Counters + exact cache + streams | ADR-0004/0005/0006 |
| Event Bus | Async transport (pluggable) | ADR-0005 |
| Embedding backend | Vectors (local default) | ADR-0007 |

All compute containers are built from **one image**, stateless, horizontally scalable (NFR-S02). In
self-hosted mode the external systems and data stores run **in-cluster**
([ADR-0011](../../adr/0011-self-hosted-deployment-architecture.md)).

**Requirements:** FR-001..146 (distributed across containers); NFR-P*, NFR-S*, NFR-A*, NFR-D*.
