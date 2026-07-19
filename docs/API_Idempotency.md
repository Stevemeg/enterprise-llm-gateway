# API Idempotency

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Safe retries for mutating and inference requests. Realizes FR-036 (idempotent/safe retries), supports the
reserve/commit accounting (ADR-0004) and at-least-once eventing (ADR-0005).

## 1. Mechanism
- Clients send **`Idempotency-Key: <uuid>`** on `POST` create/action requests (and inference POSTs).
- The server stores the key with the **request fingerprint** (route + hash of body) and the **saved
  response** for a **24-hour** window.
- **Replays:**
  - Same key + same fingerprint → the **original response is returned** (same status/body); the operation
    is **not** re-executed.
  - Same key + **different** fingerprint → `409 conflict_error` (`idempotency_key_reuse`) — a key must not
    be reused for a different request.
  - A retry arriving while the first is still in flight → `409` (`idempotency_in_progress`) or a short
    wait, then the stored result (implementation detail; contract: no double effect).

## 2. Which operations
| Operation class | Idempotency |
|-----------------|-------------|
| Inference `POST` (`/chat/completions`, `/completions`, `/embeddings`) | **Recommended** — prevents double provider charge on network retry |
| Create `POST` (`/organizations`, `/projects`, `/api-keys`, `/budgets`, …) | **Recommended** — prevents duplicate resources |
| Action `POST` (`/api-keys/{id}/rotate`) | **Recommended** |
| `PATCH`/`PUT` | Naturally idempotent by value; key optional |
| `DELETE` | Idempotent by definition (repeat → 204/404) |
| `GET` | Safe/idempotent; no key |

## 3. Interaction with budgets (ADR-0004)
Inference idempotency ensures a **retried request that actually succeeded** does not create a **second
reservation or a duplicate `usage_ledger` entry**. The `Idempotency-Key` (or the gateway `request_id`)
is the dedupe key: the reservation is keyed to it, and metering consumers dedupe on it (exactly-once
*effects* over at-least-once delivery, ADR-0005). This directly protects budget correctness (RISK-T03,
SM-P06 zero overspend) under client retries.

## 4. Client guidance
- Generate a **fresh UUID per logical operation**; reuse the **same** key for **retries of that same
  operation** (backoff + jitter, honoring `Retry-After`).
- Do **not** reuse a key for a semantically different request.
- SDKs auto-attach an idempotency key to create/action calls and reuse it across their internal retries
  ([`API_SDK_Guidelines.md`](API_SDK_Guidelines.md)).

## 5. Scope & storage
- Keys are scoped **per tenant + principal + route**; collisions across tenants are impossible.
- Stored responses respect the tenant's logging/PII policy (a stored inference response follows
  `governance_policy` — [`Data_Retention.md`](Data_Retention.md)); default retention 24h then purged.

## 6. Guarantees
- **At-most-once effect** for a given key within the window, regardless of retries or duplicate delivery.
- Combined with server-side idempotent event consumers, the end-to-end pipeline yields **exactly-once
  effects** for metering, audit, and cache population.

## 7. Traceability
FR-036; ADR-0004 (reserve/commit), ADR-0005 (idempotent consumers); RISK-T03; SM-P06.
