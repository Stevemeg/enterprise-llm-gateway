# ADR-0012: Intelligent routing engine design

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, AI Platform Engineer
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** (routing engine; complements provider abstraction ADR-0003)

## Context & problem
Each request must be routed to the **optimal** model within policy — by cost, latency, quality tier,
weight, or explicit pin (FR-030..033) — with **automatic, bounded failover** across healthy providers
(FR-034..038), optional **cost right-sizing** (FR-039) and **fallback chains/canary** (FR-040/041),
all within the p99 ≤50 ms overhead budget (NFR-P01) and respecting **residency** eligibility
(FR-116/117). The engine is the system's brain; it must be **extensible** (new strategies without core
change, NFR-M02) and **explainable** (record the decision, FR-033).

## Decision drivers
- FR-030..041 (policies, strategies, eligibility, decision recording, failover, circuit breaking,
  right-sizing, fallback, canary), FR-116/117 (residency eligibility).
- NFR-P01 (overhead), NFR-A02 (failover success), NFR-M02 (extensible), RISK-T04 (drift via ADR-0003).

## Options considered
### Option A — Static config/rules table (per-tenant YAML: model → provider, fixed priority)
- **Pros:** Predictable, simple, fast.
- **Cons:** No dynamic cost/latency/health awareness; right-sizing/canary bolted on awkwardly; frequent
  edits. Insufficient for "intelligent."

### Option B — ML/bandit-based adaptive router (learn best model per prompt from feedback)
- **Pros:** Potentially optimal quality/cost over time.
- **Cons:** Opaque (hard to satisfy FR-033 explainability), needs labeled feedback + training infra,
  unpredictable for enterprise governance, risky for v1. Deferred as a future pluggable strategy.

### Option C — **Pipeline of composable strategies over an eligibility filter**, deterministic and
explainable, with health-aware failover and a pluggable strategy interface
A request flows through: **(1) Eligibility filter** — policy + residency + provider/model
enable-state + capability (FR-032, FR-116/117, ADR-0003 registry); **(2) Ranking strategy** —
`lowest_cost` | `lowest_latency` | `quality_tier` | `weighted` | `pinned` (FR-031), using live cost
(price tables) and latency/health signals; **(3) Selection + decision record** (FR-033); **(4)
Execution with bounded failover** — attempt the ranked candidates in order until success or the
attempt/latency budget is exhausted (FR-034/035), honoring **circuit-breaker** state per provider
(FR-037/038); **(5) optional right-sizing/fallback/canary** as strategies (FR-039/040/041). Strategies
implement a `RoutingStrategyPort` (open/closed, NFR-M02). Health/circuit state is maintained from
passive (live errors/latency) and active probes.
- **Pros:** Deterministic + explainable (FR-033); composable and extensible (new strategy = new
  adapter, NFR-M02); residency/eligibility enforced *before* ranking (fail-closed, ADR-0009);
  failover/circuit-breaking built into execution (NFR-A02); low, predictable overhead (NFR-P01). ML
  bandit can later be *one more strategy* behind the same port.
- **Cons:** Rule/threshold tuning per tenant; not self-optimizing (acceptable; explainability
  preferred for enterprise governance).

## Decision
Adopt **Option C**: a **composable strategy pipeline** — *Eligibility filter → Ranking strategy →
Decision record → Bounded failover execution → optional right-sizing/fallback/canary* — with each
strategy behind a `RoutingStrategyPort`. **Residency and policy eligibility are applied first and fail
closed** if no compliant candidate remains (FR-117, ADR-0009). Every decision records the candidate
set, chosen model, and reason into the request trace (FR-033, observability). Failover is bounded by
max attempts + total latency budget (FR-035) and respects circuit-breaker state (FR-037/038). Cost
comes from the versioned **price tables** (ADR-0004/FR-074). An **adaptive/ML strategy (Option B)** is
explicitly left as a future pluggable strategy — not v1 — to preserve explainability and governance.

## Consequences
- **Positive:** Intelligent yet explainable and governable routing; extensible without core change;
  failover and residency correct by construction; predictable overhead.
- **Negative:** Requires per-tenant policy/threshold tuning; not self-learning in v1.
- **Follow-ups:** Phase 7 implements the pipeline, strategies, health/circuit-breaker, and decision
  tracing; Phase 13 load/chaos-tests failover (AC-US-021/022) and overhead (NFR-P01).

## Requirements satisfied
- Functional: FR-030, FR-031, FR-032, FR-033, FR-034, FR-035, FR-036, FR-037, FR-038, FR-039, FR-040,
  FR-041, FR-116, FR-117.
- Non-functional: NFR-P01, NFR-A02, NFR-M02.

## Review notes
Introduce the adaptive/bandit strategy once we have a feedback/eval loop (post-v1) and can preserve an
explainable fallback; add as a new ADR behind `RoutingStrategyPort`.
