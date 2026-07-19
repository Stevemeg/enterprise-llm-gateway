# API Webhooks

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Outbound event notifications so customers can react to gateway events without polling. Realizes ADR-0005
(eventing), ADR-0011 (secret references), and the `webhook`/`webhook_delivery` schema.

## 1. Model
- A tenant registers a **webhook** (`POST /webhooks`) with an `https://` `url`, a list of subscribed
  `events`, and an optional **signing secret reference** (`secret_ref` → `secret_reference`; the secret
  itself is stored in the secrets manager, never in the DB — ADR-0011).
- The gateway emits **deliveries** (`webhook_delivery`) when subscribed events occur; delivery history is
  queryable via `GET /webhooks/{id}/deliveries`.

## 2. Event catalog (initial)
| Event type | When | Payload summary |
|-----------|------|-----------------|
| `budget.threshold_reached` | 80%/100% budget crossed (FR-066) | budget id, scope, percent |
| `budget.exceeded` | Hard budget hit (FR-061) | budget id, scope |
| `provider.circuit_opened` / `.recovered` | Circuit breaker state change (FR-037/038) | provider id, state |
| `key.created` / `key.revoked` | Key lifecycle (FR-096) | key id (no secret) |
| `usage.rollup_ready` | Daily aggregate computed | period, totals |
| `invoice.issued` | Invoice generated | invoice id, amount |
| `audit.high_risk_action` | Sensitive admin action | action, actor |
New event types are **additive** (non-breaking, [`API_Versioning_Strategy.md`](API_Versioning_Strategy.md)).

## 3. Delivery payload envelope
```json
{
  "id": "evt_01HZ…",
  "type": "budget.threshold_reached",
  "version": "1",
  "created_at": "2026-07-15T12:00:00Z",
  "organization_id": "…",
  "data": { /* event-specific, PII-scrubbed per governance_policy */ }
}
```
- `version` allows additive payload evolution per event type.
- `data` respects the tenant's logging/PII policy — no sensitive content beyond policy.

## 4. Security — signing & verification
- Each delivery is signed: header `X-ELG-Signature: t=<ts>, v1=<hmac_sha256(secret, ts + "." + body)>`.
- The signing secret is resolved from the `secret_ref` at send time; customers verify using their copy.
- **Replay protection:** reject if `t` is outside a tolerance window; verify the HMAC in constant time.
- Only `https://` endpoints accepted (schema-enforced). Optional allow-list / mTLS for high-security
  tenants (self-host).

## 5. Delivery guarantees & retries (ADR-0005)
- **At-least-once** delivery; consumers must be **idempotent** (dedupe on `id`).
- Retries on failure with exponential backoff over a bounded window; after max attempts the delivery is
  moved to **`dead_letter`** (`webhook_delivery.status`) and surfaced (list + optional notification).
- Delivery attempts, response codes, and status are recorded (`webhook_delivery`) — retention is transient
  ([`Data_Retention.md`](Data_Retention.md)).

## 6. Consumer guidance
- Respond `2xx` quickly (ack), process asynchronously; treat delivery as a signal and reconcile via REST if
  needed.
- Verify the signature before trusting the payload.
- Handle duplicates (idempotent by `id`) and out-of-order arrival (use `created_at`).

## 7. Relationship to internal events
Webhooks are the **external** projection of selected internal `EventBus` events (ADR-0005). Not every
internal event is exposed; the catalog is curated for customer relevance and privacy.

## 8. WebSockets vs webhooks
Webhooks are for **server-to-server** async notifications to customer backends. Live **UI** feeds use SSE/
(optionally) admin WebSockets — see [`API_Streaming.md`](API_Streaming.md) §4. They serve different needs.

## 9. Traceability
ADR-0005 (eventing/idempotency/DLQ), ADR-0011 (secret refs), FR-061/066/037/038/096; NFR-SEC (signing).
Schemas: `Webhook`, `WebhookDelivery` in [`api/OpenAPI.yaml`](api/OpenAPI.yaml).
