# API Rate Limiting & Quotas

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Protects the platform and enforces fair use / noisy-neighbor isolation. Realizes FR-064/065, NFR-S06,
NFR-SEC08; distinct from monetary budgets (ADR-0004, [`API_Idempotency.md`](API_Idempotency.md) note).

## 1. Two independent controls
| Control | Unit | Enforced | Exceed → |
|---------|------|----------|----------|
| **Rate limit** | requests/second, requests/period, tokens/period | per scope (org/project/api_key), Redis token-bucket | `429 rate_limit_error` |
| **Budget** | money | per scope, reserve/commit (ADR-0004) | `402 budget_error` |

Both can trigger on one request; **rate limit is checked before budget reservation** (cheap gate first).

## 2. Scope hierarchy (FR-064)
Limits are configured via `rate_limit_policy` at **organization / project / api_key** scope
(`POST /rate-limits`). The **most-restrictive** applicable limit wins (mirrors budget hierarchy). Default
platform limits apply if no policy is set, protecting shared infra (NFR-SEC08).

## 3. Response signaling
- **Success responses** include a `RateLimit` header: `limit=<n>, remaining=<n>, reset=<seconds>`.
- **On limit:** `429` + `Retry-After: <seconds>` + `RateLimit` + `Error` body (`rate_limited` or
  `quota_exceeded`), `retryable:true`.
- Token-based quotas (`tokens_per_period`) return `quota_exceeded` when the period token allotment is
  spent.

## 4. Algorithm & placement
- **Token-bucket in Redis** (atomic), evaluated at the edge/API tier before routing — sub-millisecond,
  consistent with the reserve path (ADR-0004 infra reuse). RPS smoothing via bucket refill; period
  quotas via counters with scheduled reset.
- **Fail-closed vs open:** if the rate-limit store is unavailable, the platform applies a conservative
  **default cap** (degraded protection) rather than unlimited — a safety bias consistent with ADR-0009
  (protecting the platform), while not blocking all traffic on a soft control. Hard *budget* remains
  fail-closed.

## 5. Streaming & long requests
- A streaming (SSE) inference request counts as **one** request against RPS at initiation; **token**
  quotas are debited on completion from actual usage.
- Concurrency caps (max in-flight streams per scope) may be applied to protect connection pools.

## 6. Client guidance
- Read `RateLimit`/`Retry-After`; back off with jitter; do not hammer on `429`.
- SDKs implement automatic backoff honoring `Retry-After` ([`API_SDK_Guidelines.md`](API_SDK_Guidelines.md)).
- Use multiple keys/projects to partition workloads intentionally rather than to evade limits (limits
  aggregate up the scope hierarchy).

## 7. Observability
Rate-limit decisions emit metrics (allow/deny per scope) and feed dashboards/alerts (FR-081/085); repeated
`429`s on a scope can trigger a notification (FR-066).

## 8. Traceability
FR-064/065, NFR-S06, NFR-SEC08, ADR-0004 (infra), ADR-0009 (fail bias). Config of record:
`rate_limit_policy` ([`Data_Dictionary.md`](Data_Dictionary.md)).
