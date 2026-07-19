# Technology Decisions

**Phase:** 2 — Architecture · Draft for approval
**Last updated:** 2026-07-15

Rationale for the concrete technology selections. The spec (§2) fixes the primary stack; this document
justifies each choice against requirements and records the alternatives weighed. Deeper decisions have
dedicated [ADRs](adr/).

| Concern | Choice | Key alternatives | Why (requirements) | ADR |
|---------|--------|------------------|--------------------|-----|
| Backend language/runtime | **Python 3.12 + FastAPI (ASGI), async** | Go, Node/NestJS, Django | I/O-bound proxy workload; async fits; typed (Pydantic v2/mypy); mandated stack; rich AI ecosystem. NFR-M03, NFR-P01/P04 | [0001](adr/0001-clean-architecture-and-runtime.md) |
| Internal architecture | **Hexagonal + Clean Architecture** | N-tier, framework-centric | Swappable adapters, testable domain, one codebase→two modes. NFR-M01/M02, NFR-D01 | [0001](adr/0001-clean-architecture-and-runtime.md) |
| Data validation/typing | **Pydantic v2 + mypy (strict)** | dataclasses, marshmallow | Strong typing at boundaries; performance. NFR-M03 | [0001](adr/0001-clean-architecture-and-runtime.md) |
| Primary datastore | **PostgreSQL 16** | MySQL, CockroachDB, DynamoDB | ACID ledger, RLS for tenancy, partitioning, mature. NFR-SEC02/07, NFR-S04/S05 | [0002](adr/0002-multi-tenant-isolation-model.md) |
| Vector search | **pgvector (HNSW)** | Pinecone, Weaviate, Milvus | Reuse Postgres; air-gap-friendly; tenant-scoped; meets ≤40 ms. NFR-P03, NFR-D05 | [0006](adr/0006-semantic-cache-architecture.md) |
| Cache / counters / streams | **Redis 7+** | Memcached, Hazelcast | Atomic Lua for budgets; sub-ms cache; Streams for events; one dependency, 3 roles. NFR-P02/P05, FR-060..065 | [0004](adr/0004-reserve-commit-cost-accounting.md), [0005](adr/0005-eventing-backbone.md) |
| Eventing backbone | **Redis Streams (default) → Kafka/Redpanda (scale)** behind `EventBus` port | SQS/PubSub, RabbitMQ | Air-gap-friendly default; pluggable for scale; no cloud lock-in. NFR-S05/D05/D01 | [0005](adr/0005-eventing-backbone.md) |
| Embeddings | **Bundled self-hosted model (default) + optional external** behind port | External-only, local-only | Air-gap by default; governance-aware; versioned. NFR-P03/D05, ASM-15 | [0007](adr/0007-embedding-strategy.md) |
| AuthN | **OAuth2/OIDC + JWT (JWKS)** | Sessions, API-keys-only | Corporate SSO; standard; rotation/revocation. FR-090..093 | [0008](adr/0008-rbac-model.md) |
| AuthZ | **RBAC over permission catalog** behind `AuthorizationPort` | Hard-coded checks, ABAC/OPA now | Named enterprise roles + fine-grained perms; ABAC-ready later. FR-098..101 | [0008](adr/0008-rbac-model.md) |
| Frontend | **Next.js (App Router) + TypeScript (strict)** | SPA (CRA/Vite), server-rendered templates | Mandated; SSR/RSC; typed; WCAG-capable. FR-120..129, NFR-UX01 | — |
| Containerization | **Docker → Kubernetes 1.29+ (Helm)** | VMs, serverless, Nomad | Portability, HA, one artifact both modes. NFR-D02/D03 | [0011](adr/0011-self-hosted-deployment-architecture.md) |
| IaC | **Terraform + Helm** | Pulumi, CDK, Kustomize | Cloud-neutral, reproducible; customer-runnable. NFR-D03/D04 | [0011](adr/0011-self-hosted-deployment-architecture.md) |
| Telemetry | **OpenTelemetry + Prometheus + Grafana** | Datadog/New Relic (SaaS-only) | Open, self-hostable, air-gap-friendly. NFR-O01..05 | [0005](adr/0005-eventing-backbone.md) |
| Secrets | **`SecretsProvider` port: cloud KMS / Vault / sealed-secrets** | Env vars, in-DB | No plaintext secrets; pluggable per mode; fail-fast. NFR-SEC03, FR-146 | [0011](adr/0011-self-hosted-deployment-architecture.md) |
| CI/CD | **GitHub Actions** (Phase 11) | GitLab CI, Jenkins | Mandated; native to repo; gates quality. NFR-SEC06, SM-Q* | — |
| Multi-region | **Cell-per-region, single-writer-per-tenant** | Single-region, active-active multi-master | Availability + residency + budget correctness. NFR-A01/A05, NFR-C02 | [0010](adr/0010-multi-region-strategy.md) |

**Language note:** Go was seriously considered for raw proxy throughput, but the mandated Python/
FastAPI stack, the team's typing/tooling standards, and the AI ecosystem (embeddings, tokenizers)
outweigh the per-request CPU advantage for an I/O-bound workload where provider latency dominates; the
overhead budget (NFR-P01) is met with async Python plus horizontal scaling. Should Phase 13 reveal a
CPU-bound hot spot (e.g., tokenization), that component can be isolated/optimized without changing the
stack — recorded as a future ADR if needed.
