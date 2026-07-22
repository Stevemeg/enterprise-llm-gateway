# ADR-0017: PostgreSQL-transactional reserve/commit as the interim hard-budget mechanism

- **Status:** Accepted
- **Date:** 2026-07-22
- **Deciders:** Principal Architect, Database Architect
- **Phase:** 4 — Enterprise AI OS (Slice 9)
- **Affects:** ADR-0004 (scopes, does not reverse, its Option-B rejection); adds `org_budget`,
  `budget_reservation`, `cost_ledger` tables. Does not touch ADR-0016 (frozen) or any Tier-1 seam.

## Context & problem

Slice 8 built deterministic cost accounting (`CostAccountant`, `BudgetEnforcer`) with an explicitly
documented limitation: `snapshot()` (read) and `record()` (write) are separate calls, so nothing
prevents two concurrent requests from each reading "budget available" and both proceeding — and,
more fundamentally, `BudgetEnforcer.evaluate()` runs *after* `ProviderExecutor` has already called
the provider. By the time a hard limit is "enforced," the spend already happened. Settlement alone
cannot prevent a request's own provider call from exceeding budget — only a check *before* the call
(reservation) can gate it.

ADR-0004 already decided how hard enforcement should work: **atomic Redis Lua reserve/commit**,
explicitly rejecting "Option B" (a synchronous ledger transaction on the hot path, i.e. Postgres
row-locking) because it "puts a serialized DB write on every request → contention hotspots... can't
meet NFR-P05/NFR-P06 at NFR-S01 throughput." That rejection is a **performance** finding at
production SaaS scale (≤5ms budget checks, ≥10k usage records/s, hundreds of tenants) — it is not a
**correctness** finding. Nothing in ADR-0004 disputes that a single ACID transaction with row-level
locking gives correct, atomic, race-free reserve/commit; it says that mechanism will not be fast
enough once the system reaches that scale.

This project has not reached that scale. No load test exists yet (ADR-0004 itself defers that to
"Phase 13"). No Redis client, Lua script, or reconciler exists anywhere in this codebase — Redis is
provisioned in `docker-compose.dev.yml` and used by nothing. Introducing it now, for a milestone
that has not been asked to meet NFR-P05/NFR-S05 and has no consumer for a reconciliation job, would
be exactly the speculative-infrastructure Rule 5 (ADR-0016) warns against, one layer down from
protocols.

Separately: `docs/Schema.sql` and `backend/migrations/sql/0001_initial.sql` **already define** a
fuller `budget` / `reservation` / `usage_ledger` schema (hierarchical org/project/api_key scope,
period rollover, FK links to a `provider`/`model` catalog, a `uuid NOT NULL request_id`, double-entry
ledger rows). Investigation for this slice found that schema was never populated or read by any
application code, and does not fit what actually exists today:

- No code creates `provider`/`model`/`price_table` rows — `InMemoryProviderCatalog` and
  `StaticPriceTable` (Slice 6/8) are in-memory, string-keyed, with no DB identity to join against.
- `BudgetPort`/`BudgetEnforcer` (Slice 8) are organization-scoped only — nothing consumes
  project/api_key budget scope or period rollover.
- `InferenceRequest.correlation_id` (Slice 7) is an arbitrary caller-supplied `str`, not a UUID.
  `reservation.request_id` and `usage_ledger.request_id` are typed `uuid NOT NULL` — inserting a
  non-UUID correlation id into that column fails outright, and coercing/validating every
  correlation id into UUID shape to fit the column would be an undocumented, silently-agreed
  convention (exactly what Rule 3 exists to avoid).
- `reservation.request_id` carries a bare `UNIQUE` constraint (globally unique), not scoped to
  `organization_id`. A caller-supplied identifier has no reason to be globally unique across
  tenants; two different organizations' clients could legitimately reuse the same string.

Populating the illustrative schema's unused dimensions now (fabricated catalog rows, scope/period
values with no reader) would itself violate Rule 5. Reusing its `request_id`/`reservation` naming
would silently misrepresent a `str` as a `uuid`-shaped identity.

## Decision drivers

- ADR-0004 (Reserve/Commit is the *decided* enforcement shape; only the mechanism is at issue here).
- ADR-0016 Rule 5 (no speculative fields/infrastructure without an active consumer) and GP-2 (a
  milestone that would bend an existing Accepted decision stops and writes a superseding/companion
  ADR rather than reinterpreting it in place).
- ADR-0002/0014 (tenant isolation via RLS, least-privilege `app_rw` runtime role).
- The user-facing requirement driving this slice: genuine hard-budget enforcement (reservation
  before provider execution), durable and race-free, without contaminating Tier-1.

## Options considered

### Option A — Implement ADR-0004's Redis Lua reserve/commit now
- **Pros:** Matches the original decision exactly; meets NFR-P05/NFR-S05 from day one.
- **Cons:** No Redis client, connection pool, or Lua-script infrastructure exists in this codebase;
  building it now for a milestone with no throughput requirement and no reconciler consumer is
  speculative infrastructure with no failing test demanding it. Rejected for this milestone.

### Option B — Reuse the Phase-1 illustrative `budget`/`reservation`/`usage_ledger` tables as-is
- **Pros:** Zero new tables; matches the originally documented schema.
- **Cons:** Requires either fabricating unused provider/model/scope/period data (Rule 5 violation)
  or leaving NOT NULL columns unpopulated by contract-breaking defaults; `request_id uuid` cannot
  safely hold an arbitrary `correlation_id: str`; the existing `UNIQUE (request_id)` constraint is
  global, not tenant-scoped, which is the wrong identity for a caller-supplied id. Rejected.

### Option C — PostgreSQL-transactional reserve/commit against new, narrower tables — **chosen**
A single ACID transaction per operation (`reserve`, `settle`, `release`), using a conditional
`UPDATE ... WHERE (limit - spent - reserved) >= :cost` against a per-organization budget row as the
atomic primitive — the same indivisible read-check-write property ADR-0004 wanted from a Lua
script, expressed as one SQL statement inside one Postgres transaction instead. New tables
(`org_budget`, `budget_reservation`, `cost_ledger`) are scoped to exactly what `BudgetPort`/
`PricingPort`/`CostAccountant` already model (organization-level, no catalog FK, `correlation_id`
typed `text`, uniqueness on `(organization_id, correlation_id)`), avoiding both Rule-5 speculative
population and the `uuid`/`str` mismatch.
- **Pros:** Genuinely atomic and race-free (proven against real PostgreSQL, not asserted); durable;
  no new infrastructure; correctly tenant-scoped identity; capability-local (no Tier-1 change).
- **Cons:** Does not meet ADR-0004's original ≤5ms / ≥10k-records/s hot-path targets at full SaaS
  scale — a single row-locked `UPDATE` on a hot budget row becomes a serialization point under very
  high concurrent QPS *against the same organization*. This is an honest, documented limitation,
  not a claim of production-scale performance.

## Decision

Adopt **Option C** for this milestone. `org_budget`, `budget_reservation`, and `cost_ledger`
(migration `0006_budget_ledger`) are new, narrower, RLS-protected tables. Budget sufficiency
across *different* reservations is atomic because a single `UPDATE ... WHERE ... RETURNING` is
Postgres's own indivisible primitive — no atomicity is claimed there that the database does not
itself provide. Two further races exist beneath that primitive and are closed with explicit,
minimal locking rather than left implicit: `settle`/`release` take `SELECT ... FOR UPDATE` on the
reservation row before branching on its status (without it, two concurrent calls for the same
`correlation_id` could each read a pre-commit status and both apply their own budget update); and
`reserve` opens with a transaction-scoped `pg_advisory_xact_lock` keyed on
`(organization_id, correlation_id)` (there is no row to lock for a brand-new id, so a genuine
concurrent duplicate `reserve` could otherwise be wrongly evaluated against the winner's
already-committed state and denied). Both were found during pre-commit review of this ADR against
the implementation, fixed, and proven by dedicated concurrency tests — see
Architecture_Evidence_Log.md. `cost_ledger` is append-only (INSERT-only grant for `app_rw`,
mirroring `audit_event`/`usage_ledger`'s existing convention). Idempotency is enforced by
`UNIQUE (organization_id, correlation_id)` — a database-participating constraint, not merely an
in-process dictionary key (the limitation Slice 8's `InMemoryBudgetStore` explicitly documented).

**This does not reverse ADR-0004.** ADR-0004's Redis Lua mechanism remains the target for the
production-scale, multi-region, NFR-P05/NFR-S05-bound deployment; that follow-on work is
unchanged and undertaken when a load-testing milestone (or a concrete latency/throughput
requirement) makes Postgres-only reservation insufficient — evidence, per GP-1, not a
hypothetical future need. Until then, Postgres-transactional reserve/commit is the actual,
verified, hard-enforcement mechanism: reservation happens *before* `ProviderExecutor` is called,
and a rejected reservation means the provider is never invoked.

## Consequences

- **Positive:** Real hard enforcement (reservation gates the call, not just after-the-fact
  classification); durable across restarts; tenant-isolated by RLS like every other table;
  idempotent by a real database constraint; zero new infrastructure dependency.
- **Negative / obligations:** Not yet meeting ADR-0004's original latency/throughput targets at
  full scale (documented, not hidden); a reservation abandoned mid-flight (process crash between
  provider execution and settlement) holds its budget reservation until the same `correlation_id`
  is retried — no expiry-driven reconciler exists yet (mirrors ADR-0004's own deferred
  "reconciler" follow-up, now inherited by this narrower mechanism too).
- **Explicitly deferred:** Redis Lua reserve/commit (ADR-0004's original mechanism, for when scale
  demands it); a reservation-expiry reconciliation sweep; project/api_key-scoped budgets; a
  provider/model pricing catalog in the database (pricing remains `StaticPriceTable`, unchanged).

## Requirements satisfied

Upholds ADR-0002 (tenant isolation), ADR-0009 row 1 (budget-store outage fails closed), ADR-0014
(runtime role is `app_rw`, never bypasses RLS). Advances ADR-0004's FR-061/FR-063 (hard stop,
atomic under concurrency) for the current milestone's scale; does not yet claim NFR-P05/NFR-S05.

## Review notes

Revisit when a load-testing or multi-region milestone demonstrates row-lock contention on a hot
budget row, or when a reconciliation consumer is actually needed — either is the evidence (GP-1)
that would move this project to ADR-0004's original Redis Lua mechanism.
