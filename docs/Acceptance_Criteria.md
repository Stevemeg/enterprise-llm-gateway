# Acceptance Criteria

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

Acceptance criteria are expressed in Given/When/Then (Gherkin-style) and keyed to user stories in
[`User_Stories.md`](User_Stories.md). These are the verification anchors referenced by the SRS and
the [`Traceability_Matrix.md`](Traceability_Matrix.md). Only representative/high-value criteria are
enumerated per epic; each becomes executable tests in Phase 13.

---

## Epic A — Unified Inference API

**AC-US-001 (OpenAI-compatible chat)**
- Given a valid virtual key and an OpenAI-format chat request,
  When it is POSTed to `/v1/chat/completions`,
  Then the response matches the OpenAI chat schema and includes a gateway request ID.
- Given an existing OpenAI SDK client,
  When only base URL and key are changed to the gateway,
  Then previously working calls succeed without code changes.

**AC-US-002 (Streaming)**
- Given a request with `stream=true`,
  When the provider streams tokens,
  Then the gateway relays incremental SSE chunks and a terminal `[DONE]` event with no buffering-induced
  delay beyond the routing overhead budget (NFR-PERF).

**AC-US-004 (Consistent errors)**
- Given any downstream provider error,
  When it is returned to the client,
  Then the gateway maps it to a documented, typed error envelope with a stable error code and the
  originating request ID, never leaking provider credentials or internal stack traces.

## Epic B — Provider Abstraction

**AC-US-010 / AC-US-011**
- Given an admin registers a new provider+model with credentials,
  When a routing policy references it,
  Then requests are served through that provider with no application code change.
- Given a new provider adapter implementing the adapter contract,
  When it is added,
  Then no changes are required in the routing engine or API layer (open/closed principle).

**AC-US-012**
- Given a provider is disabled at runtime,
  When new requests arrive,
  Then they are routed to remaining eligible providers and none are sent to the disabled provider.

## Epic C — Routing & Failover

**AC-US-020**
- Given a routing policy prioritizing lowest cost within a quality tier,
  When a request qualifies for two models,
  Then the cheaper eligible model is selected, and the decision is recorded in the request trace.

**AC-US-021 (Failover)**
- Given the primary provider returns a retryable error or times out,
  When failover is enabled,
  Then the request is retried on the next healthy provider within the configured attempt/latency budget,
  and the client receives a successful response without manual retry.

**AC-US-022 (Circuit breaking)**
- Given a provider exceeds its error-rate threshold,
  When the circuit opens,
  Then it is removed from rotation until health checks pass, and an alert is emitted.

## Epic D — Caching

**AC-US-030 (Exact cache)**
- Given an identical request (same normalized inputs, same scope) within TTL,
  When it is received again,
  Then it is served from cache, no provider call is made, and the response is flagged `cache: hit`.

**AC-US-031 (Semantic cache)**
- Given a prompt semantically similar to a cached one above the configured similarity threshold and
  within the same tenant scope,
  When received,
  Then it may be served from the semantic cache and flagged as a semantic hit with the similarity score.

**AC-US-032 (Isolation & invalidation)**
- Given two tenants issue identical prompts,
  When caching is active,
  Then neither tenant is served the other's cached response (cache is tenant-scoped).
- Given a cache entry exceeds TTL or is explicitly invalidated,
  When requested,
  Then it is treated as a miss.

## Epic E — Budgets, Quotas & Rate Limiting

**AC-US-040 (Hard budget)**
- Given a team's monthly budget is exhausted,
  When a new billable request arrives,
  Then it is rejected with a documented `budget_exceeded` error before any provider cost is incurred.
- Given hierarchical budgets, When a key is within its limit but its parent team is over,
  Then the request is rejected (most-restrictive limit wins).

**AC-US-042 (Alerts)**
- Given a budget crosses 80% then 100%,
  When each threshold is crossed,
  Then exactly one alert per threshold is emitted to the configured channel.

## Epic F — Metering & Attribution

**AC-US-050 / AC-US-051**
- Given a completed request,
  When metering runs,
  Then a usage record is persisted with tenant, team, key, provider, model, token counts, and computed
  cost, and is queryable within the freshness SLO.
- Given current provider price tables,
  When cost is computed,
  Then it matches an independent recomputation from token counts within a defined tolerance.

## Epic G — Observability

**AC-US-060 / AC-US-061**
- Given any request,
  When processed,
  Then a distributed trace spans gateway→routing→provider, correlated by request ID across logs,
  metrics, and traces.
- Given the operations dashboard,
  When opened,
  Then it shows latency, traffic, errors, saturation, cache hit rate, and cost, updated within the
  metrics freshness SLO.

## Epic H — Auth, RBAC & Keys

**AC-US-070 / AC-US-072**
- Given an admin authenticates via corporate OIDC,
  When issued a JWT,
  Then access to admin functions is granted only per their RBAC role.
- Given a user with the `auditor` role,
  When they attempt to modify budgets,
  Then the action is denied (read-only), and the attempt is audited.

**AC-US-071 (Virtual keys)**
- Given a virtual key with scope limited to embeddings,
  When used for chat,
  Then the request is rejected with an authorization error.

## Epic I — Governance

**AC-US-080 (PII redaction)**
- Given PII redaction is enabled for a tenant,
  When a prompt contains detectable PII,
  Then the configured policy (redact/block) is applied before the provider call, and the action is
  recorded.

**AC-US-081 (Audit)**
- Given any admin or inference-governance event,
  When it occurs,
  Then an immutable, tamper-evident audit entry is written and cannot be altered or deleted via the API.

**AC-US-082 (Residency)**
- Given a tenant restricted to EU region providers,
  When a request would route to a non-EU provider,
  Then that route is excluded and, if none remain, the request fails closed with a documented residency
  error.

## Epic K — Multi-Tenancy

**AC-US-100 (Isolation)**
- Given tenant A and tenant B,
  When A queries usage, keys, or config,
  Then no data belonging to B is ever returned, under any API path (verified by isolation tests).

## Epic L — Self-Hosted

**AC-US-110 / AC-US-111**
- Given the self-hosted deployment artifact,
  When installed in a customer cluster with no outbound access except approved providers,
  Then all in-scope features function, and no telemetry or data leaves the cluster except as configured.
- Given a deployment,
  When a release is rolled out and then rolled back,
  Then both operations complete via documented procedure with health checks gating traffic.

---

### Definition of Done (phase-agnostic)
A story is Done when: its acceptance criteria pass as automated tests (where practical); the mapped
FRs/NFRs are satisfied; code review passes; Quality Gates (coverage, lint, security scan) are green;
and documentation is updated. See project spec §12.
