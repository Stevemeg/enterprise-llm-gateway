# Architecture Implementation Map

**Phase:** 2 — Architecture (organizing artifact) · Draft for approval
**Last updated:** 2026-07-15

This document **organizes the already-approved architecture** into an implementation roadmap for
Phases 3–15. It introduces **no new architecture** — every row references existing
[ADRs](Architecture_Decision_Log.md), [FRs](Functional_Requirements.md),
[NFRs](Non_Functional_Requirements.md), and [Architecture.md](Architecture.md) sections. Columns that
name database components, API specs, or modules are **forward pointers** to artifacts to be produced in
their phase (DB = Phase 3, API = Phase 4, Backend = Phases 5/7/8/9, Frontend = Phase 6, Infra =
Phases 11/12, Tests = Phase 13, Observability = Phase 10) — they are naming/scoping guidance, not new
decisions.

## How to read this
- **Subsystem** — the architectural unit (from [Architecture.md](Architecture.md)).
- **ADRs / FR / NFR** — the approved decisions and requirements it must satisfy.
- **DB / API / Backend / Frontend / Infra / Tests / Observability** — where it will be realized.
- Module/table/endpoint names are **proposed identifiers** to keep later phases consistent; final names
  are fixed in the owning phase.

---

## 1. Subsystem → implementation matrix

### 1.1 Unified Inference API
- **ADRs:** 0001 · **FR:** 001–010 · **NFR:** M01–M04, P01, P04, UX02
- **DB (P3):** none (stateless); reads model registry
- **API (P4):** `POST /v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `GET /v1/models`; canonical error envelope
- **Backend (P5):** `delivery/http/inference_router`, `application/usecases/inference`, `domain/canonical_models`
- **Frontend (P6):** — (API-only; docs surfaced in dashboard "Getting started")
- **Infra (P11/12):** API Deployment + HPA; ingress route `/v1/*`
- **Tests (P13):** contract tests vs OpenAI schema (AC-US-001/002/004); streaming TTFB
- **Observability (P10):** request span root, `x-request-id`, RED metrics

### 1.2 Provider Abstraction Layer
- **ADRs:** 0003 · **FR:** 020–029 · **NFR:** M02, P01, P04, A02
- **DB (P3):** `provider`, `model`, `price_table`
- **API (P4):** admin CRUD `/admin/providers`, `/admin/models`
- **Backend (P5):** `adapters/providers/{openai,anthropic,bedrock,azure,generic}`, `LLMProviderPort`, `ProviderRegistry`
- **Frontend (P6):** Providers & Models management screens (FR-120)
- **Infra:** provider egress allow-list (self-host)
- **Tests (P13):** per-adapter **contract tests** on recorded fixtures (RISK-T04); error-normalization tests
- **Observability:** per-provider latency/error/share metrics (FR-088)

### 1.3 Intelligent Routing Engine
- **ADRs:** 0012, 0003 · **FR:** 030–041, 116–117 · **NFR:** P01, A02, M02
- **DB (P3):** `routing_policy`, `provider_health` (or Redis-held health state)
- **API (P4):** `/admin/routing-policies`
- **Backend (P7):** `application/routing/{eligibility,strategies,failover,circuit_breaker}`, `RoutingStrategyPort`, decision-record emitter
- **Frontend (P6):** Routing policy editor (FR-123)
- **Tests (P13):** failover + circuit-break chaos (AC-US-021/022); overhead load test (NFR-P01)
- **Observability:** routing-decision span attributes, failover counters

### 1.4 Cost Optimization & Budget Enforcement
- **ADRs:** 0004 · **FR:** 060–077 · **NFR:** P05, P06, S05; **SM:** P06
- **DB (P3):** `budget`, `usage_ledger` (append-only, partitioned), `price_table`
- **API (P4):** `/admin/budgets`, `/admin/usage`, `/admin/usage/export`
- **Backend (P5/P7):** `BudgetPort` + `RedisLuaBudgetAdapter`, `application/metering`, `Reconciler`
- **Frontend (P6):** Budgets, alerts, usage/cost dashboards (FR-122/125)
- **Infra:** Redis HA; scheduler CronJob (resets/reconcile)
- **Tests (P13):** **concurrency overspend** test (AC-US-040, RISK-T03); cost-accuracy reconciliation (SM-T07)
- **Observability:** budget-threshold events, reservation/commit metrics

### 1.5 Semantic Cache
- **ADRs:** 0006, 0007 · **FR:** 050–058 · **NFR:** P02, P03, COST01/03, SEC07
- **DB (P3):** `cache_entry` (+ `pgvector` column, HNSW index, `embedding_model/version/dim`), RLS
- **API (P4):** cache flags in response; `/admin/cache/purge`
- **Backend (P8):** `CachePort` (exact/semantic), `EmbeddingPort`, embedding worker, invalidation
- **Frontend (P6):** cache analytics view (FR-126)
- **Tests (P13):** isolation (AC-US-032), false-positive rate, hit-rate/savings (NFR-COST03)
- **Observability:** hit-rate, semantic-score distribution, cost-avoided

### 1.6 Multi-Tenancy & Isolation
- **ADRs:** 0002 · **FR:** 130–138 · **NFR:** SEC07, S03, S06, D01
- **DB (P3):** `tenant`, `team`, `membership`; `tenant_id` + **RLS** on all tenant tables
- **API (P4):** `/admin/tenants`, `/admin/teams`, `/admin/members`
- **Backend (P5):** tenant-context middleware, RLS session binding, scoping in repositories
- **Frontend (P6):** tenant/team/member admin (FR-124)
- **Tests (P13):** **cross-tenant isolation suite** (NFR-SEC07, RISK-T05)
- **Observability:** per-tenant usage/quota metrics

### 1.7 Authentication
- **ADRs:** 0008 · **FR:** 090–097 · **NFR:** SEC01/04/05
- **DB (P3):** `user`, `virtual_key` (hashed, scopes), `signing_key`
- **API (P4):** OIDC login/callback, token refresh; key issue/rotate/revoke `/admin/keys`
- **Backend (P9):** `adapters/oidc` (JWKS), JWT issue/validate, key hashing/rotation
- **Frontend (P6):** SSO login, key management UI
- **Tests (P13):** token validation, key-scope enforcement (AC-US-071)
- **Observability:** auth success/failure metrics, audit on auth decisions

### 1.8 Authorization (RBAC)
- **ADRs:** 0008 · **FR:** 098–101, 128–129 · **NFR:** SEC05, SEC09
- **DB (P3):** `role`, `permission`, `role_permission`
- **API (P4):** enforced on every admin endpoint
- **Backend (P9):** `AuthorizationPort` + central decision function; deny-by-default
- **Frontend (P6):** same decisions gate UI affordances (FR-128)
- **Tests (P13):** least-privilege matrix, auditor read-only (AC-US-072)
- **Observability:** authz allow/deny audit events

### 1.9 Governance (PII / Residency / Audit)
- **ADRs:** 0009, 0010 · **FR:** 110–119 · **NFR:** C01–C06, SEC09
- **DB (P3):** `governance_policy`, `audit_event` (append-only, hash-chained)
- **API (P4):** `/admin/governance`, `/admin/audit` (read/export)
- **Backend (P9):** PII detector/redactor, residency evaluator, audit writer; **fail-closed** wiring
- **Frontend (P6):** audit viewer (FR-127), governance policy config
- **Tests (P13):** PII fail-closed, residency fail-closed, audit immutability (AC-US-080/081/082)
- **Observability:** governance-action events, residency exclusions

### 1.10 Prompt Management
- **ADRs:** 0006, 0009 · **FR:** 118, 058, 110–112
- **DB (P3):** `prompt_template` (+ version) [optional], logging-policy fields
- **API (P4):** template reference id in request (optional)
- **Backend (P5/P8):** normalization, template versioning (cache-key participation), logging policy store/hash/drop
- **Frontend (P6):** later (authoring UI is post-v1 per PRD non-goals)
- **Tests (P13):** cache-key invalidation on template change, logging-policy behavior
- **Observability:** prompt logging-policy counters

### 1.11 Model Registry
- **ADRs:** 0003 · **FR:** 020–021, 028, 074–075
- **DB (P3):** `provider`, `model`, `price_table` (effective-dated, versioned)
- **API (P4):** `/admin/models`, `/admin/price-tables`
- **Backend (P5):** registry service (read by routing/cost), runtime enable/disable
- **Frontend (P6):** model catalog + pricing screens
- **Tests (P13):** price-table versioning → historical cost reproducibility
- **Observability:** model enable/disable audit

### 1.12 Event-Driven & Background Workers
- **ADRs:** 0005, 0004 · **FR:** 066, 070–077, 086–088, 113 · **NFR:** S05, P06, A05, D05
- **DB (P3):** consumers write `usage_ledger`, `audit_event`, `usage_rollup`
- **API (P4):** n/a (internal); DLQ depth exposed via metrics
- **Backend (P5/P7):** `EventBusPort` + Redis Streams adapter (+ Kafka adapter), workers (metering/audit/embeddings/analytics/alerts), idempotency + DLQ
- **Infra:** worker Deployments; Redis Streams / optional Kafka
- **Tests (P13):** at-least-once + idempotency, DLQ handling, throughput to NFR-S05
- **Observability:** consumer lag, DLQ depth, processing rate

### 1.13 Database (PostgreSQL + pgvector)
- **ADRs:** 0002, 0004, 0006 · **FR:** 070–077, 113–114, 130–134 · **NFR:** SEC02/09, S04/S05
- **DB (P3):** full schema, RLS policies, partitions (usage/audit), HNSW index, migrations
- **API (P4):** n/a
- **Backend (P5):** repositories behind ports; migration tooling
- **Infra:** HA Postgres (primary+replica), backups, PITR
- **Tests (P13):** migration tests, RLS tests, partition/scale tests
- **Observability:** DB metrics (connections, replication lag, slow queries)

### 1.14 Redis
- **ADRs:** 0004, 0005, 0006 · **FR:** 050–053, 060–065 · **NFR:** P02/P05, A03/A05
- **DB:** n/a (Redis is the store) — counters, exact cache, streams (logical separation)
- **Backend (P5):** Lua scripts (reserve/commit), cache adapter, streams adapter
- **Infra:** Redis HA (primary+replicas, automatic failover), AOF sized to RPO
- **Tests (P13):** Lua atomicity, failover behavior (fail-closed), cache TTL
- **Observability:** Redis metrics, keyspace, stream lengths

### 1.15 Observability, Logging & Monitoring
- **ADRs:** 0005 · **FR:** 080–089 · **NFR:** O01–O05
- **DB:** telemetry stored in backends (not Postgres)
- **API (P4):** `/health`, `/ready`, `/live`, `/metrics`
- **Backend (P10):** OTel instrumentation, structured JSON logging (PII-scrubbed), Prom exporters
- **Infra:** Prometheus, Grafana, OTel collector; alert rules
- **Tests (P13):** trace-continuity test, dashboard/alert smoke
- **Observability:** the subsystem itself — golden signals + cache/cost/routing dashboards

### 1.16 Secrets Management
- **ADRs:** 0011 · **FR:** 022, 093, 097, 146 · **NFR:** SEC02/03
- **DB:** none (secrets never in DB)
- **Backend (P9):** `SecretsPort` + adapters (cloud KMS / Vault / sealed-secrets), fail-fast startup
- **Infra:** secret store provisioning per mode
- **Tests (P13):** no-plaintext scan, startup-fail-on-missing-secret
- **Observability:** secret-fetch failures alerting

### 1.17 HA / DR / Horizontal Scaling
- **ADRs:** 0010, 0011 · **FR:** 116–117, 140–146 · **NFR:** A01–A06, S01–S02, C02/C05
- **DB (P3):** replication, PITR, cross-region standby
- **Infra (P12):** cells, multi-AZ, HPA, cross-region replication + promotion automation, global router
- **Tests (P13):** **chaos**: region failover (RTO/RPO), pod loss, dependency loss
- **Observability:** SLO dashboards, error-budget burn, replication lag

### 1.18 Deployment (SaaS & Self-Hosted)
- **ADRs:** 0011, 0010 · **FR:** 140–146 · **NFR:** D01–D05, O03/O04
- **Infra (P11/12):** Docker images, **Helm chart**, Terraform modules, `saas`/`self_hosted` profiles, air-gap bundle, upgrade/rollback runbooks
- **Tests (P13):** air-gapped install + rollback (AC-US-110/111), config-validation fail-fast
- **Observability:** deployment health gates

---

## 2. Phase delivery sequence (roadmap)

| Phase | Delivers | Depends on subsystems |
|-------|----------|-----------------------|
| 3 Database | Schema, ERD, RLS, partitions, HNSW | 1.6, 1.13, 1.4, 1.5, 1.9 |
| 4 API contracts | OpenAPI, error taxonomy, admin APIs | 1.1, 1.2, 1.4, 1.7–1.9 |
| 5 Backend core | Inference path, providers, registry, tenancy, metering | 1.1, 1.2, 1.6, 1.11, 1.4 |
| 6 Frontend | Admin dashboard | 1.2, 1.4–1.9, 1.11 |
| 7 Routing engine | Strategies, failover, circuit breaking | 1.3, 1.12 |
| 8 Semantic cache | Exact+semantic, embeddings, invalidation | 1.5, 1.10 |
| 9 Security | AuthN/Z, RBAC, PII, audit, residency, secrets | 1.7–1.9, 1.16 |
| 10 Observability | Telemetry, dashboards, alerts | 1.15 |
| 11 CI/CD | Pipelines, quality/security gates | 1.18 |
| 12 K8s & Terraform | Cells, HA, multi-region, Helm | 1.17, 1.18 |
| 13 Testing | Unit→chaos→security→load | all |
| 14 Documentation | User/ops/API docs | all |
| 15 Hardening | GA readiness, compliance posture | all |

## 3. Traceability guarantee
Every subsystem row lists its ADRs, FRs, and NFRs; combined with
[Traceability_Matrix.md](Traceability_Matrix.md) (Persona→Story→FR→AC) and
[Architecture_Decision_Log.md](Architecture_Decision_Log.md) (decision→FR/NFR), this closes the loop
from **user need → requirement → decision → implementation artifact → test**. No subsystem is without an
ADR; no Must-requirement is without a subsystem.
