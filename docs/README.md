# Documentation Index

Single source of truth for the **Enterprise LLM Gateway & Cost Router**. All documentation lives
under `/docs`; architecture diagrams under `/docs/architecture`; ADRs under `/docs/adr`; API specs
under `/docs/api`.

## Phase 1 — Discovery & Requirements

| Document | Purpose |
|----------|---------|
| [Project_Overview.md](Project_Overview.md) | Vision, problem, goals/non-goals, deployment modes. |
| [PRD.md](PRD.md) | Product requirements, positioning, scope, capabilities. |
| [SRS.md](SRS.md) | Software requirements specification (ISO/IEC/IEEE 29148 style). |
| [User_Personas.md](User_Personas.md) | Personas P-01…P-06 and their goals. |
| [User_Stories.md](User_Stories.md) | Epics A–L with stories US-### and priorities. |
| [Acceptance_Criteria.md](Acceptance_Criteria.md) | Given/When/Then criteria keyed to stories. |
| [Functional_Requirements.md](Functional_Requirements.md) | FR-001…FR-146, atomic and testable. |
| [Non_Functional_Requirements.md](Non_Functional_Requirements.md) | NFRs (perf, scale, security, etc.). |
| [Competitor_Analysis.md](Competitor_Analysis.md) | Market + competitor landscape (mid-2026). |
| [Assumptions.md](Assumptions.md) | Assumptions, constraints, open questions. |
| [Risks.md](Risks.md) | Scored risk register with mitigations. |
| [Success_Metrics.md](Success_Metrics.md) | North-star, business, SLO, and quality KPIs. |
| [Glossary.md](Glossary.md) | Shared terminology. |
| [Traceability_Matrix.md](Traceability_Matrix.md) | Persona → Story → FR/NFR → Acceptance mapping. |

## Phase 2 — Architecture

| Document | Purpose |
|----------|---------|
| [Architecture.md](Architecture.md) | Master architecture: high-level + every subsystem. |
| [System_Context.md](System_Context.md) | Actors, services, providers, trust zones, boundaries, data classes, ownership. |
| [Architecture_Implementation_Map.md](Architecture_Implementation_Map.md) | Subsystem → ADR/FR/NFR/DB/API/modules/infra/tests/observability roadmap (Phases 3–15). |
| [Technology_Decisions.md](Technology_Decisions.md) | Technology selections with rationale. |
| [Architecture_Decision_Log.md](Architecture_Decision_Log.md) | Tabular summary of all 13 decisions. |
| [adr/](adr/) | 13 Architecture Decision Records (ADR-0000…0012). |
| [architecture/C4/](architecture/C4/) | C4 context, container, component, code diagrams. |
| [architecture/sequence/](architecture/sequence/) | 6 sequence diagrams (inference, failover, budget, cache, auth, async). |
| [architecture/deployment/](architecture/deployment/) | SaaS + self-hosted deployment diagrams. |
| [architecture/data-flow/](architecture/data-flow/) | Data-flow diagrams + data classification. |
| [architecture/security/](architecture/security/) | Trust boundaries + STRIDE threat model. |

## Phase 3 — Database Architecture

| Document | Purpose |
|----------|---------|
| [Database_Design.md](Database_Design.md) | Design narrative: conventions, domains, decisions, normalization, JSONB/pgvector. |
| [Schema.sql](Schema.sql) | Full PostgreSQL 16 DDL: 40 tables, enums, constraints, indexes, RLS, partitioning. |
| [ERD.md](ERD.md) | Entity-relationship diagrams (all tables) + many-to-many list. |
| [Data_Dictionary.md](Data_Dictionary.md) | Per-table: purpose, keys, constraints, indexes, growth, volume, retention. |
| [Indexing_Strategy.md](Indexing_Strategy.md) | Every index justified; pgvector/HNSW detail. |
| [Partitioning_Strategy.md](Partitioning_Strategy.md) | Justified partitioning (usage_ledger, audit_event). |
| [Migration_Strategy.md](Migration_Strategy.md) | Ordering, seed, zero-downtime, CI validation. |
| [Backup_and_Recovery.md](Backup_and_Recovery.md) | Backups, PITR, replication, DR runbooks. |
| [Data_Retention.md](Data_Retention.md) | Per-entity retention, archival, GDPR erasure. |
| [RLS_Strategy.md](RLS_Strategy.md) | Row-Level Security model, roles, append-only, testing. |
| [Database_Naming_Standards.md](Database_Naming_Standards.md) | Naming rules: tables, columns, keys, indexes, constraints, triggers, partitions, sequences, migrations. |
| [Database_Dependency_Map.md](Database_Dependency_Map.md) | Every table → ADRs/FR/NFR/subsystem/parents/children/APIs/modules/retention/RLS/audit. |
| [Query_Performance_Guide.md](Query_Performance_Guide.md) | Query patterns, hot/cold, R/W ratios, pagination, vector/join strategy, transactions, locking, pooling. |

## Phase 4 — API Contracts & Developer Platform

| Document | Purpose |
|----------|---------|
| [api/OpenAPI.yaml](api/OpenAPI.yaml) | OpenAPI 3.1 contract: 53 paths, 87 operations, 98 schemas. |
| [API_Design_Guide.md](API_Design_Guide.md) | Principles, URI/resource/method conventions. |
| [API_Error_Model.md](API_Error_Model.md) | Unified error envelope, stable codes, retry semantics. |
| [API_Versioning_Strategy.md](API_Versioning_Strategy.md) | Versioning, compatibility, breaking-change policy. |
| [API_Authentication.md](API_Authentication.md) | API keys + OIDC/JWT + RBAC per endpoint. |
| [API_Pagination_Filtering.md](API_Pagination_Filtering.md) | Keyset pagination, filtering, sorting. |
| [API_Idempotency.md](API_Idempotency.md) | Idempotency-Key semantics; budget-safe retries. |
| [API_Rate_Limiting.md](API_Rate_Limiting.md) | Rate limits & quotas vs. budgets. |
| [API_Streaming.md](API_Streaming.md) | SSE inference streaming; WebSocket justification. |
| [API_Webhooks.md](API_Webhooks.md) | Outbound webhooks, signing, retries/DLQ. |
| [API_SDK_Guidelines.md](API_SDK_Guidelines.md) | Python/TypeScript/Go/Java SDKs from OpenAPI. |
| [API_Governance.md](API_Governance.md) | Naming/resource/header/tracing rules + linting. |
| [API_Changelog_Policy.md](API_Changelog_Policy.md) | Change classification & publication. |
| [API_Deprecation_Policy.md](API_Deprecation_Policy.md) | Deprecation lifecycle & sunset windows. |
| [API_Examples.md](API_Examples.md) | Representative request/response examples. |
| [API_Testing_Strategy.md](API_Testing_Strategy.md) | Contract/conformance/security/load test plan. |
| [API_Implementation_Map.md](API_Implementation_Map.md) | Endpoints → ADR/FR/NFR/tables/modules/tests/obs. |

## Phase 5 — Backend governance & implementation

| Document | Purpose |
|----------|---------|
| [Backend_Implementation_Guide.md](Backend_Implementation_Guide.md) | The backend "constitution": structure, layers, patterns, DI, config, errors, logging, middleware, workers, testing, style. |
| [../backend/README.md](../backend/README.md) | Backend entry point & orientation. |
| [../backend/ARCHITECTURE.md](../backend/ARCHITECTURE.md) | Code-facing layer/ports/adapters summary. |
| [../backend/CONTRIBUTING.md](../backend/CONTRIBUTING.md) | Workflow, PR checklist, gates. |
| [../backend/STYLE_GUIDE.md](../backend/STYLE_GUIDE.md) | Coding standards. |

## Implementation status

The backend is implemented and validated; see the root [README](../README.md) for the
capability summary and the honest list of current limitations.

| Area | Location | Status |
|------|----------|--------|
| Serving runtime, routing, budgets, caching, streaming, ingress protection | [`backend/src/gateway`](../backend/src/gateway) | Implemented |
| Unit · integration (real PostgreSQL/Redis) · security tests | [`backend/tests`](../backend/tests) | 986 passing, 0 skipped, 98% coverage |
| Schema & migrations | [`backend/migrations`](../backend/migrations) | Alembic head `0007_rbac_seed_audit_chain` |
| Architecture decisions | [`adr/`](adr/) | 22 ADRs |
| Frontend, Kubernetes/Terraform, CI, distributed tracing | — | Not built |

> [`api/OpenAPI.yaml`](api/OpenAPI.yaml) is an **aspirational** Phase-4 contract covering a much
> broader control plane than is implemented. The live API is documented in the root README.

## Conventions

- **Requirement IDs are stable**: FR-###, NFR-XXX, US-###, P-##, RISK-*, ASM-*, SM-*. Do not renumber;
  deprecate instead.
- **Priority**: MoSCoW (Must/Should/Could).
- **Changes** to approved requirements are recorded via ADRs under [`adr/`](adr/).
- **Evidence over assertion**: architectural claims are backed by import-linter contracts,
  AST guards and tests rather than by prose.
