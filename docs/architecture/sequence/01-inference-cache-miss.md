# Sequence — Inference request (cache miss, happy path)

The canonical hot path: authenticate → govern → reserve budget → cache check → route → provider →
respond, with async metering. Back to [index](README.md).

```mermaid
sequenceDiagram
    autonumber
    participant App as Client App
    participant Edge as Edge (TLS/WAF)
    participant API as Inference API
    participant Auth as AuthN/AuthZ
    participant Gov as Governance (PII/residency)
    participant Bud as Budget (Redis Lua)
    participant Cache as Cache (Redis/pgvector)
    participant Route as Routing Engine
    participant Prov as Provider Adapter
    participant Bus as Event Bus

    App->>Edge: POST /v1/chat/completions (key)
    Edge->>API: forward (TLS terminated, rate-limit ok)
    API->>Auth: validate key + scope, resolve tenant, RBAC
    Auth-->>API: principal + tenant context (deny→401/403)
    API->>Gov: PII scan + residency eligibility
    Gov-->>API: sanitized request + allowed providers/regions
    API->>Bud: reserve(scopeChain, estimate=max_tokens×price)
    Bud-->>API: reservationId (or budget_exceeded → 402/429, fail closed)
    API->>Cache: exact lookup (hash) ; if miss → semantic (gated)
    Cache-->>API: MISS
    API->>Route: eligible candidates → rank → select
    Route-->>API: chosen model + decision record
    API->>Prov: call provider (chosen model)
    Prov-->>API: response + usage (tokens)
    API-->>App: 200 response (x-request-id, cache: miss)
    API-)Bus: publish usage.recorded (async, non-blocking)
    Note over Bud,Bus: Worker commits actual cost to ledger &<br/>reconciles reservation (see seq 06)
```

## Notes
- Steps 3–8 are the **synchronous governance/enforcement** gates; each **fails closed** per
  [ADR-0009](../../adr/0009-fail-open-fail-closed-matrix.md).
- Budget **reserve** (step 8) is a single atomic Redis Lua call (≤5 ms, NFR-P05); **commit** is async
  (step 15+) so metering adds **0 ms** to the response (NFR-P06).
- Overhead target for steps 2–13 excluding provider time: **p99 ≤ 50 ms** (NFR-P01).

**Requirements:** FR-001..010, FR-030..033, FR-050..053, FR-060..063, FR-070..073, FR-110..117;
NFR-P01/P05/P06.
