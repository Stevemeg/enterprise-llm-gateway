# ADR-0009: Fail-open vs fail-closed behavior matrix

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, Security Architect, SRE
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** Fail-open vs fail-closed behavior matrix (Phase-1 review finding #2)

## Context & problem
NFR-A04 requires a **documented** failure mode per feature, but Phase 1 left it implicit. Each
dependency (Redis, PostgreSQL, IdP, provider, embedding, PII detector, event bus) can fail, and the
*wrong* default is dangerous in opposite directions: failing **open** on a governance control (PII,
residency, budget) is a compliance/financial breach (RISK-S01, RISK-S03, RISK-T03); failing **closed**
on a non-critical enrichment needlessly harms availability (NFR-A01). We need an explicit, per-feature
policy that biases **security/financial-integrity controls to fail closed** and **availability-neutral
enrichments to fail open (degrade)**.

## Decision drivers
- NFR-A04 (documented degradation), NFR-A01 (99.95% availability), NFR-SEC*/NFR-C* (security/compliance
  must not silently bypass), FR-061 (hard budget), FR-117 (residency fail closed), FR-110..112 (PII).
- Risks: RISK-T03 (overspend), RISK-S01 (PII leak), RISK-S03 (residency), RISK-T02 (bad cache hit).

## Options considered
### Option A — Global fail-open (favor availability everywhere)
- **Pros:** Maximum uptime.
- **Cons:** A down PII detector or budget store would let requests through ungoverned/unbounded —
  unacceptable breach. Rejected.

### Option B — Global fail-closed (favor safety everywhere)
- **Pros:** Safest.
- **Cons:** A blip in a non-critical enrichment (e.g., analytics, non-blocking metering) would reject
  user traffic and blow the availability SLO. Rejected.

### Option C — **Per-feature matrix**: fail closed for integrity/security/financial controls; fail
open (graceful degrade) for availability-neutral enrichments; explicit per-tenant overrides where a
customer's risk posture differs.
- **Pros:** Correct bias per concern; satisfies both governance and availability; explicit and testable.
- **Cons:** Must be enumerated, implemented, and tested per feature (more work) — but that is exactly
  what NFR-A04 demands.

## Decision
Adopt **Option C**. The authoritative behavior matrix:

| # | Feature / dependency | On failure | Mode | Rationale | Refs |
|---|----------------------|-----------|------|-----------|------|
| 1 | **Budget/quota store (Redis) for hard-limited scope** | Reject request (`budget_unavailable`) | **Closed** | Never allow unbounded spend | FR-061, RISK-T03 |
| 2 | Budget for **soft-limited** scope | Allow + warn event | Open | Soft limits are advisory | FR-067 |
| 3 | **PII detection/redaction** (policy=redact/block) | Reject/block | **Closed** | Never leak PII to provider | FR-110-112, RISK-S01 |
| 4 | PII detection (policy=allow-with-log) | Allow + flag degraded | Open | Logging-only policy | FR-111 |
| 5 | **Data-residency evaluation** | Reject (`residency_unavailable`) | **Closed** | Never risk out-of-region routing | FR-116/117, RISK-S03 |
| 6 | **AuthN (OIDC/JWT) / AuthZ / key validation** | Reject (401/403) | **Closed** | No auth → no access | FR-090-101 |
| 7 | **Audit log write** (security events) | Reject the *audited admin action*; buffer+alert for inference-side | **Closed** (admin) | Actions must be auditable | FR-113/114 |
| 8 | **Primary provider** error/timeout | Failover to next healthy provider | Open (via failover) | That's the point of the gateway | FR-034-038, NFR-A02 |
| 9 | **All eligible providers** down | Reject (`no_provider_available`) | Closed (unavoidable) | Nothing to serve | NFR-A04 |
| 10 | **Exact/semantic cache** lookup error | Treat as miss → call provider | Open | Cache is an optimization | FR-050-058 |
| 11 | **Embedding** service (for semantic lookup) | Skip semantic tier → exact/provider | Open | Degrade, don't fail | ADR-0007 |
| 12 | **Metering/usage event publish** | Buffer/retry async; never block | Open (non-blocking) | Accounting is async | NFR-P06, ADR-0005 |
| 13 | **Analytics/rollups** | Serve stale / skip | Open | Non-critical | FR-086 |
| 14 | **Event bus** unavailable | Local durable buffer + retry; if buffer exhausted, shed non-critical, preserve audit/usage | Open w/ backpressure | Protect hot path + durability | ADR-0005, NFR-A05 |
| 15 | **PostgreSQL** (system of record) unavailable | Reject writes needing it; serve cache-only reads where safe | **Closed** for writes | Integrity | NFR-A05 |
| 16 | **Secrets manager** unreachable at startup | Fail fast (don't start) | **Closed** | No secrets → misconfigured | FR-146, RISK-S04 |

Per-tenant overrides are permitted **only** in the safe direction (a tenant may make an Open control
stricter; it may not turn a Closed integrity control Open). All degraded responses set an explicit
degradation indicator and emit an alert.

## Consequences
- **Positive:** Governance/financial integrity never silently bypassed; availability preserved for
  optimizations; every mode is explicit and testable — satisfies NFR-A04.
- **Negative:** More conditional handling and chaos tests to author.
- **Follow-ups:** Phase 9/10 implement per-feature degradation; Phase 13 chaos tests each row.

## Requirements satisfied
- Functional: FR-034..038, FR-061, FR-067, FR-110..112, FR-113, FR-116, FR-117, FR-146.
- Non-functional: NFR-A01, NFR-A02, NFR-A04, NFR-A05, NFR-SEC*, NFR-C02, NFR-P06.

## Review notes
This matrix is the single source of truth for degradation; any new dependency/feature must add a row
before GA. Revisit per-row defaults after Phase 13 chaos results.
