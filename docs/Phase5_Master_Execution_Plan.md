# Phase 5 — Master Execution Plan (Proposed)

**Status:** **M1-M4 delivered** (M1/M2 2026-07-26; M3/M4 2026-07-27). **M5 evaluated and NOT
JUSTIFIED** — Phase 5 closes without it; see the evidence log's M5 gate section.
**Created:** 2026-07-25 · **Baseline:** `main` @ `d5d3bc2` · tag `v1.21.0-phase4-slices20-21`
**Implementation baseline for M1/M2:** `main` @ `863ad64` · tag `v1.21.1-phase4-closeout`
**Subordinate to** accepted ADRs and source. ADR-0016 remains **frozen**; nothing here amends it.
This plan is *sequencing intent*, derived from [`Phase4_Final_Architecture_Review.md`](Phase4_Final_Architecture_Review.md).

## Theme and why

**Phase 5 = Production Hardening of the serving runtime, evolving into a distributed runtime.**
"Make one node correct and credible, then make N nodes correct." Every milestone resolves a gap
proven in the Phase-4 review, not a hypothetical.

### Why not the alternatives first
- **E — More AIOS capabilities (Memory, Benchmark, OPA).** Every remaining AIOS capability is a
  GP-1 deferral with no consumer. The product cannot yet stream or safely call a real provider;
  adding memory before that is the speculative-capability trap ADR-0016 exists to prevent.
- **C — Distributed runtime *first*.** Horizontal scaling is meaningless while a single node can't
  stream, defaults to a fake client, and leaks reservations. Distributing incorrect single-node
  semantics only distributes the bugs. C is therefore the *later* half of Phase 5 (M4), not the
  start.
- **D — Operational platform (deploy/runbooks/DR) first.** Premature: a runbook written now
  documents a runtime about to change under M1–M3.
- **F — Pure debt closure as its own phase.** The debt (vacuous `after_response`/`on_error`, dead
  `BudgetEnforcer`, latent `selected_model`) is real but small; it is folded into the milestone
  that already touches that code (M2), not elevated to a phase.
- **A — Provider integration first.** Real provider integration already shipped (Slice 19). What
  remains — streaming, cancellation — *is* hardening, and lives in M1/M2.

### Milestone sequence (ordered by architectural dependency)

| # | Milestone | Resolves | Depends on | Status |
|---|---|---|---|---|
| P5-M1 | Streaming inference | Review §4.1 (BLOCKER) | — | **Delivered** |
| P5-M2 | Serving correctness & debt closure | §4.2, §4.3, §4.6 + D1/D2/D3 | M1 | **Delivered — all 6 items resolved.** 4 in-milestone; 2 via [ADR-0020](adr/0020-narrowing-proven-vacuous-tier-1-surface.md), written as the GP-2 stop, then **accepted and applied** before publication |
| P5-M3 | Ingress protection | §4.5 (rate limit, size limits) | M2 | **Delivered.** Prediction CONFIRMED: a capability-owned `RateLimiterPort` + two middlewares, no Tier-1 diff, no ADR |
| P5-M4 | Distributed runtime state | §4.8 (cross-replica) + eventing | M1–M3 | **Delivered, prediction SPLIT.** Shared rate limiting on Redis behind the **unchanged** M3 port; the circuit breaker and deduplicator **FALSIFIED** it (sync port / no port) and stopped at a Rule-5 gate — [ADR-0021](adr/0021-distributed-runtime-state-scope.md) |
| P5-M5 *(conditional)* | Operational readiness | §4.7 (OTel), deploy, DR | M1–M4 | **NOT JUSTIFIED — not implemented.** Tracing has no second hop or replica to trace; manifests are out of scope; the migration story and config validation already exist; a DR runbook would document a deployment shape that does not exist |

---

## P5-M1 — Streaming inference · **DELIVERED**

> **Outcome.** Tier-1 byte-stable. The pre-registered prediction was **half falsified**: streaming
> is *not* an additive method on `ProviderClient` but a new capability-owned seam
> (`StreamingProviderClient`). The commit boundary is enforced by an import contract rather than a
> runtime flag. Pre-first-chunk *failover* is deferred with a reason (reflection retries the same
> provider, so it is not failover). Evaluation of streams is deferred. See the evidence log.


- **Objective.** Serve token-streamed responses end to end (provider → coordinator → HTTP), while
  preserving budget reservation, settlement, caching semantics and the circuit-breaker feed.
- **Evidence.** Review §4.1: non-streaming is a BLOCKER; the real adapter does one blocking POST.
- **Exact limitation resolved.** A client cannot receive incremental tokens; large completions
  block the request path for their full duration.
- **Components likely affected.** `ports/providers.py` (a streaming result shape), `ProviderClient`
  adapters, `ProviderExecutor`, `InferenceCoordinator` (settlement/cache after stream completes),
  `delivery/http/api/inference.py` (SSE/chunked), reflection interaction with a partial stream.
- **Seams consumed.** `ProviderClient`, `ResponseCachePort`, `ReservationService`, `CircuitBreaker`.
- **Tier-1 evolution expected?** **Possibly.** This is the phase's principal Rule-5 test: does
  representing a stream force a change to a Tier-1 contract, or can it be an additive port concept?
- **Security implications.** Streamed errors must not leak provider internals; a mid-stream failure
  must still release or settle correctly (no half-charged, un-released holds).
- **Persistence/migration.** None expected (cache stores the assembled response as today).
- **Required failure tests.** provider fails mid-stream → reservation released, no cache write;
  client disconnects mid-stream → provider call aborted, hold released; empty/malformed chunk →
  fail closed; cache write only on a *complete* successful stream.
- **Concurrency tests.** Two identical in-flight streaming requests coalesce or independently
  stream without cross-talk; per-request state isolation preserved.
- **Structural enforcement.** Reuse "delivery reaches inference only via InferenceService" and the
  execution⊥accounting contract; a new guard only if streaming introduces a genuinely unenforced
  boundary.
- **Acceptance.** Streamed happy path; settlement equals the non-streamed cost for identical usage;
  all failure tests green; Gate 1 + Gate 2 exit 0; no Tier-1 diff unless Rule 5 fires and is
  approved.
- **Out of scope.** Streaming *cache replay*, partial-response caching, tool/function-call streaming.
- **Pre-registered experiment.**
  - *Prediction:* streaming is expressible as an **additive** streaming method/result on
    `ProviderClient` + a delivery change; the Tier-1 seams (`RoutingDecision`, `PipelineStage`) are
    untouched.
  - *Falsification:* if settlement/caching cannot be preserved without changing a Tier-1 contract
    (e.g. `RoutingDecision` or the pipeline seam), the prediction is falsified.
  - *Expected result:* Tier-1 byte-stable; one new capability-owned concept; failure tests prove
    reservation integrity under mid-stream failure.
  - *What would force an ADR:* a required change to any Tier-1 protocol, or a new persistent store
    for partial streams.

## P5-M2 — Serving correctness & debt closure · **DELIVERED (4 of 6; 2 deferred by governance)**

> **Outcome.** Fake-client default replaced with a fail-closed client; reservation reconciliation
> shipped **with no migration** (the schema already had `created_at` and an `expired` enum member);
> unpriced/unaccountable calls became a typed 503 instead of a generic 500; the dead Slice-8 budget
> layer was removed. Narrowing `PipelineStage` and removing `selected_model` are **Tier-1** changes,
> so the milestone stopped and wrote [ADR-0020](adr/0020-narrowing-proven-vacuous-tier-1-surface.md)
> per GP-2 rather than applying them unilaterally. That ADR was then **accepted** and the
> contraction applied, so the published state carries an explicit Tier-1 diff. See the evidence log.


- **Objective.** Close the correctness gaps that exist even on one node, and remove the vacuous
  architecture the review identified.
- **Evidence.** §4.2 (fake-client default), §4.3 (reservation leak), §4.6 (unpriced→500); D1/D2/D3.
- **Exact limitations resolved.** (a) production silently serving fabricated responses; (b) leaked
  budget holds on crash; (c) config defects surfacing as 500s; (d) three dead/over-built seams.
- **Components likely affected.** `container.py` (fail closed when catalog has providers but no
  connection; delete `BudgetEnforcer`/`BudgetPort` wiring); `ReservationService`/`BudgetLedgerPort`
  (expiry + reconciliation); `delivery/http/api/inference.py` (unpriced → tailored 5xx);
  `ports/pipeline.py` (narrow to `before_request` **or** wire a response consumer — decide with
  evidence); routing agents (`selected_model` populate-or-remove).
- **Seams consumed.** `BudgetLedgerPort`, `PricingPort`, `ProviderClient`, `PipelineStage`.
- **Tier-1 evolution expected?** **Narrowing only, and only if chosen:** removing
  `after_response`/`on_error` *reduces* the stage protocol. Treated as a deliberate, ADR-noted
  decision (the seam is invariant 5), not a silent edit.
- **Security implications.** Fail-closed provider wiring prevents fabricated-response disclosure;
  reservation reconciliation prevents budget-bypass via crash-looping.
- **Persistence/migration.** Reservation expiry may add a column/index (e.g. `expires_at`) and a
  reconciliation query — an append-only, RLS-respecting migration if so.
- **Required failure tests.** providers-seeded-but-no-connection → startup or request fails closed
  (never fabricates); reserved hold past expiry → reconciled/released, not double-spent; unpriced
  model → tailored non-500 fail-closed with no spend booked; deleting `BudgetEnforcer` breaks no
  serving path (regression proof).
- **Concurrency tests.** Reconciliation vs concurrent settle does not double-release (atomicity on
  Postgres).
- **Structural enforcement.** New guard candidate: "the composition root may not wire a fake
  provider client when a durable catalog is active." Reuse accounting/ledger contracts.
- **Acceptance.** All failure tests green; removed seams provably unreferenced; Gate 1 + Gate 2
  exit 0; docs updated to match.
- **Out of scope.** Distributed reservation coordination (M4).
- **Pre-registered experiment.**
  - *Prediction:* the fake-client default and the reservation leak are removable/closable **without
    any Tier-1 change**; the stage protocol can be honestly narrowed to `before_request`.
  - *Falsification:* if a real consumer for `after_response`/`on_error` emerges during the work
    (e.g. evaluation genuinely needs the response phase), narrowing is wrong and the seam is LIVE.
  - *Expected result:* three vacuous items resolved; two correctness bugs closed with failure tests;
    Tier-1 either byte-stable or deliberately, ADR-notedly narrowed.
  - *What would force an ADR:* narrowing invariant 5's protocol; a schema change for expiry.

## P5-M3 — Ingress protection

- **Objective.** Per-tenant ingress rate limiting and request-size limits at the delivery boundary,
  fail-closed and cardinality-bounded.
- **Evidence.** §4.5: no ingress limits today; a gateway without them is a cost/abuse hole.
- **Exact limitation resolved.** Unbounded request volume/size per tenant.
- **Components likely affected.** new delivery middleware + a `RateLimiterPort` (capability-owned),
  a first limiter implementation, metrics, `container.py` wiring.
- **Seams consumed.** delivery layer; identity from auth middleware (tenant is the limit key).
- **Tier-1 evolution expected?** No.
- **Security implications.** Fail-closed on limiter outage must be a deliberate decision (ADR-0009
  row alignment): a rate limiter that fails *open* is often correct for availability — this must be
  chosen with evidence, not defaulted.
- **Persistence/migration.** A single-node limiter needs none; a shared limiter needs a store —
  which ties into M4 (this is the second real consumer that can justify shared state / ADR-0005).
- **Required failure tests.** over-limit → 429 with no downstream execution; oversized body → 413
  before any provider call; limiter store unavailable → the chosen fail mode, tested explicitly.
- **Concurrency tests.** Burst of concurrent requests respects the limit within one node.
- **Structural enforcement.** import contract: the limiter reaches no capability; construction guard
  if a shared instance must be singular.
- **Acceptance.** Limits enforced pre-execution; Gate 1 + Gate 2 exit 0.
- **Out of scope.** Cross-node shared counters (M4) unless trivially satisfied here.
- **Pre-registered experiment.**
  - *Prediction:* a `RateLimiterPort` with a single-node implementation satisfies the requirement
    and needs no Tier-1 change; cross-node sharing is a *separate* consumer.
  - *Falsification:* if correctness demands cross-node counting from day one, the single-node
    implementation is insufficient and M3 must merge into M4.
  - *Expected result:* enforced per-tenant limits; fail mode chosen with a stated ADR-0009 rationale.
  - *What would force an ADR:* choosing fail-open, or requiring a shared store (→ eventing/ADR-0005).

## P5-M4 — Distributed runtime state

- **Objective.** Make the stateful runtime components correct across replicas: shared circuit-breaker
  health and cross-node deduplication, via the eventing backbone (ADR-0005) or a shared store.
- **Evidence.** §4.8: circuit breaker and deduplicator are in-process; multi-replica correctness is
  unproven. This milestone is the **first real consumer of ADR-0005**.
- **Exact limitation resolved.** On N nodes, provider health is learned N times and dedup coalesces
  nothing across nodes.
- **Components likely affected.** a durable/shared `CircuitBreaker` implementation, distributed
  dedup, `provider_health` snapshots (now with a reader *and* writer), ADR-0005 wiring (Redis is
  already in compose, unused).
- **Seams consumed.** `CircuitBreaker`, `RequestDeduplicator`, `BudgetLedgerPort` (already durable).
- **Tier-1 evolution expected?** No — the ports were designed for this substitution (one-line swap
  in the composition root, by design).
- **Security implications.** Shared state must remain tenant-isolated (`(org, provider)` keying);
  cross-replica audit fan-out must preserve the hash chain.
- **Persistence/migration.** `provider_health` gains a real reader+writer (satisfying the "no table
  without both" rule at last); possibly event tables.
- **Required failure tests.** node A opens a circuit → node B observes OPEN; dedup across two nodes
  coalesces a duplicate; eventing backbone down → degrade to per-node (documented), never crash.
- **Concurrency tests.** Concurrent observers across nodes converge on the same circuit state; no
  lost updates on the shared counter.
- **Structural enforcement.** Reuse the circuit-breaker construction + isolation contracts against
  the new implementation (prove the *old* guard still holds for the *new* subject).
- **Acceptance.** Multi-node integration test proves shared health + dedup; Gate 1 + Gate 2 exit 0.
- **Out of scope.** Multi-region (ADR-0010), globally-distributed reservation.
- **Pre-registered experiment.**
  - *Prediction:* ADR-0005's eventing (or a shared store) implements shared circuit/dedup **behind
    the existing ports with no Tier-1 change** — the Phase-4 seams were the right shape.
  - *Falsification:* if the `CircuitBreaker`/deduplicator ports cannot express distributed semantics
    without interface changes, the Phase-4 abstraction was wrong (the review's stated top risk
    realized).
  - *Expected result:* one-line composition-root swap; multi-node tests green; ports byte-stable.
  - *What would force an ADR:* implementing ADR-0005 itself is the ADR; any port change is a Rule-5
    stop.

## P5-M5 — Operational readiness *(conditional on M1–M4)*

- **Objective.** OpenTelemetry tracing, deployment manifests, migration-on-deploy story, config
  validation surfacing, and a disaster-recovery runbook.
- **Evidence.** §4.7 (no tracing) plus the review's "operationally pre-production" verdict.
- **Why conditional.** Only worth doing once the runtime semantics (M1–M4) are settled, so the
  runbook and traces describe the real system.
- **Tier-1 evolution expected?** No.
- **Pre-registered experiment.**
  - *Prediction:* tracing and ops tooling are additive and touch no application/domain contract.
  - *Falsification:* if instrumenting the request path requires threading trace context through a
    Tier-1 type, tracing is not purely cross-cutting.
  - *Expected result:* traces across pipeline→routing→execution; deployment reproducible; DR
    rehearsed.
  - *What would force an ADR:* a change to how identity/correlation is carried through the seams.

---

## Working agreements (carried from Phase 4)

- Milestones are sized by evidence, implemented one at a time, fully green before the next.
- Every new structural guard is violated → observed failing → restored → observed passing before
  trust.
- Nothing weakened: tests, coverage, mypy strictness, import-linter, guards, RLS/runtime-role,
  three-state validation, parity.
- A milestone that would bend a rule **stops** and writes a superseding ADR (GP-2).
- Write each milestone's PREDICTION/FALSIFICATION **before** implementation (evidence quality).
