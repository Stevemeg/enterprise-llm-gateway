# Phase 4 — Final Architecture Review

**Status:** Review artifact (no authority over ADRs or source) · **Created:** 2026-07-25
**Baseline reviewed:** `main` @ `d5d3bc2` · tag `v1.21.0-phase4-slices20-21` · working tree clean
**Method:** reconstructed from source, migrations, composition root, contracts and guards — not from
the evidence logs, which were treated as claims to verify.

This document records a hostile end-of-phase review. It changes no implementation. Where it
disagrees with a living document, the source was taken as authoritative and the disagreement is
noted.

---

## 1. What Phase 4 actually delivered — capability map

Verified against `config/container.py` (the composition root) and the wired call paths. "Consumer"
means a *production* caller reachable from `Container.create`, not a test.

| Capability | Production impl | Port / seam | Real consumer (prod path) | Persistence | Guard/enforcement | Major limitation |
|---|---|---|---|---|---|---|
| Authentication | `CompositeAuthenticator` (API-key + JWT) / `BearerTokenAuthenticator` | `Authenticator`, `AuthAuditSink` | auth middleware | `api_key`, `audit_event`+`audit_chain_head` (Postgres) | import-linter; runtime-role guard | API-key path requires Postgres (ADR-0019 bootstrap); JWT-only otherwise |
| Authorization / RBAC | `SqlPermissionResolver` / `NullPermissionResolver` (fail-closed) | `PermissionResolver` | `AuthorizationStage` (pipeline stage 1) | `role`,`permission`,`role_permission`,`membership` | resolver-construction guard; RBAC import contracts | No admin API to grant/seed at runtime; seed is a migration |
| Pipeline | `RequestPipeline.admit` | `PipelineStage` (Tier-1 inv. 5) | `InferenceService` | none | pipeline-construction guard; "pipeline decides nothing" contract | **Only `before_request` runs**; `after_response`/`on_error` never invoked (see §3) |
| Agents / runtime | `AgentRuntime` (5 agents) | `BaseAgent` (Tier-1) | `AgentOrchestratedRoutingEngine` | none | routing-engine guard; "agents may not orchestrate" | `PolicyAgent`, `CostAgent` are allow-all / fixed-estimate stubs |
| Routing | `AgentOrchestratedRoutingEngine` | `RoutingEngine`, `RoutingDecision` (Tier-1 inv. 3) | `AgentRoutingStage` (pipeline stage 3) | reads catalog | RoutingDecision single-construction guard (Guard L) | `selected_model` never populated (see §3) |
| Tool registry | (protocol + validation impl) | `ToolRegistryPort` (Tier-1 inv. 2) | **none in serving path** | none | registry-construction guard; tool import contract | Seam only; no tool is invoked by the inference path |
| MCP | (protocol + validation impl) | `McpGatewayPort` (Tier-1 inv. 1) | **none in serving path** | none | mcp-construction guard; MCP import contracts | Seam only; no MCP server wired |
| Provider execution | `ProviderExecutor` → `OpenAiCompatibleProviderClient` / `InMemoryProviderClient` | `ProviderClient` | `InferenceCoordinator` | none | provider-construction guard; "execution ⊥ accounting" | Non-streaming; fake client is the silent default (see §4) |
| Usage metering | `ProviderUsage` (real adapter) / synthesized (in-mem) | part of `ProviderClient` | `CostAccountant` at settle | none | — | Real tokens only from the real adapter |
| Cost accounting | `CostAccountant` | `PricingPort` | `ReservationService.settle` | `price_table` (Postgres) | accounting-construction guard | Unpriced model → `UnknownPriceError` → generic 500 (see §6) |
| Budget reservation | `ReservationService` → `SqlBudgetLedger` / `InMemoryBudgetLedger` | `BudgetLedgerPort` | `InferenceCoordinator` | `budget_ledger` (Postgres) | accounting guard; ledger import contracts | No reservation expiry/reconciliation (see §4) |
| Budget (Slice 8) | `BudgetEnforcer` + `InMemoryBudgetStore` | `BudgetPort` | **none — constructed, never called** | in-memory | — | **Dead wiring** superseded by the ledger (see §3) |
| Cache | `SqlResponseCache` / `InMemoryResponseCache` | `ResponseCachePort` | `InferenceCoordinator` | `response_cache` (Postgres) | cache import contracts | Exact-match only (ADR-0018 scoped out semantic) |
| Reflection | `ReflectiveExecutor` + `RetryPolicy` | (no new port) | `InferenceService` | none | "reflection reaches capabilities only via its coordinator" | Retries the whole coordinator path; not a router |
| Evaluation | `EvaluationRunner` (2 pure evaluators) | `Evaluator` | `InferenceService` (post-hoc) | none | "evaluation observes only" | Observational; no LLM judge; results not persisted |
| Policy | `LocalPolicyEngine` | `PolicyEnginePort` | `PolicyStage` (pipeline stage 2) | none | policy-construction; "engines decide policy only" | Local/deterministic; OPA deferred (no consumer) |
| Observability | Prometheus counters/histograms | `observability.metrics` | recorders across capabilities; `/metrics` | none | metric-cardinality guard; "observability ⊥ delivery/config" | Metrics + structured logs only; **no OTel tracing** |
| HTTP inference | FastAPI `inference.py` + middleware | delivery layer | `InferenceService` | none | "delivery translates, reaches inference only via InferenceService" | Non-streaming; body-size/rate limits absent |
| API keys | `AuthenticateApiKey` + `TenantScopedApiKeyRepository` | `Authenticator` | auth middleware | `api_key` (Postgres) | RLS; runtime-role guard | Postgres-only |
| Provider catalog | `SqlProviderCatalog` / `InMemoryProviderCatalog` | `ProviderCatalog` | routing engine | `provider`,`model` (Postgres) | "catalog supplies candidates, does not route" | In-mem catalog starts empty → `NO_CANDIDATE` |
| Provider health / circuit breaking | `InMemoryCircuitBreaker` | `CircuitBreaker` | `HealthAgent` (read), `InferenceCoordinator` (write) | **in-process only** | circuit-breaker construction guard; 2 import contracts | Per-process; no cross-replica state (see §4) |
| Adaptive routing | `HealthTieredRoutingStrategy` | `RoutingStrategy` | `ProviderAgent` | none | 2 routing-strategy import contracts | Deterministic health-tier ranking only; no cost/latency/bandit |

**Enforcement inventory:** 42 import-linter contracts (0 broken at baseline), 15 `check_*.py`
structural guards (14 architectural + runtime-role + parity + migration + powershell-encoding),
three-state validation with parity, 7 Alembic migrations (head `0007_rbac_seed_audit_chain`),
46 tables defined / ~20 with a production reader-writer.

---

## 2. Architecture diagram (text)

```
                      HTTP (FastAPI delivery)  ── /v1/inference, /healthz /readyz /livez /metrics
                                │  translate only; reaches app only via InferenceService
                     ┌──────────▼──────────┐
   Authentication →  │  auth middleware    │  identity: CompositeAuthenticator (API key | JWT)
   (identity source) └──────────┬──────────┘  → audit sink (hash-chained, per-tenant)
                                │  StageContext(org, principal, correlation)
                     ┌──────────▼───────────────── InferenceService ────────────────────────┐
                     │  RequestPipeline.admit   (before_request only; first-block-wins)      │
                     │    1 AuthorizationStage → PermissionResolver (fail-closed)            │
                     │    2 PolicyStage        → LocalPolicyEngine                           │
                     │    3 AgentRoutingStage  → RoutingEngine                               │
                     │         AgentRuntime [planner, policy*, cost*, health, provider]      │
                     │             HealthAgent  ← reads CircuitBreaker                        │
                     │             ProviderAgent → RoutingStrategy (health-tier rank)         │
                     │             ⇒ RoutingDecision  (SINGLE construction site)             │
                     │  admitted ⇒ ReflectiveExecutor(RetryPolicy)                            │
                     │             └─ InferenceCoordinator                                    │
                     │                  cache.get ─(hit)→ return (no spend)                   │
                     │                  (miss) dedup.coalesce →                               │
                     │                     ReservationService.reserve  (budget gate)         │
                     │                     ProviderExecutor.execute → ProviderClient          │
                     │                     CircuitBreaker.observe(outcome)   ← WRITE          │
                     │                     ok  → settle (CostAccountant/price_table) + cache  │
                     │                     err → release                                      │
                     │  EvaluationRunner (post-hoc, observational)                            │
                     └───────────────────────────────────────────────────────────────────────┘
   * PolicyAgent / CostAgent are stubs.   in-process state: CircuitBreaker, Deduplicator.
   Postgres (RLS): api_key, audit_event, role/permission/membership, provider/model/price_table,
                   budget_ledger, response_cache.
```

---

## 3. Vacuous architecture findings

Classification with source evidence.

### LIVE (load-bearing; verified consumed in the serving path)
`RoutingDecision`, `PipelineStage.before_request`, `PermissionResolver`, `PolicyEnginePort`,
`RoutingEngine`, `CircuitBreaker` (read+write), `RoutingStrategy`, `ProviderClient`,
`BudgetLedgerPort`/`ReservationService`, `ResponseCachePort`, `Evaluator`, `PricingPort`,
`Authenticator`, `AuthAuditSink`. All construction guards proven by deliberate-failure in-slice.

### LATENT BUT JUSTIFIED (no serving consumer today, but a defensible reason to exist)
- **`ToolRegistryPort` / `McpGatewayPort` (Tier-1 inv. 1 & 2).** No tool or MCP server is invoked
  by the inference path. Justified: these are the *whole reason* ADR-0016 exists — foundational
  seams deliberately built before their capability so the capability is an extension, not a
  rewrite. They are validated by a first implementation (Rule 4) and enforced by construction
  guards. Their emptiness is the plan, not a defect — but it is real and should be stated: **two
  of the five Tier-1 invariants have no production consumer at end of Phase 4.**
- **In-memory second implementations** (`InMemoryResponseCache`, `InMemoryBudgetLedger`,
  `InMemoryProviderCatalog`, `StaticPriceTable`). Justified twice over: Rule 4's second
  implementation, and the no-Postgres dev/test path. (The in-memory *provider client* is a
  different matter — see §4.)

### VACUOUS / UNJUSTIFIED (exists, has no consumer, and no longer earns its place)
- **`PipelineStage.after_response` and `PipelineStage.on_error`.** `RequestPipeline.admit` calls
  **only `before_request`** (`pipeline/runner.py:185-196`). All four stages implement the other two
  methods, and **nothing ever calls them.** `ports/evaluation.py:24` explicitly records that
  evaluation will *not* route through `after_response`. This is the oldest recorded debt and it is
  genuine over-specification: the Tier-1 stage protocol committed to a request/response lifecycle
  that was never built. **Honest resolution: narrow the protocol to `before_request` (an admission
  seam), or build a real response-phase consumer.** Leaving three methods where one is used is a
  seam shaped by an imagined lifecycle — exactly the Rule-5 smell, one level up.
- **`BudgetEnforcer` + `BudgetPort` + `InMemoryBudgetStore`.** Constructed in the container
  (`container.py:349-351`, held as fields) and **called by nothing.** Budget gating in production is
  entirely `ReservationService`→`BudgetLedger` (ADR-0017). Slice 8's enforcer was superseded by
  Slice 9 and never removed. **Honest resolution: delete the wiring** (keep the port only if a
  concrete future consumer is named).
- **`AgentContext.selected_model` / `RoutingDecision.selected_model`.** No agent ever assigns
  `context.selected_model` (verified: the only reference is the read in `runtime.py:125`). The model
  actually used comes from `RoutingExecution.provider` (a `ProviderDescriptor`). The field is a
  latent parallel that is always `None`. **Honest resolution: populate it (make model selection a
  real agent responsibility) or remove it.**

---

## 4. Production-readiness gap analysis

Treated as if we intended to deploy `d5d3bc2` today. Classified BLOCKER / HIGH-VALUE NEXT /
EVIDENCE REQUIRED / DEFER.

### BLOCKER (a credible enterprise LLM gateway cannot ship without these)
1. **No streaming.** `OpenAiCompatibleProviderClient` issues a single non-streaming
   `POST /chat/completions`; there is no token streaming anywhere in delivery or the coordinator.
   Streaming is table-stakes for an LLM gateway; its absence alone disqualifies production use.
2. **Fake provider client is the silent default.** With no provider connection configured,
   `provider_client = InMemoryProviderClient()`, whose `invoke` **always succeeds and echoes the
   request** while synthesizing usage and booking cost. A deployment with providers seeded in the
   catalog but a missing connection env-var serves fabricated responses instead of failing. This
   must fail closed in production.
3. **Reservation leak on crash.** A process that dies between `reserve` and `settle`/`release`
   leaves the hold `reserved` forever — there is no expiry, sweeper, or reconciliation
   (verified: no `expir*`/`reconcil*`/`sweep`/`ttl` in accounting or ledger). Under real traffic
   this silently erodes tenant budgets.

### HIGH-VALUE NEXT
4. **Cancellation / client-disconnect propagation.** Timeouts are per-provider and explicit
   (good), but a cancelled client request does not demonstrably abort the provider call / release
   the reservation.
5. **Ingress rate limiting and request-size limits.** None present (only provider-side 429
   *classification* and OIDC-JWKS refresh throttling). A gateway without ingress limits is a cost
   and abuse hole.
6. **Unpriced-model mapping.** `UnknownPriceError` currently surfaces as a generic 500 (documented
   debt) — a config defect masquerading as a server fault.
7. **OpenTelemetry tracing.** Metrics + structured logs exist; distributed tracing does not. Needed
   the moment there is more than one hop or replica.

### EVIDENCE REQUIRED (needs a real consumer/limitation before building)
8. **Cross-replica circuit-breaker + deduplication state.** Both are in-process. Correct on one
   node; on N nodes each node learns provider health independently and dedup coalesces nothing
   across nodes. Justified to defer *until* a horizontal-scaling deployment is the actual target —
   at which point ADR-0005 (eventing) or a shared store gains its first real consumer.
9. **Per-org `routing_policy` configuration.** Needs a management API consumer first.

### DEFER (recorded, no consumer, correctly out of scope)
Enterprise Memory, Benchmark Service, semantic/vector cache, OPA, ML/bandit routing. Each is a GP-1
deferral with no consumer today.

---

## 5. Deferred-capability review

For each explicit Phase-4 deferral: consumer? exists today? invalidated by Slices 1–21? keep
deferred? trigger.

| Deferral | Consumer that would use it | Exists today? | Evidence changed it? | Keep deferred? | Trigger to build |
|---|---|---|---|---|---|
| Enterprise Memory | a retrieval-augmented agent | No | No | **Yes** | an agent that must recall prior context |
| Benchmark Service | offline model-quality comparison | No | No | **Yes** | a procurement/quality decision needing scores |
| Semantic/vector cache | the cache lookup path | Exact-match cache exists | No | **Yes** (ADR-0018 scoped out) | measured exact-match hit-rate too low |
| Eventing backbone (ADR-0005) | cross-replica circuit/dedup/audit fan-out | No (Redis runs, unused) | **Yes — §4.8 makes it concrete** | **Conditionally** | first multi-replica deployment |
| Rate limiting | HTTP ingress | No | **Yes — §4.5 is a real gap** | **No — promote** | any internet-facing deployment |
| OPA | `PolicyStage` (swap `LocalPolicyEngine`) | `LocalPolicyEngine` serves the seam | No | **Yes** | a policy the local engine cannot express |
| Durable `provider_health` snapshots | cross-replica health sharing | No | Tied to §4.8 | **Conditionally** | multi-replica + eventing |
| Per-org `routing_policy` config | management/admin API | No | No | **Yes** | an admin surface to read it |
| ML/bandit routing | `RoutingStrategy` (swap strategy) | health-tier strategy serves the seam | No | **Yes** (explainability) | evidence deterministic ranking is insufficient |
| Reservation expiry reconciliation | the ledger itself | No | **Yes — §4.3 is a correctness bug** | **No — promote** | any real deployment |

**Net:** three deferrals have been overtaken by evidence and should be promoted into Phase 5 —
**rate limiting**, **reservation expiry reconciliation**, and (conditionally) **the eventing
backbone**, whose first genuine consumer is cross-replica runtime state.

---

## 6. Bugs / debt discovered

| # | Finding | Class | Evidence |
|---|---|---|---|
| B1 | Fake `InMemoryProviderClient` is the default when no connection is configured; it fabricates success | **BUG (prod risk)** | `container.py:333-337`; `in_memory_client.py` "Always succeeds" |
| B2 | Reservation hold leaks on crash between reserve and settle/release | **BUG** | no expiry/reconciliation in accounting/ledger |
| B3 | Unpriced model → generic 500 instead of tailored fail-closed 5xx | **ARCH DEBT** | plan §"known contradictions"; verified `UnknownPriceError` path |
| D1 | `PipelineStage.after_response`/`on_error` never invoked | **ARCH DEBT (vacuous)** | `runner.py:185-196` |
| D2 | `BudgetEnforcer`/`BudgetPort`/`InMemoryBudgetStore` constructed, never called | **ARCH DEBT (dead wiring)** | `container.py:349-351`; grep shows no caller |
| D3 | `selected_model` latent, always `None` | **ARCH DEBT (vacuous field)** | only read at `runtime.py:125`, never assigned |
| P1 | `PolicyAgent` (allow-all) and `CostAgent` (fixed estimate) are stubs | **INTENTIONAL PLACEHOLDER** | agent docstrings; real policy is `PolicyStage` |
| P2 | `ToolRegistryPort`/`McpGatewayPort` have no serving consumer | **VALID DEFERRED** | Tier-1 seams-first by design |
| C1 | Metric-cardinality guard is name-based and alias-blind | **KNOWN LIMITATION** | guard docstring; documented, not a defect |
| N1 | ~26 tables defined but unused | **VALID DEFERRED** | plan; schema forward-declares future capabilities |

No `TODO`/`FIXME`/`NotImplementedError` anywhere in `src`. Working tree clean (tracked files); the
many `*.tmp` files under `backend/` are git-ignored local editor cruft, not repository content.

---

## 10. Phase 4 final verdict

- **Did ADR-0016's central hypothesis survive?** *Yes, and it is the strongest result of the
  phase.* "Let future capabilities constrain today's interfaces without implementing them, enforced
  by CI not documentation" held across 21 slices: every capability consumed the Tier-1 seams with
  **zero Tier-1 protocol churn**, and no completed module was rewritten. `RoutingDecision` still has
  exactly one construction site 15 slices after it was defined.
- **Genuinely validated rules:** Rule 3 (typed domain objects — repeatedly prevented silent
  disagreement, e.g. `TRANSIENT_PROVIDER_ERROR_CATEGORIES` deduplication), Rule 4 (first
  implementation forced corrections), Rule 5 (Slice 21 *declined* to grow `PlannerDecision` — the
  rule did real work by preventing a change), GP-2 (ADR-0017/18/19 each surfaced a defect a patch
  would have buried).
- **Weakly tested rules:** Rule 1's Tier-1 admission test is only half-exercised — invariants 1 & 2
  (MCP, Tool Registry) never met their capability, so the counterfactual ("omitting the seam would
  force an interface change") was never actually put to the test for them. They are asserted, not
  yet demonstrated.
- **Abstractions that proved unnecessary (so far):** `PipelineStage`'s response lifecycle
  (`after_response`/`on_error`), the Slice-8 `BudgetEnforcer`/`BudgetPort` layer, and
  `selected_model`. Over-built relative to any consumer.
- **Falsified predictions:** none catastrophic; the notable one is that the pipeline's
  request/response symmetry was assumed and never needed.
- **Load-bearing guards:** RoutingDecision single-construction (Guard L), the five
  construction-path guards, the runtime-role/RLS guard, validation parity — all proven to fail on
  deliberate violation. **Near-vacuous:** the circuit-breaker construction guard (one target class)
  and the alias-blind metric-cardinality guard.
- **Biggest architectural risk remaining:** the runtime's **stateful components are single-process**
  (circuit breaker, deduplicator) and the horizontal-scaling story (ADR-0005 eventing) is *accepted
  but unimplemented and unproven*. If the first multi-replica deployment reveals those seams are
  wrong, that is the rewrite ADR-0016 fought to prevent — relocated from the interfaces to the
  runtime.
- **Biggest production risk remaining:** the serving path **cannot stream**, **defaults to a fake
  provider client**, and **leaks budget reservations on crash**.
- **Prototype, production gateway, or between?** **A production-grade *architecture* wrapped around
  a pre-production *runtime*.** The enforcement, security (RLS, fail-closed, hash-chained audit),
  accounting integrity and explainability are genuinely production-quality and unusually rigorous.
  The serving runtime is not deployable as a credible enterprise gateway yet. It is roughly one
  focused hardening phase away — which is precisely what Phase 5 should be.

---

*This review is documentation only. No source, test, guard, migration, threshold, or ADR was
modified. ADR-0016 remains byte-identical.*
