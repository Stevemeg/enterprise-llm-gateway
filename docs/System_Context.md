# System Context

**Phase:** 2 — Architecture (organizing artifact) · Draft for approval
**Last updated:** 2026-07-15

This document **consolidates and clarifies** the already-approved system context — actors, services,
providers, trust zones, boundaries, data classes, and ownership. It introduces **no new architecture**;
it is a single-page reference over [Architecture.md](Architecture.md), the
[C4 context](architecture/C4/01-context.md), [trust boundaries](architecture/security/01-trust-boundaries.md),
and [data-flow](architecture/data-flow/01-data-flow.md).

> **Ownership note:** "Owner" columns list the **responsible role/team** (per the project's role model:
> Principal/Platform Engineer, LLMOps, SRE, Security Architect, DevOps, DB Architect, PM, Tech Writer).
> These are role assignments for accountability, not new components.

---

## 1. External actors

| Actor | Description | Interface | AuthN | Refs |
|-------|-------------|-----------|-------|------|
| Application Developer (P-04) | Builds features on the unified API | HTTPS `/v1/*` + SSE | Virtual key (scoped) | FR-001–010, FR-094–097 |
| Platform/AI Infra Engineer (P-01) | Integrates & operates providers/policies | HTTPS admin API + UI | OIDC/JWT | FR-020–041, FR-120–129 |
| Eng Leader / FinOps (P-02) | Budgets, cost, analytics | UI/admin API | OIDC/JWT | FR-060–077 |
| Security & Compliance (P-03) | Governance, audit, residency | UI/admin API | OIDC/JWT | FR-110–119 |
| SRE / Operator (P-05) | Runs the gateway | Ops endpoints, dashboards | OIDC/JWT + infra | FR-080–089 |
| Tenant Administrator (P-06) | Self-service org admin (SaaS) | UI/admin API | OIDC/JWT | FR-130–138 |

## 2. Internal services (trusted zone)

| Service | Responsibility | Owner | Refs |
|---------|----------------|-------|------|
| Edge / API Gateway | TLS, WAF, rate limit, routing | DevOps/SRE | NFR-SEC01/08, FR-065 |
| Inference API | Hot path pipeline | Platform Eng | ADR-0001, Arch §2–4 |
| Admin/Control-plane API | Config + RBAC-guarded management | Platform Eng | FR-120–129 |
| Admin Dashboard (Next.js) | Config + analytics UI | Frontend/Platform | FR-120–129 |
| Worker services | Metering, audit, embeddings, analytics, alerts | LLMOps/Platform | ADR-0005 |
| Scheduler/Reconciler | Budget resets, reconciliation, probes | Platform Eng | ADR-0004 |
| PostgreSQL + pgvector | System of record + vectors | DB Architect | ADR-0002/0006 |
| Redis | Counters, exact cache, streams | Platform/SRE | ADR-0004/0005/0006 |
| Event bus | Async transport (Streams/Kafka) | Platform Eng | ADR-0005 |
| Embedding backend | Vectors (local default) | LLMOps | ADR-0007 |
| Telemetry stack | OTel/Prometheus/Grafana | SRE | NFR-O01–05 |

All internal compute services are stateless, built from one image, horizontally scalable (NFR-S02).

## 3. External providers / third parties

| System | Purpose | Trust | Boundary control | Refs |
|--------|---------|-------|------------------|------|
| LLM Providers (OpenAI, Anthropic, Google, Bedrock, Azure OpenAI, self-hosted) | Model inference | External / semi-trusted | TLS, egress allow-list, governed payloads (PII/residency) | ADR-0003, FR-020–024, FR-110–117 |
| OIDC IdP (Okta/Azure AD/Google) | Admin SSO | External / trusted | OIDC, JWKS validation | FR-090–093 |
| Secrets Manager (KMS/Vault) | Credentials, signing keys | External / trusted | TLS, no plaintext, fail-fast | NFR-SEC03, FR-022/146 |
| Notification channels (email/Slack/webhook) | Alerts | External | Outbound only, no sensitive payloads | FR-066, FR-085 |
| Telemetry backends | Metrics/traces/logs | External or in-cluster | PII-scrubbed, TLS/OTLP | FR-082 |

In **self-hosted/air-gapped** mode, IdP, secrets, and telemetry are **in-cluster** and provider egress
is an approved allow-list ([ADR-0011](adr/0011-self-hosted-deployment-architecture.md)).

## 4. Trust zones

| Zone | Contents | Trust level | Entry control |
|------|----------|-------------|---------------|
| Z0 Untrusted | Public internet: client apps, admin browsers, attackers | None | Edge (TLS/WAF/rate limit) |
| Z1 Edge (DMZ) | Ingress, WAF, LB | Low | Terminates TLS; forwards authenticated traffic |
| Z2 Application | Inference/Admin API, governance | Medium | OIDC/JWT, key validation, RBAC, tenant context |
| Z3 Data | Postgres (RLS), Redis, event bus | High | Reachable only from Z2; RLS; network policy |
| Z4 Secrets | Secrets manager | Highest | Least-privilege fetch; audited |
| Zext External | Providers, IdP | Partner | TLS + egress allow-list; governed data |

Mapped to the five control boundaries in [trust-boundaries](architecture/security/01-trust-boundaries.md)
and the [STRIDE model](architecture/security/02-threat-model-stride.md).

## 5. Network boundaries

| Boundary | From → To | Protocol | Controls | Refs |
|----------|-----------|----------|----------|------|
| Internet ingress | Z0 → Z1 | HTTPS/SSE | TLS 1.2+, WAF, DDoS, rate limit | NFR-SEC01/08 |
| App ingress | Z1 → Z2 | HTTP (internal, mTLS optional) | Auth required, network policy | NFR-SEC05 |
| Data access | Z2 → Z3 | TLS (PG/Redis) | Network policy, RLS session, least-privilege creds | ADR-0002 |
| Secrets fetch | Z2/Z4 | TLS | Scoped tokens, audit | NFR-SEC03 |
| Provider egress | Z2 → Zext | HTTPS | **Allow-list**, cert validation, governed payloads | ADR-0003, FR-142 |
| Cross-region replication (SaaS) | Cell → Cell | TLS | Async, home-region single-writer | ADR-0010 |
| Telemetry export | Z2 → backend | OTLP/TLS | PII-scrubbed | FR-082 |

Self-host collapses cross-region and most egress; only the provider allow-list remains
(air-gap-ready).

## 6. Data classifications

Authoritative summary (full handling in [data-flow §2](architecture/data-flow/01-data-flow.md)).

| Class | Examples | At rest | In transit | Notes |
|-------|----------|---------|-----------|-------|
| Secret | Provider creds, signing keys, raw virtual keys | Secrets mgr / **hashed** | TLS | Never in DB plaintext; keys hashed (FR-022/097) |
| Sensitive | Prompts/completions, embeddings | AES-256; store/hash/drop per policy | TLS | PII-redacted pre-provider; tenant-scoped (FR-110–118) |
| Confidential | Usage ledger, audit, config | AES-256; append-only (ledger/audit) | TLS | Hash-chained audit (FR-113/114) |
| Internal | Metrics, traces, logs | Backend-dependent | TLS/OTLP | PII-scrubbed (FR-082) |
| Public | API schema, docs | — | — | Non-sensitive |

Residency: Sensitive/Confidential data stays in the tenant's **home region** (SaaS) or **customer
boundary** (self-host) — NFR-C02/C05.

## 7. Service ownership

| Service / area | Accountable role |
|----------------|------------------|
| Inference API, provider layer, routing, registry | Principal/Platform Engineer, LLMOps |
| Budgets, metering, reconciliation | Platform Engineer + FinOps stakeholder (PM) |
| Semantic cache, embeddings | LLMOps Engineer |
| AuthN/Z, RBAC, PII, audit, residency, secrets | Security Architect |
| Data schema, RLS, partitions, backups | Database Architect |
| Observability, SLOs, runbooks | SRE |
| CI/CD, images, Helm, Terraform, deployment | DevOps Architect |
| Docs, ADRs, user/ops guides | Technical Writer (with owners) |

## 8. API ownership

| API surface | Path prefix | Owner | Spec (Phase 4) |
|-------------|-------------|-------|----------------|
| Inference (public, OpenAI-compatible) | `/v1/*` | Platform Eng | `docs/api/OpenAPI.yaml` |
| Admin — providers/models/pricing | `/admin/providers,/models,/price-tables` | Platform/LLMOps | OpenAPI (admin) |
| Admin — routing policies | `/admin/routing-policies` | Platform Eng | OpenAPI (admin) |
| Admin — budgets/usage | `/admin/budgets,/usage` | Platform + FinOps | OpenAPI (admin) |
| Admin — tenants/teams/members | `/admin/tenants,/teams,/members` | Platform Eng | OpenAPI (admin) |
| Admin — keys | `/admin/keys` | Security | OpenAPI (admin) |
| Admin — governance/audit | `/admin/governance,/audit` | Security | OpenAPI (admin) |
| Ops — health/metrics | `/health,/ready,/live,/metrics` | SRE | OpenAPI (ops) |
| Auth — OIDC | `/auth/*` | Security | OpenAPI (auth) |

All admin/auth APIs enforce the same RBAC decision function (FR-128) and tenant scoping (FR-129); the
public `/v1/*` surface authenticates via scoped virtual keys. Concrete contracts are authored in
**Phase 4** — this table fixes ownership and path scope only.

---

### Consistency statement
Every actor, service, provider, zone, boundary, data class, and owner above is drawn from the approved
Phase-2 architecture ([Architecture.md](Architecture.md), [C4](architecture/C4/01-context.md),
[trust boundaries](architecture/security/01-trust-boundaries.md),
[data-flow](architecture/data-flow/01-data-flow.md)) and Phase-1 requirements. No new components,
flows, or decisions are introduced.
