# Functional Requirements

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

Each requirement is atomic and testable. IDs are stable and referenced by
[`User_Stories.md`](User_Stories.md), [`Acceptance_Criteria.md`](Acceptance_Criteria.md), and
[`Traceability_Matrix.md`](Traceability_Matrix.md). Priority uses MoSCoW.

Legend — **M** Must · **S** Should · **C** Could.

---

## FR-0xx — Unified Inference API (PR-01)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-001 | Expose `POST /v1/chat/completions` accepting OpenAI-compatible chat request schema. | M |
| FR-002 | Expose `POST /v1/completions` accepting OpenAI-compatible completion schema. | M |
| FR-003 | Expose `POST /v1/embeddings` accepting OpenAI-compatible embeddings schema. | M |
| FR-004 | Expose `GET /v1/models` listing models available to the caller's tenant/policy. | M |
| FR-005 | Accept a `model` alias that the routing engine resolves to a concrete provider model. | M |
| FR-006 | Return responses conforming to OpenAI response schemas plus a gateway `x-request-id`. | M |
| FR-007 | Support streaming responses via SSE for chat/completions when `stream=true`. | M |
| FR-008 | Support batch/multiple inputs for embeddings in a single request. | M |
| FR-009 | Return a documented, typed error envelope for all error classes. | M |
| FR-010 | Never leak provider credentials, internal stack traces, or other tenants' data in responses. | M |

## FR-02x — Provider Abstraction (PR-02)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-020 | Register providers with type, endpoint, auth, region, and capability metadata. | M |
| FR-021 | Register models under a provider with pricing, context window, modality, and quality tier. | M |
| FR-022 | Store provider credentials via the secrets manager, never in plaintext config or DB. | M |
| FR-023 | Provide adapters for major providers (OpenAI, Anthropic, Google, AWS Bedrock, Azure OpenAI). | M |
| FR-024 | Provide a generic OpenAI-compatible adapter for self-hosted/open-weight models. | M |
| FR-025 | Define a uniform adapter contract (request map, response map, stream, error map, token/usage extraction). | M |
| FR-026 | Adding a new adapter requires no change to API or routing layers (open/closed). | M |
| FR-027 | Normalize provider-specific errors into the common error taxonomy. | M |
| FR-028 | Enable/disable providers and models at runtime without redeploy. | S |
| FR-029 | Support per-provider connection settings (timeouts, retries, concurrency caps). | S |

## FR-03x — Routing & Failover (PR-03)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-030 | Support declarative routing policies scoped to tenant/team/key. | M |
| FR-031 | Route by strategy: lowest-cost, lowest-latency, quality-tier, weighted, and explicit pin. | M |
| FR-032 | Evaluate eligibility using policy constraints (allowed providers/regions/models). | M |
| FR-033 | Record the routing decision (candidate set, chosen model, reason) in the request trace. | M |
| FR-034 | Automatically fail over to the next eligible healthy provider on retryable errors/timeouts. | M |
| FR-035 | Bound failover by max attempts and total latency budget. | M |
| FR-036 | Make retries idempotent/safe (no duplicated side effects, correct usage accounting). | M |
| FR-037 | Perform active and passive health checks per provider/model. | S |
| FR-038 | Apply circuit breaking to remove unhealthy providers and auto-recover. | S |
| FR-039 | Support model right-sizing: attempt a cheaper model first, escalate on policy signal. | S |
| FR-040 | Support fallback chains defined per policy. | S |
| FR-041 | Support canary/weighted rollout of a new model within a policy. | C |

## FR-05x — Caching (PR-04)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-050 | Provide exact-match response caching keyed on normalized request + scope. | M |
| FR-051 | Make caching configurable per tenant/policy (on/off, TTL). | M |
| FR-052 | Flag responses with cache status (`hit`/`miss`/`semantic_hit`) and not double-charge cache hits. | M |
| FR-053 | Bypass cache for requests marked non-cacheable (e.g., high temperature/randomness or opt-out). | M |
| FR-054 | Provide semantic caching using embeddings + vector similarity (`pgvector`). | S |
| FR-055 | Make the semantic similarity threshold configurable per policy. | S |
| FR-056 | Record similarity score and source entry for semantic hits (auditability). | S |
| FR-057 | Scope all cache entries to a tenant; never serve across tenants. | M |
| FR-058 | Support explicit and policy-driven cache invalidation (TTL, manual purge, model/version change). | M |

## FR-06x — Budgets, Quotas & Rate Limiting (PR-05)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-060 | Define budgets at tenant, team, and key levels with period (daily/monthly). | M |
| FR-061 | Enforce hard stops: reject billable requests once a budget is exhausted (fail closed). | M |
| FR-062 | Apply most-restrictive-wins across the budget hierarchy. | M |
| FR-063 | Reserve/commit budget atomically to prevent overspend under concurrency. | M |
| FR-064 | Enforce per-key rate limits (RPS) and quotas (requests/tokens per period). | M |
| FR-065 | Return standard rate-limit headers and `429` with retry guidance. | M |
| FR-066 | Emit alerts at configurable budget thresholds (e.g., 80%, 100%). | S |
| FR-067 | Support soft limits (warn but allow) distinct from hard limits (block). | S |
| FR-068 | Allow temporary budget overrides with audit trail and expiry. | S |
| FR-069 | Support scheduled budget resets aligned to billing periods. | S |

## FR-07x — Cost Metering & Attribution (PR-06)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-070 | Meter every request: prompt/completion tokens, model, provider, latency, cache status. | M |
| FR-071 | Compute cost from provider price tables at request time. | M |
| FR-072 | Attribute each usage record to tenant, team, key, and (optional) user/label. | M |
| FR-073 | Persist usage records durably as the system of record for billing/showback. | M |
| FR-074 | Maintain versioned provider price tables with effective dates. | M |
| FR-075 | Cost computation must reconcile with independent recomputation within tolerance. | M |
| FR-076 | Provide usage export (CSV/JSON) filtered by scope and period. | S |
| FR-077 | Provide aggregation APIs (by team/model/day) for analytics. | S |

## FR-08x — Observability & Analytics (PR-07)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-080 | Emit OpenTelemetry traces spanning gateway→routing→provider per request. | M |
| FR-081 | Expose Prometheus metrics for the four golden signals plus cache hit rate and cost. | M |
| FR-082 | Produce structured JSON logs correlated by request ID, with PII handled per policy. | M |
| FR-083 | Propagate/accept trace context (W3C `traceparent`) from callers. | M |
| FR-084 | Provide operational dashboards (latency, traffic, errors, saturation, cache, cost). | M |
| FR-085 | Provide alerting rules for SLO breaches and error-budget burn. | M |
| FR-086 | Provide usage/cost analytics queryable by tenant/team/model/time. | S |
| FR-087 | Track cache effectiveness (hit rate, cost avoided). | S |
| FR-088 | Track routing outcomes (per-provider share, failover counts). | S |
| FR-089 | Retain telemetry per configurable retention policy. | S |

## FR-09x — AuthN/AuthZ, RBAC & Keys (PR-08)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-090 | Authenticate admin/console access via OAuth2/OIDC (corporate SSO). | M |
| FR-091 | Issue and validate signed JWTs for admin sessions with expiry/refresh. | M |
| FR-092 | Support integration with external IdPs (Okta, Azure AD, Google) via OIDC. | M |
| FR-093 | Rotate signing keys and support key revocation. | M |
| FR-094 | Issue virtual API keys for inference clients, scoped to tenant/team. | M |
| FR-095 | Support key scopes/permissions (e.g., chat-only, embeddings-only). | M |
| FR-096 | Support key rotation, revocation, and expiry. | M |
| FR-097 | Store only hashed key material; show full key once at creation. | M |
| FR-098 | Provide RBAC roles: owner, admin, operator, finance, auditor, developer. | M |
| FR-099 | Enforce least-privilege authorization on every admin action. | M |
| FR-100 | Deny-by-default authorization; explicit grants required. | M |
| FR-101 | Audit all authentication and authorization decisions for sensitive actions. | M |

## FR-11x — Governance: PII, Audit, Residency (PR-09)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-110 | Detect PII in prompts/responses using configurable detectors. | M |
| FR-111 | Apply configurable action on detection: redact, block, or allow-with-log. | M |
| FR-112 | Make governance policies scoped per tenant. | M |
| FR-113 | Write immutable, tamper-evident audit records for admin and governance events. | M |
| FR-114 | Prevent modification/deletion of audit records via API. | M |
| FR-115 | Make audit records queryable/exportable for compliance. | M |
| FR-116 | Support data-residency policies restricting providers/regions per tenant. | M |
| FR-117 | Exclude non-compliant routes; fail closed if no compliant route remains. | M |
| FR-118 | Support configurable prompt/response logging policy (store/hash/drop). | M |
| FR-119 | Support configurable data retention and deletion (right-to-erasure support). | S |

## FR-12x — Admin Dashboard (PR-10)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-120 | Provide UI to manage providers and models. | S |
| FR-121 | Provide UI to manage virtual keys and scopes. | S |
| FR-122 | Provide UI to manage budgets, quotas, and alerts. | S |
| FR-123 | Provide UI to manage routing policies. | S |
| FR-124 | Provide UI for RBAC/user & team management. | S |
| FR-125 | Provide usage & cost dashboards (by team/model/time). | S |
| FR-126 | Provide cache & routing analytics views. | S |
| FR-127 | Provide audit log viewer (read-only). | S |
| FR-128 | Enforce the same RBAC in the UI as the API. | M |
| FR-129 | Ensure UI shows only the authenticated tenant's data. | M |

## FR-13x — Multi-Tenancy & Isolation (PR-11)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-130 | Model tenants as the top-level isolation boundary. | M |
| FR-131 | Isolate all tenant data (keys, config, usage, cache, audit) logically. | M |
| FR-132 | Enforce tenant scoping on every query/data path (no cross-tenant reads). | M |
| FR-133 | Support per-tenant configuration (policies, budgets, providers, residency). | M |
| FR-134 | Support tenant lifecycle: create, suspend, delete (with data handling per policy). | M |
| FR-135 | Model teams within a tenant and members within teams. | M |
| FR-136 | Allow tenant admins to manage their teams, members, and keys (scoped). | M |
| FR-137 | Support invitations/role assignment within a tenant. | S |
| FR-138 | Provide per-tenant usage/quota isolation so one tenant cannot degrade another. | M |

## FR-14x — Self-Hosted Deployability (PR-12)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-140 | Provide a single-tenant self-hosted deployment mode with feature parity. | M |
| FR-141 | Drive deployment-mode differences by configuration, from one codebase. | M |
| FR-142 | Support air-gapped/restricted-egress operation (only approved provider endpoints). | M |
| FR-143 | Keep all data within the customer boundary in self-hosted mode; no external telemetry unless configured. | M |
| FR-144 | Provide reproducible deployment via container images + Helm/Terraform. | M |
| FR-145 | Provide health/readiness/liveness endpoints and documented rollback. | M |
| FR-146 | Provide configuration validation and safe startup (fail fast on misconfig). | M |

---

### Notes
- Requirements marked **M** constitute the v1 acceptance boundary; **S/C** may be sequenced across
  milestones M1–M4 (see [`PRD.md`](PRD.md) §7).
- Non-functional constraints (performance, security, scale) are specified separately in
  [`Non_Functional_Requirements.md`](Non_Functional_Requirements.md).
