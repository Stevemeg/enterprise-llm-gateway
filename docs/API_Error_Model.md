# API Error Model

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

One error shape for the whole API — machine-readable, stable, and correlatable. Realizes FR-009/010
(typed errors, no leakage) and ADR-0009 (fail-closed semantics). Schema: `Error` in
[`api/OpenAPI.yaml`](api/OpenAPI.yaml).

## 1. Envelope
```json
{
  "error": {
    "type": "budget_error",
    "code": "budget_exceeded",
    "message": "Monthly budget for project 'search' is exhausted.",
    "request_id": "req_01HZY…",
    "retryable": false,
    "retry_after_seconds": null,
    "details": [ { "field": "…", "issue": "…", "message": "…" } ],
    "doc_url": "https://docs.example.com/errors/budget_exceeded"
  }
}
```
- **`type`** — coarse machine category (enum, stable). Drives client branching.
- **`code`** — fine, stable, machine-readable slug. Never reworded once shipped (deprecate instead).
- **`message`** — human-readable, non-localized, safe (no secrets/PII/stack traces, FR-010).
- **`request_id`** — correlation id; equals the `X-Request-Id` response header; matches logs/traces.
- **`retryable`** / **`retry_after_seconds`** — retry guidance (see §4).
- **`details`** — per-field validation issues (422) or structured context.
- **`doc_url`** — link to the error's documentation.

## 2. Error `type` → HTTP status
| `type` | HTTP | Meaning | Fail mode |
|--------|------|---------|-----------|
| `invalid_request_error` | 400 | Malformed syntax/JSON | — |
| `authentication_error` | 401 | Missing/invalid credentials | closed |
| `permission_error` | 403 | RBAC/scope denied | closed |
| `not_found_error` | 404 | Absent or not visible to tenant | — |
| `conflict_error` | 409 | Uniqueness/state conflict | — |
| `validation_error` | 422 | Semantically invalid | — |
| `rate_limit_error` | 429 | Rate/quota exceeded | closed |
| `budget_error` | 402 | Hard budget exhausted | closed (ADR-0004) |
| `provider_error` | 502 | Upstream provider failed after failover | — |
| `availability_error` | 503 | No eligible/healthy provider, or not ready | closed (ADR-0009) |
| `governance_error` | 403 | PII/residency policy blocked | closed |
| `internal_error` | 500 | Unexpected server fault | — |

404 is intentionally returned instead of 403 where revealing existence would leak cross-tenant
information.

## 3. Representative stable codes
| code | type | HTTP | Notes |
|------|------|------|-------|
| `invalid_json` | invalid_request_error | 400 | Body not parseable |
| `missing_parameter` | invalid_request_error | 400 | Required param absent |
| `invalid_api_key` | authentication_error | 401 | Unknown/revoked key |
| `token_expired` | authentication_error | 401 | JWT expired |
| `insufficient_scope` | permission_error | 403 | Key/role lacks scope (e.g., chat-only key on embeddings) |
| `field_invalid` | validation_error | 422 | See `details[]` |
| `budget_exceeded` | budget_error | 402 | Hard budget hit (FR-061) |
| `rate_limited` | rate_limit_error | 429 | See `Retry-After` |
| `quota_exceeded` | rate_limit_error | 429 | Period token/request quota |
| `provider_unavailable` | provider_error | 502 | All attempts failed |
| `no_provider_available` | availability_error | 503 | No eligible route (FR-117) |
| `residency_violation` | governance_error | 403 | No compliant region (FR-117) |
| `pii_blocked` | governance_error | 403 | PII policy = block (FR-111) |
| `budget_unavailable` | availability_error | 503 | Budget store down; hard-limit fail-closed (ADR-0009 r1) |
| `conflict` | conflict_error | 409 | Duplicate slug/name |

The **full registry** of codes (one row per code, immutable) is maintained alongside the spec and
published at `doc_url` roots; new codes are additive and announced via
[`API_Changelog_Policy.md`](API_Changelog_Policy.md).

## 4. Retry semantics
- `retryable:true` with `retry_after_seconds` → client may retry after the delay (429, transient 502/503).
- `retryable:false` → do not blind-retry (400/401/403/404/409/422/402). Fix the request or state first.
- **Idempotency:** retries of create/action POSTs must reuse the original `Idempotency-Key`
  ([`API_Idempotency.md`](API_Idempotency.md)) so a retried-but-actually-succeeded call is not
  duplicated.
- SDKs implement exponential backoff + jitter honoring `Retry-After` (see [`API_SDK_Guidelines.md`](API_SDK_Guidelines.md)).

## 5. Provider error normalization
Upstream provider errors are mapped to the canonical taxonomy (ADR-0003) before returning — clients see
a stable `provider_error`/`availability_error`, never a raw provider payload. The originating provider
may be surfaced (non-sensitively) in `details` for debugging.

## 6. Correlation
Every response — success or error — carries `X-Request-Id`; on errors it is also in `error.request_id`.
This id threads logs, traces, and metrics (FR-080/082) so support can pinpoint any request.

## 7. Consistency rules (enforced in tests)
- Every non-2xx response body validates against `Error`.
- Every `code` has exactly one `type` and one canonical HTTP status.
- Messages contain no secrets/PII/stack traces (checked in Phase 13, FR-010).
- `code`s are never renamed or repurposed — only added or deprecated
  ([`API_Deprecation_Policy.md`](API_Deprecation_Policy.md)).
