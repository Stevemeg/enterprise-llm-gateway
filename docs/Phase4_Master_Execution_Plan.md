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

## Remaining sequence

Ordering principle: **cross-cutting operational foundations before capabilities that depend on
trustworthy runtime evidence** (GP-1 — architecture evolves through evidence, and evidence requires
instrumentation).

| # | Milestone | Type | Depends on | Rationale |
|---|---|---|---|---|
| 18 | RBAC Durable Storage + Hash-Chained Audit Sink | Capability | 17 | `role`/`permission`/`role_permission` and `audit_event` tables exist and are unused; ADR-0009 mandates the audit sink. **Blocking:** the endpoint shipped in Slice 17 denies every request until permissions have storage, and API-key credentials cannot be verified without a request-scoped `ApiKeyRepository` |
| 19 | Real Provider Adapter + Durable Catalog/Pricing | Capability | 17 | Realizes ADR-0003; `provider`/`model`/`price_table` unused, catalog and pricing are empty in-memory stubs |
| 20 | Provider Health & Circuit Breaking | Capability | 16, 19 | `HealthAgent` is a stub; `provider_health` table unused. Needs metrics and a real provider to have health |
| 21 *(conditional)* | Adaptive Routing | Capability | 16, 20 | **Only if** 16 + 20 produce evidence justifying it (ADR-0016 names it the legitimate consumer of `PlannerDecision`'s deferred fields) |

**Explicitly deferred beyond Phase 4 under GP-1 (no consumer today):** Enterprise Memory, Benchmark
Service, semantic/vector cache tier (ADR-0018 scoped it out), eventing backbone (ADR-0005 accepted,
unimplemented), rate limiting, OPA. Each is a recorded deferral, not an omission.

## Known contradictions and debt (carried forward)

- **ADR-0016's "Observed evidence" table is stale** — still lists Tool Registry, MCP Gateway and
  RBAC as `_pending_`. The section says it is "recorded after each Foundation milestone", but the
  file has been treated as byte-frozen all phase. **Do not edit the frozen ADR**;
  `Architecture_Evidence_Log.md` is the authoritative substitute. Resolve by companion ADR if ever
  needed.
- **ADR-0013 is still `Proposed`** although the schema change it covers shipped long ago.
- **ADR-0005 (eventing) is Accepted but unimplemented**; Redis runs in `docker-compose.dev.yml` and
  nothing connects to it.
- **ADR-0003 (provider abstraction) has never met a real SDK** — `InMemoryProviderClient` only.
- **Four of five routing agents are stubs** (`PolicyAgent`, `CostAgent`, `HealthAgent`,
  `ProviderAgent`); only `PlannerAgent` is real.
- **31 of 45 schema tables are unused.**
- **The default deployment denies every request** — correct fail-closed behaviour, but no storage
  backs the permissions that would allow one until Slice 18.
- **`PipelineStage.after_response` / `on_error` are still executed by nothing** — `RequestPipeline`
  runs only `before_request`. The oldest open piece of the Tier-1 stage protocol.
- **Only JWT bearer credentials can be verified** (Slice 17). API keys fail closed until Slice 18
  supplies the request-scoped repository `CompositeAuthenticator` needs.

## Working agreements

- Two slices per implementation prompt; the first must be fully green before the second begins.
- Every new structural guard is violated, verified present, observed failing, restored, verified
  restored, and observed passing before it is trusted.
- Nothing is weakened: tests, coverage, mypy strictness, import-linter contracts, guards,
  skipped-test enforcement, RLS/runtime-role checks, three-state validation, validation parity.
