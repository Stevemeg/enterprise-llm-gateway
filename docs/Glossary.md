# Glossary

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

Shared vocabulary for the project. Terms are referenced across all requirement documents.

| Term | Definition |
|------|-----------|
| **Adapter** | A component implementing the uniform provider contract, translating between the gateway's internal model and a specific provider's API (request/response/stream/error/usage). |
| **Air-gapped** | A deployment with no general outbound network access; only explicitly approved endpoints (or none) are reachable. |
| **Attribution** | Assigning a request's usage and cost to a tenant, team, key, and optional user/label. |
| **Audit log** | An append-only, tamper-evident record of admin and governance-relevant events. |
| **Budget** | A spending limit for a period (daily/monthly) at tenant, team, or key level; may be soft (warn) or hard (block). |
| **Cache hit / miss** | Whether a response was served from cache (`hit`/`semantic_hit`) or required a provider call (`miss`). |
| **Circuit breaker** | A mechanism that removes an unhealthy provider from rotation after crossing an error threshold, with automatic recovery. |
| **Clean Architecture** | A layered design keeping domain logic independent of frameworks, providers, and delivery mechanisms. |
| **Control plane** | Management functions: tenants, keys, budgets, policies, config, analytics. |
| **Data plane** | The request-serving path: inference API → routing → caching → provider. |
| **Data residency** | Constraints requiring data to be processed only in permitted regions/providers. |
| **Embedding** | A vector representation of text used for semantic similarity (semantic cache, vector features). |
| **Failover** | Automatically retrying a request on the next eligible healthy provider after a retryable failure. |
| **FinOps** | Financial operations discipline for cloud/AI cost management (attribution, budgets, optimization). |
| **Gateway** | This product: the control + data plane between client apps and LLM providers. |
| **Governed traffic** | LLM requests that flow through the gateway (and thus subject to policy, metering, governance). |
| **Hard limit** | A budget/quota that blocks further billable requests once exhausted (fail closed). |
| **Idempotency** | Property ensuring safe retries without duplicated side effects or double-charging. |
| **LLM** | Large Language Model. |
| **Metering** | Recording per-request usage (tokens, model, latency, cost, cache status). |
| **MoSCoW** | Prioritization scheme: Must / Should / Could / Won't-yet. |
| **Multi-tenant** | One deployment serving many isolated organizations (tenants). |
| **NFR / FR** | Non-Functional / Functional Requirement. |
| **OIDC / OAuth2** | Identity/authorization protocols used for admin SSO. |
| **`pgvector`** | PostgreSQL extension for storing and querying vector embeddings. |
| **PII** | Personally Identifiable Information. |
| **Provider** | An LLM vendor or endpoint (OpenAI, Anthropic, Bedrock, Azure OpenAI, self-hosted, etc.). |
| **Quality tier** | A classification of models by capability/quality used in routing decisions. |
| **Quota** | A cap on request/token volume per period, distinct from a monetary budget. |
| **RBAC** | Role-Based Access Control. |
| **Right-sizing** | Selecting the cheapest model that meets quality requirements, escalating only when needed. |
| **Routing policy** | Declarative rules (scoped to tenant/team/key) determining how requests select models/providers. |
| **RTO / RPO** | Recovery Time / Point Objective. |
| **Self-hosted (single-tenant)** | Deployment inside a customer's own environment serving only that customer. |
| **Semantic cache** | Cache that serves responses for prompts similar (by embedding distance) to prior ones, within a threshold and tenant scope. |
| **SLO / SLA** | Service Level Objective / Agreement. |
| **Tenant** | The top-level isolation boundary: a customer organization. |
| **Virtual key** | A scoped API key issued by the gateway for client apps to authenticate inference requests. |
