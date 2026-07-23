# ADR-0018: Exact-match response caching and process-local request deduplication

- **Status:** Accepted
- **Date:** 2026-07-23
- **Deciders:** Principal Architect, Database Architect
- **Phase:** 4 — Enterprise AI OS (Slice 10)
- **Affects:** ADR-0006 (scopes, does not reverse, its two-tier exact+semantic decision). Reuses
  `semantic_cache_entry` (no new migration). Does not touch ADR-0016 (frozen) or any Tier-1 seam.

## Context & problem

Slice 10's goal is caching and request deduplication that cannot bypass authorization, routing
ownership, provider execution semantics, budget enforcement, tenant isolation, or accounting
correctness. ADR-0006 already decided a cache architecture: a two-tier design - Redis exact-match
in front of a `pgvector` semantic-similarity tier, both tenant-scoped, populated asynchronously via
the event bus. Investigation for this slice found the same situation ADR-0017 found for Redis-based
budget reservation: **no Redis client, connection pool, embedding pipeline, `pgvector` query, or
event-bus consumer exists anywhere in this codebase.** `redis` is a declared dependency used by
nothing; `docker-compose.dev.yml` provisions a Redis container nothing connects to; the `embedding`
table (`0001_initial.sql`) has no writer. Building any of that now, for a milestone with no
similarity-threshold requirement, no false-positive-rate tooling, and no active consumer, would be
exactly the speculative infrastructure Rule 5/GP-1 warn against - the same finding ADR-0017 made
about ADR-0004's Redis Lua mechanism, one layer over.

Unlike ADR-0017's finding about the `budget`/`reservation` tables, however, the *exact-match* half
of ADR-0006's schema turned out to need no narrower replacement. `semantic_cache_entry`
(`0001_initial.sql`) already carries `organization_id uuid NOT NULL`, `request_hash bytea NOT NULL`,
`response jsonb NOT NULL`, `expires_at timestamptz` - exactly what a tenant-scoped, TTL-expiring,
exact-match cache needs - with `project_id`, `model_id`, `embedding_id` and `prompt_fingerprint` all
nullable, so leaving them unpopulated fabricates nothing and violates nothing (contrast Slice 9's
`reservation.request_id uuid NOT NULL`, which could not safely hold a `str` `correlation_id` at
all). The table already has RLS `ENABLE`+`FORCE` with the NULLIF-safe tenant policy every tenant
table shares, and `app_rw` already holds full DML on it - no migration was required for this slice.

A second, logically separate question this slice had to settle explicitly: is "caching" the same
concept as "deduplication"? They are not. A cache entry answers "have we ever produced this exact
response before" - content-identity, meant to persist and be reused by *unrelated* future requests.
Deduplication answers "is this exact logical request already running right now" -
correlation-identity, meant to be transient and reached only by genuine concurrent duplicates of the
*same* caller-supplied `correlation_id`. Conflating them (e.g. keying a cache on `correlation_id`,
or treating two different correlation ids with identical content as "the same request") would either
make caching worthless (a permanent miss) or silently collapse two logically separate requests -
across a tenant boundary if the two correlation ids belonged to different organizations.

## Decision drivers

- ADR-0006 (two-tier cache is the *decided* target architecture; only the tier/mechanism actually
  built this milestone is at issue).
- ADR-0016 Rule 5 (no speculative infrastructure without an active consumer) and GP-2 (a milestone
  that would bend an Accepted decision stops and writes a superseding/companion ADR rather than
  reinterpreting it in place) - the same posture ADR-0017 already established for ADR-0004.
- ADR-0002/0014 (tenant isolation via RLS, least-privilege `app_rw` runtime role).
- Rule 3 (cache identity and deduplication identity are different facts; a shared key would let
  them silently disagree).

## Options considered

### Option A - Build ADR-0006's full two-tier cache now (Redis exact + pgvector semantic)
- **Pros:** Matches the original decision exactly; captures near-duplicate savings the semantic
  tier targets (SM-P01/P02).
- **Cons:** No Redis client, embedding pipeline, or event-bus consumer exists in this codebase;
  building all three for a milestone with no similarity-threshold, false-positive-rate, or
  hit-rate-tuning requirement is speculative infrastructure with no failing test demanding it, and
  a wrong similarity threshold risks serving a wrong answer (RISK-T02) with no evidence yet of what
  threshold this system needs. Rejected for this milestone.

### Option B - PostgreSQL-backed exact-match cache against `semantic_cache_entry`, no semantic tier - **chosen**
A single tenant-scoped table lookup/upsert (`get`/`put`) against the pre-existing, already
RLS-protected `semantic_cache_entry` table, keyed by a deterministic SHA-256 digest of
`(organization_id, provider, model, canonical_payload)`. No embedding, no similarity threshold, no
new datastore. "Semantic-safe" here means *equivalent execution semantics* - an exact match on every
field that could affect the response, including any randomness/temperature setting a caller sent -
never fuzzy nearest-neighbour prompt matching.
- **Pros:** Zero new infrastructure; zero new migration (the existing table's shape already fits);
  correctly tenant-scoped (RLS, proven against real Postgres); no false-positive risk category to
  reason about, because there is no similarity threshold to get wrong.
- **Cons:** Does not capture near-duplicate savings a semantic tier would (two prompts differing by
  one character are two different cache entries). Not sub-millisecond the way an in-process/Redis
  exact tier would be at very high QPS - a Postgres round-trip per lookup, an honest, documented
  limitation, not a claim of Redis-tier latency.

### Option C - A process-local (in-process dict) exact-match cache only, no persistence
- **Pros:** Trivial, fastest possible hit path.
- **Cons:** Every gateway replica keeps an independent cache with no shared benefit across
  processes/restarts; still needed as the Rule-4 second implementation, but insufficient as the
  *only* implementation given a real database was already available and already shaped correctly.
  Adopted as the in-memory fallback, not the primary mechanism.

## Decision

Adopt **Option B** for persistent caching: `SqlResponseCache` reads/writes `semantic_cache_entry`
via a `ResponseCachePort`, tenant-bound through the same `AsyncUnitOfWork`/RLS mechanism every other
tenant-scoped adapter in this codebase uses. `InMemoryResponseCache` (Option C) is wired for
non-Postgres profiles, satisfying Rule 4's second-implementation requirement and exercising
`InferenceCoordinator` without a database, but - like `InMemoryBudgetLedger` before it - proves
nothing about RLS or durability.

Cache identity is computed by `compute_cache_key(organization_id, provider, model, payload)`:
canonical JSON (sorted keys) over the entire request payload, SHA-256 digested, with tenant,
provider and model baked into the digest itself (defence in depth beyond RLS/query filters -
`SqlResponseCache`'s own integration tests prove RLS still isolates tenants even for a deliberately
colliding raw key, independent of this defence). `correlation_id` is never part of this identity.

Deduplication is a separate, process-local `RequestDeduplicator`: an `asyncio.Task`-based
single-flight coalescer keyed on `(organization_id, correlation_id)`, used only to wrap the *miss*
path (a hit is a pure read with no side effects, so nothing needs coalescing there). It gives no
cross-process guarantee - two gateway replicas receiving the same `correlation_id` at the same
moment could each call the provider once - a gap this milestone does not close, matching ADR-0017's
own precedent of building the process/single-instance-scoped mechanism this milestone can prove and
explicitly deferring the distributed one until evidence demands it (GP-1). `SqlBudgetLedger`'s
durable, cross-process idempotency (Slice 9) remains the backstop against double-*charging* even in
that gap; it does not, by itself, prevent a double provider *call*, which is exactly the narrower
problem this slice's deduplicator closes within one process.

A cache hit is never treated as provider execution: it creates no `ProviderUsage`, incurs no cost,
and never reserves or settles budget, because nothing was spent. `InferenceCoordinator` is the new,
single composition point proving the full path end to end (cache check → dedup-wrapped
reserve/execute/settle) - it decides nothing itself, delegating routing (already decided),
budget-gating (`ReservationService`, unchanged) and provider invocation (`ProviderExecutor`,
unchanged) exactly as before.

## Consequences

- **Positive:** Real cache/dedup with no new infrastructure dependency; zero new migration;
  tenant-isolated by RLS like every other table; deterministic, reproducible cache identity;
  explicit, tested separation between cache identity and deduplication identity.
- **Negative / obligations:** No near-duplicate ("semantic similarity") savings - only literal exact
  matches hit. No cross-process deduplication guarantee - documented, not hidden. A Postgres cache
  lookup is not Redis-tier latency at very high QPS against the same organization.
- **Explicitly deferred:** `pgvector`-based semantic similarity caching (ADR-0006's Tier 2); Redis
  exact-match tier for sub-millisecond latency at scale; the embedding pipeline (ADR-0007);
  distributed (Redis- or Postgres-advisory-lock-based) cross-process deduplication; explicit
  purge/invalidation beyond TTL expiry; `hit_count`/`prompt_fingerprint` population.

## Requirements satisfied

Upholds ADR-0002 (tenant isolation), ADR-0014 (runtime role is `app_rw`, never bypasses RLS).
Advances ADR-0006's FR-050 (exact-match caching) and FR-057 (tenant isolation, no cross-tenant
serving) for the current milestone's scale; does not yet claim FR-054-056/058 (semantic tier,
similarity scoring, model/version-driven invalidation) or NFR-P02 (Redis-tier exact-hit latency).

## Review notes

Revisit when a measured near-duplicate miss rate, or a concrete latency requirement Postgres cannot
meet, demonstrates a need for the semantic tier or a Redis exact tier - either is the evidence
(GP-1) that would move this project toward ADR-0006's original two-tier mechanism. Revisit
distributed deduplication when running more than one gateway replica is an actual deployment shape,
not a hypothetical one.
