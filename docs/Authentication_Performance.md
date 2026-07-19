# Authentication Performance Baseline

**Phase:** 5 — Backend Implementation · Milestone 3d (Authentication)
**Status:** Measurement baseline (Gate 1 sandbox) · re-measure required in Gate 2
**Last updated:** 2026-07-18
**Related:** [Cryptographic_Architecture.md](Cryptographic_Architecture.md) ·
[Authentication_Architecture.md](Authentication_Architecture.md) ·
[Security_Test_Plan.md](Security_Test_Plan.md) · [Local_Validation_Guide.md](Local_Validation_Guide.md)

> **Scope.** This document **measures**, it does not optimize. It establishes a latency baseline for
> the four credential-verification paths so future changes can be judged against a known starting
> point. No code was tuned to produce these numbers. Optimization opportunities are listed at the
> end as *candidates*, not committed work.

---

## 1. What was measured

The authentication subsystem verifies four kinds of credential. Each has a distinct cryptographic
cost profile, so each is measured independently. The measured unit is the **cryptographic + in-memory
verification work only** — the portion the gateway executes on CPU. Database round-trips (the API-key
prefix lookup, the session/refresh-token row fetch, the service-account credential fetch) are
**explicitly excluded** here because they are I/O-bound and are governed by the database performance
budget in [Query_Performance_Guide.md](Query_Performance_Guide.md), not by the auth CPU budget. Where a
path has a DB step, this document states so and measures only the CPU-side verification.

| # | Path | What it exercises | DB step (excluded here) |
|---|------|-------------------|-------------------------|
| 1 | **JWT verification** | RS256 signature verify + claim/exp/aud/iss validation (per-request hot path) | none |
| 2 | **JWT issuance** | RS256 sign + claim assembly (login / refresh path only) | none |
| 3 | **API-key verification** | SHA-256 of presented key + constant-time compare to stored hash | prefix → row lookup |
| 4 | **Refresh-token validation** | SHA-256 of presented token + constant-time compare to stored hash | token_hash → row lookup |
| 5 | **Service-account authentication** | secret hash + constant-time verify against stored credential | client_id → credential lookup |

The single most important number for steady-state request latency is **path #1 (JWT verification)**,
because every authenticated API request runs it and it involves no database I/O. Paths #3–#5 are the
first-contact / token-mint paths; path #2 runs only at login and token refresh.

---

## 2. Test environment

| Property | Value |
|----------|-------|
| Gate | Gate 1 (isolated sandbox) |
| Python | 3.10.12 — **3.10 validation shim** (sed-transformed copy of the real 3.13 source) |
| CPU | 11th Gen Intel Core i5-11320H @ 3.20 GHz (2 vCPU visible to sandbox) |
| Memory | 3.8 GiB total |
| OpenSSL | 3.0.2 (15 Mar 2022) |
| cryptography | 49.0.0 |
| PyJWT | 2.13.0 |
| Clock | `time.perf_counter_ns()`, monotonic, nanosecond resolution |

> **Two caveats, stated up front.**
> 1. **Shim, not target.** Numbers were taken on the Python **3.10** validation shim, not the
>    production **3.13** runtime, and inside a CPU-throttled 2-vCPU sandbox. Absolute values —
>    **especially RSA private-key signing (path #2)** — will differ on production hardware and a
>    3.13 interpreter. Treat these as *relative* baselines and *orders of magnitude*, not SLAs.
> 2. **CPU-only.** The DB-backed paths (#3–#5) are measured for their crypto work only; end-to-end
>    latency in Gate 2 will add one indexed single-row lookup each.
>
> A Gate 2 re-measurement on real PostgreSQL + the 3.13 runtime is required before any of these
> numbers are quoted as a production SLA. See §6.

---

## 3. Methodology

For each path a tight micro-benchmark was run in-process against the real implementation classes
(`JwtService` / `JwtTokenService` / `KeyProvider` for JWT; `gateway.shared.secrets` for the
hash-based paths) — no mocks, no stubs. Each measurement:

1. **Warm-up.** 50 iterations (JWT) / 200 iterations (hash paths) discarded to prime the
   interpreter, OpenSSL, and CPU caches.
2. **Sample.** N timed iterations, each wrapped in `perf_counter_ns()` deltas converted to
   microseconds.
3. **Statistics.** Arithmetic mean, p95, and p99 computed from the sorted sample.

Sample sizes were chosen to keep total runtime within the sandbox execution budget while remaining
statistically meaningful: JWT verify N=800, JWT issue N=400 (RSA signing is intrinsically ~100×
costlier than the hash paths, so fewer iterations), hash paths N=20 000 each.

Reproduction command lives alongside the validation scripts; the benchmark imports the production
classes directly so it cannot drift from shipped behaviour.

---

## 4. Results

All figures in **microseconds (µs)**. 1 000 µs = 1 ms.

| Path | Operation | Mean | p95 | p99 | N |
|------|-----------|-----:|----:|----:|--:|
| 1 | **JWT verification** (RS256) | **111.5 µs** | 129.4 µs | 145.2 µs | 800 |
| 2 | **JWT issuance** (RS256 sign) | **40 716 µs** | 44 698 µs | 52 488 µs | 400 |
| 3 | **API-key verification** (SHA-256 + CT compare) | **1.19 µs** | 1.22 µs | 2.09 µs | 20 000 |
| 4 | **Refresh-token validation** (SHA-256 + CT compare) | **2.20 µs** | 2.78 µs | 4.23 µs | 20 000 |
| 5 | **Service-account auth** (hash + CT verify) | **1.17 µs** | 1.19 µs | 1.25 µs | 20 000 |

### Reading the table

- **JWT verification (path #1) — ~0.11 ms mean, ~0.15 ms p99.** This is the per-request hot path and
  it is cheap and tightly bounded: p99 is only ~30% above the mean, so the tail is well-behaved. At
  ~0.11 ms of CPU per request, JWT verification is not a throughput bottleneck for the gateway.
- **JWT issuance (path #2) — ~41 ms mean.** This is **~365× slower than verification** and dominates
  the entire auth subsystem's CPU cost. That asymmetry is expected and inherent to RSA: the
  private-key operation (sign) is far more expensive than the public-key operation (verify). The
  absolute value here is inflated by the throttled 2-vCPU sandbox and the 3.10 shim — on production
  hardware RSA-2048 signing is typically low-single-digit milliseconds — but the **shape** (issuance
  ≫ verification) is real and will hold on any hardware. Issuance runs only at login and refresh, not
  per request, so it does not gate steady-state request latency; it does bound login/refresh
  throughput and is the primary optimization candidate (§5).
- **Hash paths (#3–#5) — ~1–2 µs.** API-key, refresh-token, and service-account verification are
  SHA-256 + constant-time comparison and are effectively free relative to the JWT paths (~50–100×
  cheaper than even a JWT *verify*, ~20 000× cheaper than a JWT *issue*). Their end-to-end latency in
  production will be dominated entirely by the single indexed DB lookup that precedes them, not by the
  crypto measured here. The constant-time compare is intentional (timing-attack resistance) and its
  cost is negligible.

---

## 5. Bottlenecks

1. **RSA private-key signing (JWT issuance) is the dominant cost by three orders of magnitude.**
   Everything else in the auth subsystem is rounding error next to it. This is the one place where CPU
   cost is material, and it is confined to the login/refresh path.
2. **RSA verification, while cheap in absolute terms (~0.11 ms), is still ~50–100× the cost of the
   hash paths.** Because it runs on *every* authenticated request, it — not the DB-free hash checks —
   is the auth component most worth watching as request volume scales.
3. **The hash-based paths are not CPU-bottlenecked at all.** Their real-world latency will be set by
   the preceding single-row indexed database lookup (see [Query_Performance_Guide.md](Query_Performance_Guide.md)),
   which this document deliberately does not measure.

---

## 6. Future optimization opportunities (candidates, not commitments)

These are recorded for later evaluation. **None are being implemented now** — consistent with the
"measure, don't optimize" scope of this milestone. Each would require its own design + ADR before
adoption.

1. **Consider EdDSA (Ed25519) in addition to / instead of RS256.** Ed25519 signing is dramatically
   faster than RSA-2048 signing and keys are far smaller, which would collapse the path-#2 cost. This
   is an algorithm-agility decision (the JWT layer already enforces an algorithm allow-list) and would
   need a signing-key-type ADR, JWKS `kty` handling, and a rotation/compat plan.
2. **Amortize issuance cost with longer-lived access tokens + short refresh cadence**, trading token
   TTL against re-issuance frequency — a security/latency trade-off, not a pure win.
3. **Cache the verifying public key / parsed JWKS** (already effectively in-memory via `KeyProvider`)
   and confirm no per-request key re-parse creeps in as the code evolves; guard with a regression
   check on path #1.
4. **Move issuance off the request-blocking path** where product flows allow (e.g. pre-mint or
   background refresh), so the ~tens-of-ms sign cost never sits in a user-facing critical section.
5. **Re-baseline on the 3.13 runtime with hardware-accelerated OpenSSL** before setting any numeric
   SLA; the current absolute figures are sandbox-inflated.

---

## 7. Gate 2 re-measurement checklist

Before any figure here is treated as a production SLA, re-run on the target stack and record the
deltas:

- [ ] Python **3.13** runtime (not the 3.10 shim).
- [ ] Real PostgreSQL up (`docker-compose.dev.yml`) so paths #3–#5 can be measured **end-to-end**
      (crypto **+** the indexed single-row lookup).
- [ ] Production-representative CPU (not the throttled 2-vCPU sandbox).
- [ ] Record mean/p95/p99 for all five paths and compare against §4; flag any path whose p99
      regresses > 2× this baseline.

---

*Numbers in this document are a Gate 1 sandbox baseline captured on 2026-07-18. They are intended for
relative comparison and regression detection, not as production latency guarantees.*
