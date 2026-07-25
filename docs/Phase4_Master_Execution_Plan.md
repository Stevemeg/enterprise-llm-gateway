# Phase 4 — Master Execution Plan

**Status:** Living document · **Created:** 2026-07-24 (Slice 16) · **Governs:** Phase 4 sequencing

## Why this document exists, and why it did not until now

ADR-0016 states that it "establishes the framing for the Phase-4 Master Execution Plan". **That
plan was never written.** Slices 1–15 were sequenced from ADR-0016's tier tables plus
`Architecture_Evidence_Log.md`, which worked, but left a frozen ADR pointing at a document that had
never existed in the working tree, the index, or any commit in history. Slice 16 closes that
dangling reference by writing the plan from the approved planning checkpoint and the repository's
actual state.

**`AIOS_Architecture.md` was deliberately NOT created.** ADR-0016 mentions planning documentation
generally; it does not name that file, and `ADR-0016` plus `docs/Architecture.md` already serve the
architecture-narrative purpose. Creating a document to satisfy a remembered filename would be
exactly the speculative artifact GP-1 forbids.

## Authority

This plan is **subordinate** to accepted ADRs and to the source code. Where it disagrees with them,
they win and this document is wrong. It records *sequencing intent*, not architecture. ADR-0016
remains **frozen**: nothing here amends it.

## Delivered — Slices 1–17

| # | Milestone | Type | Tag |
|---|---|---|---|
| 1 | AI OS Foundation (seams only) | Foundation | `v1.1.0-aios-foundation` |
| 2 | Agent Runtime + first `PipelineStage` consumer | Foundation | `v1.1.0-phase4-slice2` |
| 3 | Tool Registry | Foundation | `v1.2.0-phase4-slice3` |
| 4 | MCP Gateway | Foundation | `v1.4.0-phase4-slice4` |
| 5 | RBAC foundation | Capability | `v1.5.0-phase4-slice5` |
| 6 | Routing Engine | Capability | `v1.6.0-phase4-slice6` |
| 7 | Provider Execution | Capability | `v1.7.0-phase4-slice7` |
| 8 | Usage Metering / Cost Accounting / Budget | Capability | `v1.8.0-phase4-slice8` |
| 9 | Persistent Ledger + Atomic Reservation (ADR-0017) | Capability | `v1.9.0-phase4-slice9` |
| 10 | Exact-match Cache + Dedup (ADR-0018) | Capability | `v1.11.0-phase4-slices10-11` |
| 11 | Reflection / Retry | Capability | `v1.11.0-phase4-slices10-11` |
| 12 | Evaluation Pipeline | Capability | `v1.13.0-phase4-slices12-13` |
| 13 | Policy Engine Foundation | Capability | `v1.13.0-phase4-slices12-13` |
| 14 | Request Admission Pipeline | Foundation | `v1.15.0-phase4-slices14-15` |
| 15 | Served Inference Path | Capability | `v1.15.0-phase4-slices14-15` |
| 16 | Production Observability | Capability | `v1.17.0-phase4-slices16-17` |
| 17 | HTTP Inference Endpoint + Authentication Wiring | Capability | `v1.17.0-phase4-slices16-17` |
| 18 | RBAC Durable Storage + Hash-Chained Audit Sink (ADR-0019) | Capability | `v1.19.0-phase4-slices18-19` |
| 19 | Real Provider Adapter + Durable Catalog/Pricing | Capability | `v1.19.0-phase4-slices18-19` |
| 20 | Provider Health & Circuit Breaking | Capability | *pending publication* |
| 21 | Adaptive Routing | Capability | *pending publication* |

Slice 18 introduced one new architectural decision,
**[ADR-0019](adr/0019-api-key-credential-bootstrap-lookup.md)** (the sanctioned `SECURITY DEFINER`
credential-bootstrap lookup); Slice 19 changed no ADR (it added `organization_id` to the
capability-owned `PricingPort` under Rule 5). Slices 20–21 are implemented, fully validated (Gate 1
+ Gate 2, 806 passed / 0 skipped / 97%) and awaiting the publication step; neither changed an ADR.
Slice 20 introduced the capability-owned `CircuitBreaker` port (no ADR, the same footing as
`PermissionResolver`/`PricingPort`); Slice 21 introduced the capability-owned `RoutingStrategy`
port and, per Rule 5's own third test, did **not** grow `PlannerDecision` — the health-tiered
strategy consumes none of its deferred fields, so no field nothing reads was added.

**Slice 21's conditionality (from the plan) was resolved to "justified".** ADR-0016 marked Adaptive
Routing conditional on "16 + 20 producing evidence justifying it". Slice 20 produces exactly that
evidence: providers now carry differentiated live circuit health (closed / half-open / open), so
selecting the first usable candidate is demonstrably suboptimal when a healthier alternative exists.
Adaptive Routing was therefore implemented as ADR-0012's deterministic ranking strategy (health
tier), **not** the ML/bandit router ADR-0012 explicitly defers.

## Remaining sequence

Phase 4's planned slices are complete. Nothing in the plan's original sequence remains.

**Explicitly deferred beyond Phase 4 under GP-1 (no consumer today):** Enterprise Memory, Benchmark
Service, semantic/vector cache tier (ADR-0018 scoped it out), eventing backbone (ADR-0005 accepted,
unimplemented), rate limiting, OPA, durable `provider_health` cross-replica snapshots (the
in-process circuit breaker is authoritative; sharing state across replicas needs ADR-0005's
eventing backbone), per-org `routing_policy` strategy configuration (no management API yet), and the
ML/bandit routing strategy (ADR-0012 defers it to preserve explainability). Each is a recorded
deferral, not an omission.

## Known contradictions and debt (carried forward)

- **ADR-0016's "Observed evidence" table is stale** — still lists Tool Registry, MCP Gateway and
  RBAC as `_pending_`. The section says it is "recorded after each Foundation milestone", but the
  file has been treated as byte-frozen all phase. **Do not edit the frozen ADR**;
  `Architecture_Evidence_Log.md` is the authoritative substitute. Resolve by companion ADR if ever
  needed.
- **ADR-0013 is still `Proposed`** although the schema change it covers shipped long ago.
- **ADR-0005 (eventing) is Accepted but unimplemented**; Redis runs in `docker-compose.dev.yml` and
  nothing connects to it.
- **ADR-0003 (provider abstraction) has met a real SDK as of Slice 19** —
  `OpenAiCompatibleProviderClient` (httpx) is wired when a provider connection is configured;
  `InMemoryProviderClient` remains the default when none is.
- **Three of five routing agents are stubs** (`PolicyAgent`, `CostAgent`, `PlannerAgent` is real
  heuristic). Slice 20 made `HealthAgent` real (it reads live circuit-breaker state), and Slice 21
  made `ProviderAgent` real (it selects via a `RoutingStrategy` that ranks by circuit health).
  `PolicyAgent` and `CostAgent` remain stubs — real policy admission lives in the `PolicyStage`
  (Slice 13), and per-candidate cost ranking awaits a real cost signal (GP-1).
- **A routable provider configured without a price fails closed as a generic 500** — the served
  path now reaches `UnknownPriceError` (Slice 8's invariant: a config defect is never a budget
  outcome), and no spend is booked, but mapping it to a tailored fail-closed 5xx is deferred
  because it would require either importing accounting into delivery (contract-forbidden) or
  reversing the Slice-8 invariant. New in Slice 19; recorded rather than hidden.
- **~26 of 45 schema tables remain unused** (Slice 18 activated `role`/`permission`/
  `role_permission`/`membership`/`audit_event` + `audit_chain_head`; Slice 19 activated
  `provider`/`model`/`price_table`).
- **`PipelineStage.after_response` / `on_error` are still executed by nothing** — `RequestPipeline`
  runs only `before_request`. The oldest open piece of the Tier-1 stage protocol.
- **Resolved in Slice 18:** the default PostgreSQL deployment can now authorize a request (durable
  RBAC), API keys are verifiable (`CompositeAuthenticator` + the ADR-0019 bootstrap), and
  authentication decisions are written to a durable, hash-chained, per-tenant `audit_event` log.
  A non-PostgreSQL deployment keeps the fail-closed `NullPermissionResolver` and JWT-only
  authenticator.

## Working agreements

- Two slices per implementation prompt; the first must be fully green before the second begins.
- Every new structural guard is violated, verified present, observed failing, restored, verified
  restored, and observed passing before it is trusted.
- Nothing is weakened: tests, coverage, mypy strictness, import-linter contracts, guards,
  skipped-test enforcement, RLS/runtime-role checks, three-state validation, validation parity.
