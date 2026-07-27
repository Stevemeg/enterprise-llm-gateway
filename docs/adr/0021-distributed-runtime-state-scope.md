# ADR-0021: Distributed runtime state — what is shared now, and what stops at a Rule-5 gate

- **Status:** Accepted
- **Date:** 2026-07-27
- **Deciders:** Repository owner
- **Phase:** 5 — Milestone 4 (Distributed runtime state)
- **Affects:** Realizes part of [ADR-0005](0005-eventing-backbone.md) (first Redis consumer in this
  codebase) and `docs/API_Rate_Limiting.md` §4. Revisits the fail-mode decision Phase 5 M3 made for
  ingress rate limiting, on the evidence M3 pre-registered as the trigger for revisiting it. Does
  **not** touch [ADR-0016](0016-enterprise-ai-os-architecture.md) (frozen) or any Tier-1 seam.
  Does not reverse [ADR-0018](0018-exact-match-response-cache-and-request-deduplication.md).

## Context & problem

Phase 5 M4's objective is "make the stateful runtime components correct across replicas". The
Phase-4 review named the gap as the project's **biggest architectural risk remaining**: the runtime's
stateful components are single-process, and "if the first multi-replica deployment reveals those
seams are wrong, that is the rewrite ADR-0016 fought to prevent — relocated from the interfaces to
the runtime."

The milestone therefore carried a pre-registered experiment with an unusually sharp falsification
criterion:

> *Prediction:* a shared store implements shared circuit/dedup **behind the existing ports with no
> Tier-1 change** — the Phase-4 seams were the right shape.
> *Falsification:* if the `CircuitBreaker`/deduplicator ports cannot express distributed semantics
> without interface changes, the Phase-4 abstraction was wrong.
> *Expected result:* one-line composition-root swap; multi-node tests green; **ports byte-stable**.
> *What would force an ADR:* implementing ADR-0005 itself is the ADR; **any port change is a
> Rule-5 stop**.

After M3 there are **three** process-local runtime states, not two. This ADR records what the
experiment found for each, and what M4 consequently does and does not build.

### Correction to a claim two documents repeat

ADR-0018 states that "`redis` is a declared dependency used by nothing". That was true when it was
written; it is **not true of the tree this ADR is written against.** `redis` appears in
`backend/pyproject.toml` only as a *forbidden module* in the "application is framework-free"
import-linter contract. It is absent from `[project.dependencies]` and was not installed. Adopting
Redis here is therefore adding a **new production dependency**, not activating a dormant one, and it
is weighed below on those terms.

## The experiment, per state

| Process-local state | Seam it sits behind | Can a shared implementation slot in with the seam unchanged? |
|---|---|---|
| **Rate limiter** (M3) | `RateLimiterPort` — `async def acquire(*, organization_id) -> RateLimitDecision` | **Yes.** Async at birth; the argument and return value are both plain data. |
| **Circuit breaker** (Slice 20) | `CircuitBreaker` — `def observe(...) -> None`, `def assess(...) -> tuple[...]` | **No.** Both methods are synchronous, by an explicit documented decision ("No I/O in the contract"). |
| **Deduplicator** (Slice 10) | *none* | **No.** There is no port at all, and its signature is not transportable. |

### Why the circuit breaker cannot

`observe` and `assess` are `def`, not `async def`. Sharing state across processes requires I/O, and
synchronous I/O inside the event loop this gateway runs on would block every concurrent request for
the duration of the round-trip. The port's own docstring makes the constraint explicit and
deliberate: *"``observe`` and ``assess`` are synchronous and side-effect-free beyond the in-memory
state they maintain. A circuit breaker must react within one call's latency budget (NFR-P01), which
a per-call database round-trip cannot meet."*

One workaround exists and was evaluated rather than dismissed: keep local authoritative state and
reconcile it with a shared store from a **background task**, so `assess` reads a periodically
refreshed local snapshot. It was rejected on three specific grounds, not on taste.

1. **It cannot share the evidence, only the verdict.** The breaker trips on *consecutive* failures.
   Consecutive-failure counters do not merge: node A at 3 and node B at 2 is not "5", because a
   success on either resets its own count and the interleaving is unknowable after the fact. So each
   node would still have to accumulate a full threshold independently before tripping. What
   propagates is the resulting OPEN state, which is worth having — but it is strictly weaker than
   the milestone's stated requirement that *failures* recorded through one instance affect health
   observed through another.
2. **It cannot give single-probe half-open semantics.** Each node's cooldown elapses independently,
   so N nodes admit N probes at a recovering provider. A design that claims one probe and delivers N
   is precisely the "reports success while structurally unable to fail" pattern this project treats
   as its recurring defect.
3. **It requires runtime machinery that does not exist.** There is no background-task supervisor,
   no task lifecycle, and `Container.dispose` releases only the database pool. Inventing a task
   scheduler to preserve a method signature is a large amount of new, load-bearing infrastructure
   bought for the sole purpose of not editing two `def`s.

**Determination: the prediction is FALSIFIED for the circuit breaker.** The seam cannot express the
distributed semantics the milestone specifies without an interface change.

### Why the deduplicator cannot — and a plan correction

The Phase-5 plan lists `RequestDeduplicator` under M4's "seams consumed". **It is not a seam.**
There is no `DeduplicatorPort`; `InferenceCoordinator.__init__` names the concrete class, and the
composition root constructs it. Rule 4's "additional implementations may be added after the first
proves the shape" has never been available here, because there is no shape to implement against.

Even given a port, the signature is not transportable:

```python
async def coalesce(self, organization_id: UUID, correlation_id: str,
                   operation: Callable[[], Awaitable[T]]) -> T
```

Both parameters are process-bound. `operation` is a closure capturing `RoutingExecution`,
`InferenceRequest` and a `CacheKey`; `T` is an unbounded `TypeVar`, so a distributed implementation
would have to serialize a value about which it is guaranteed to know nothing. Cross-node
coalescing needs a *different contract* — a leader that executes and a follower that obtains the
result by some named, serializable means — which is a redesign of the concept, not a second
implementation of it.

**Determination: the prediction is FALSIFIED for the deduplicator, more severely.** The Phase-4
review recorded the deduplicator and the breaker as the same kind of debt. They are not: one has a
port whose shape is wrong, the other has no port.

## Decision drivers

- ADR-0016 Rule 5 and GP-2: the milestone's own plan pre-declares that *any port change here is a
  Rule-5 stop*. GP-2 says a milestone that would bend a rule stops and writes an ADR rather than
  reinterpreting it in place. This ADR is that stop.
- GP-1: architecture evolves on evidence. **There is no multi-replica deployment in this
  repository** — no manifest, no replica configuration, no orchestrator. The Phase-4 review
  classified cross-replica state as EVIDENCE REQUIRED for exactly this reason.
- The twice-validated local precedent: [ADR-0017](0017-postgres-transactional-budget-reservation.md)
  and ADR-0018 each faced "build the Redis mechanism the earlier ADR named?" and each chose the
  already-wired PostgreSQL, deferring Redis until evidence demanded it.
- `docs/API_Rate_Limiting.md` §4, which *decides* the mechanism for this one control: "Token-bucket
  in Redis (atomic), evaluated at the edge/API tier before routing".

## Decision

**1. Build shared rate limiting on Redis, behind the unchanged `RateLimiterPort`.**

`RedisTokenBucketRateLimiter` becomes a Rule-4 second implementation of the M3 port. The port, the
middleware, the decision type and the delivery layer are **byte-unchanged**; the composition root
selects the implementation. This is the milestone's central claim — that shared state slots in
behind a correctly-shaped port — actually run as an experiment, on the one port whose shape permits
it, and proven against real Redis rather than a fake.

It is chosen for M4 rather than invented for it: the M3 plan section names this exact hand-off —
"a shared limiter needs a store — which ties into M4 (this is the second real consumer that can
justify shared state / ADR-0005)" — and §4 of the rate-limiting contract already decided the
mechanism. Without it, M3's protection is per-replica, so N replicas admit N times the configured
rate; that is a *correctness* gap in a control shipped one milestone ago, not a hypothetical.

**2. Do not build a distributed circuit breaker or a distributed deduplicator in M4.** Both need an
interface change, which the plan pre-declared a stop. Both are recorded above with the evidence
that stopped them. Neither is abandoned: this ADR is the record a future milestone supersedes by
naming the interface change and its active consumer.

**3. Redis is adopted as an optional production dependency, not a required one.** With no
`GATEWAY_REDIS__URL` configured the composition root wires the in-process limiter exactly as M3
did. A deployment therefore never acquires a Redis dependency it did not ask for, and the
single-node profile — the only profile this repository can currently deploy — keeps working with no
new moving parts. This mirrors how `rls_enabled` selects Sql\* over InMemory\* implementations.

**4. On Redis outage the limiter degrades to a local bucket rather than failing closed.**

This **reverses M3's fail-closed choice for this control**, deliberately, on the evidence M3
pre-registered as the trigger: *"the availability cost of failing closed is approximately zero
today, and the day it is not (a shared store, M4) is the day the trade-off is genuinely different
and must be re-decided."* That day is this ADR.

With a network dependency in the path, failing closed converts a Redis blip into a total gateway
outage — the protective control becoming the incident. `API_Rate_Limiting.md` §4 anticipated exactly
this and chose "a conservative **default cap** (degraded protection) rather than unlimited — a
safety bias consistent with ADR-0009 (protecting the platform), while not blocking all traffic on a
soft control. Hard *budget* remains fail-closed."

This is **degraded-closed, not fail-open**, and the distinction is the whole justification:

- Traffic is still limited, by a local bucket with the same policy. During an outage the effective
  global ceiling is N × the configured rate for N replicas — bounded and stateable, not unlimited.
- The **financial** control is untouched and remains fail-closed: `ReservationService` gates every
  provider call against the PostgreSQL ledger, so a Redis outage cannot produce unbounded spend.
  Rate limiting protects infrastructure; the budget protects money; only the former degrades.
- It is **not silent.** Every degraded decision increments
  `gateway_ingress_decisions_total{control="rate_limit",outcome="unavailable"}` and logs once per
  transition, so "we are running degraded" is an alertable state rather than an invisible one.

## Options considered

### A — Change `CircuitBreaker` to async and build a Redis breaker now
- **Pros:** true shared counters; genuine single-probe half-open via `SET NX`; closes the review's
  top architectural risk.
- **Cons:** the plan pre-declares a port change as a Rule-5 stop, and GP-2 forbids taking it inside
  the milestone. The active consumer Rule 5 demands would have to be a multi-replica deployment,
  which does not exist. Adds a Redis round-trip to the routing hot path against NFR-P01, with no
  measurement showing it is affordable. **Rejected for M4; recorded as the supersession path.**

### B — Background-refreshed local breaker (no port change)
- **Pros:** preserves the signature; propagates OPEN state across replicas.
- **Cons:** the three grounds above — unmergeable counters, no single-probe semantics, and a
  task-supervision subsystem that does not exist. Buys a weaker guarantee at a higher cost than A,
  purely to avoid editing a signature. **Rejected.**

### C — Write `provider_health` snapshots from the breaker
- **Pros:** the table exists; it would gain the reader *and* writer the "no table without both"
  rule wants; no new dependency.
- **Cons:** the table is a **time series**, not a state cell — `observed_at DESC` index, "short
  retention", no uniqueness on `(organization_id, provider_id)`. Reading current state means an
  ordered query per provider per routing decision, on the hot path. It also keys on `provider_id`
  (a UUID FK), while the breaker keys on the provider *name*, so every write would need a
  name→id resolution the breaker must not perform. Writing snapshots that only a future reader would
  consume is the speculative infrastructure Rule 5 forbids. **Rejected.**

### D — Postgres-backed rate limiting instead of Redis
- **Pros:** no new dependency; RLS tenant isolation; follows the ADR-0017/0018 precedent exactly.
- **Cons:** a token bucket is a read-modify-write on every single request. On Postgres that is a
  row lock per request per tenant on the hot path — turning the ingress gate into the most
  contended write in the system, and making the cheap gate the expensive one. This is the case where
  the ADR-0017/0018 precedent does **not** transfer: those moved *money* and *cached answers*, where
  a round-trip is proportionate; this is a sub-millisecond admission check whose entire purpose is
  to be cheaper than what it protects. **Rejected, with the divergence from precedent stated.**

### E — Do nothing; declare M4 blocked
- **Pros:** maximally conservative.
- **Cons:** it would leave the one port that *was* correctly shaped untested against the very claim
  it was shaped for, and leave M3's protection per-replica. The experiment is worth running where it
  can be run. **Rejected.**

## Consequences

- **Positive.** The distribution thesis is validated on real infrastructure instead of asserted: a
  shared implementation slots in behind `RateLimiterPort` with the port, the middleware and delivery
  unchanged. The two places it is *not* true are now documented with evidence rather than discovered
  by a future deployment. Redis gains its first real consumer, so ADR-0005's backbone stops being
  provisioned-and-unused.
- **Negative / obligations.** A new optional production dependency, with its own failure mode,
  configuration and integration tests. Two of the three process-local states remain process-local,
  so a multi-replica deployment still learns provider health N times and still coalesces nothing
  across nodes — **explicitly not closed by this milestone**. Redis holds no tenant data, but it
  holds tenant *identifiers* in key names, so its namespace and TTLs are now a tenant-isolation
  surface that RLS does not cover and tests must.
- **Explicitly deferred, with the trigger stated:** distributed circuit breaking (trigger: a
  multi-replica deployment, plus an accepted ADR making `CircuitBreaker` async and naming that
  deployment as the consumer); distributed deduplication (trigger: the same, plus a `DeduplicatorPort`
  that defines transportable leader/follower semantics); `provider_health` as a real read/write
  table; Redis Streams and the `EventBus` port of ADR-0005 (a rate limiter needs no event bus, and
  building one with no publisher and no consumer is the trap this project keeps avoiding).

## Requirements satisfied

Advances FR-064/065 (rate limits enforced across the deployment, not merely per process) and
NFR-SEC08. Upholds ADR-0002/0014 (no tenant data leaves PostgreSQL; Redis keys are tenant-scoped and
carry no payload), ADR-0009 (the hard budget control remains fail-closed; only the soft platform
control degrades), ADR-0016 Rules 4 and 5 and GP-1/GP-2. Realizes the Redis half of ADR-0005 for one
concrete consumer without building the event bus that ADR's other consumers would need.

## Review notes

Superseding decisions 2 and 4 above requires naming an active consumer, per Rule 5 — for the
circuit breaker that means a real multi-replica deployment, not the prospect of one. Revisit the
degraded-cap fail mode if measurement shows Redis availability is high enough that failing closed
costs nothing, or if a tenant's risk posture requires the stricter direction (ADR-0009 permits
per-tenant overrides only in the safe direction, which this is).
