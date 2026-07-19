# ADR-0004: Reserve/Commit cost-accounting model

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, Database Architect, SRE
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** Reserve vs Commit cost accounting

## Context & problem
Budgets must be **hard-enforced** — a request that would exceed a tenant/team/key budget is rejected
*before* provider cost is incurred (FR-061, AC-US-040), with **most-restrictive-wins** across the
hierarchy (FR-062) and **correct under concurrency** (FR-063). This is Phase 1's highest-scored
technical risk (RISK-T03, score 15: budget race → overspend). Simultaneously, metering must add
**zero blocking time** on the hot path (NFR-P06) and the budget check itself must be ≤5 ms (NFR-P05).
The tension: enforcement must be *synchronous and accurate*, but the true cost of a request is only
known *after* the provider responds (tokens are not known up front, especially for streaming).

## Decision drivers
- FR-060..063 (hierarchical budgets, hard stop, most-restrictive-wins, atomic under concurrency),
  FR-066..069 (alerts, soft/hard, overrides, resets), FR-070..075 (metering & cost accuracy).
- NFR-P05 (≤5 ms budget check), NFR-P06 (metering non-blocking), NFR-S05 (≥10k usage records/s),
  SM-P06 (zero overspend), SM-T07 (cost accuracy ≤2%).
- RISK-T03 (overspend race), RISK-T06 (metering inaccuracy).

## Options considered
### Option A — Post-hoc accounting only (record actual cost after the call, check budget from a running total)
- **Pros:** Simplest; always uses true cost.
- **Cons:** Between check and record, many concurrent requests can each pass the check and collectively
  blow the budget (classic race). Fails FR-063/RISK-T03. Rejected.

### Option B — Synchronous double-entry ledger transaction on the hot path (compute cost, write ledger, check, all in one DB transaction per request)
- **Pros:** Strong consistency.
- **Cons:** Puts a serialized DB write on every request → contention hotspots on popular tenants;
  can't meet NFR-P05/NFR-P06 at NFR-S01 throughput; true cost still unknown pre-call. Rejected as the
  hot-path mechanism.

### Option C — **Reserve → Commit/Release** (two-phase) with atomic reservation in Redis + durable ledger in PostgreSQL
1. **Reserve (sync, pre-call):** estimate the request's max cost (from `max_tokens`, model price, prompt
   size). Atomically decrement available budget at the **most-restrictive** level via a Redis Lua
   script (single-round-trip, atomic across concurrent requests). If insufficient → reject
   `budget_exceeded` (fail closed) before any provider call.
2. **Call provider.**
3. **Commit (async, post-call):** on completion, compute **actual** cost from returned usage; write the
   authoritative **double-entry usage/ledger record** to PostgreSQL (system of record, FR-073) via the
   event pipeline ([ADR-0005](0005-eventing-backbone.md)); **reconcile** the Redis reservation to
   actual (refund the estimate−actual difference, or debit the overage).
4. **Release:** on failure/timeout, release the full reservation.
- **Pros:** Enforcement is atomic and ≤5 ms (Redis Lua, no cross-service lock) → satisfies FR-063,
  NFR-P05, kills RISK-T03; metering/ledger write is async → satisfies NFR-P06, NFR-S05; PostgreSQL
  ledger remains the accurate, auditable source of truth (FR-073, SM-T07); estimate is conservative so
  we never under-reserve.
- **Cons:** Two accounting surfaces (fast Redis counters + durable ledger) require periodic
  **reconciliation**; over-estimation can transiently under-utilize a near-full budget (acceptable,
  fail-safe direction).

## Decision
Adopt **Option C — Reserve/Commit**. Reservations are **atomic Redis Lua** operations against
per-scope budget counters evaluated **most-restrictive-first** (key → team → tenant); a failure at any
level rejects the request (fail closed, [ADR-0009](0009-fail-open-fail-closed-matrix.md)). The
**PostgreSQL ledger** (append-only, double-entry) is the system of record, written asynchronously from
provider-usage events. A scheduled **reconciler** rebuilds/repairs Redis counters from the ledger
(and at period reset, FR-069), bounding drift. Estimation uses `max_tokens`×price as an upper bound;
streaming reserves on `max_tokens` and commits on final usage. Soft limits warn (event/alert), hard
limits block (FR-067); overrides are time-boxed and audited (FR-068).

If Redis is unavailable, budget enforcement **fails closed** for hard-limited scopes (reject) per
ADR-0009 — we never silently allow unbounded spend.

## Consequences
- **Positive:** Correct hard enforcement under concurrency with a ≤5 ms hot-path cost; accurate,
  auditable ledger without blocking; scales to target RPS/record rates.
- **Negative:** Reconciliation job is now a required component; transient under-utilization near budget
  ceilings; Redis becomes enforcement-critical (addressed by HA Redis, [ADR-0010](0010-multi-region-strategy.md), and fail-closed policy).
- **Follow-ups:** Phase 3 models `budget`, `reservation`, `usage_ledger`; Phase 5/7 implements the Lua
  scripts and reconciler; Phase 13 load-tests the concurrency race explicitly (AC-US-040).

## Requirements satisfied
- Functional: FR-060, FR-061, FR-062, FR-063, FR-066, FR-067, FR-068, FR-069, FR-070, FR-071, FR-073.
- Non-functional: NFR-P05, NFR-P06, NFR-S05, NFR-A04 (fail-closed under dependency loss).

## Review notes
Revisit the estimation model if reconciliation drift exceeds tolerance under real traffic, or if a
provider stops returning reliable usage (would require a token-counting estimator per model).
