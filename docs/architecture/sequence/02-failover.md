# Sequence — Provider failover & circuit breaking

Primary provider fails; the routing engine fails over within the attempt/latency budget and updates
circuit-breaker state. Back to [index](README.md).

```mermaid
sequenceDiagram
    autonumber
    participant API as Inference API
    participant Route as Routing Engine
    participant CB as Circuit Breaker
    participant P1 as Provider A (primary)
    participant P2 as Provider B (fallback)
    participant Bus as Event Bus

    API->>Route: route(request) [eligible: A, B]
    Route->>CB: state(A)? 
    CB-->>Route: closed (healthy)
    Route->>P1: call model@A
    P1-->>Route: 503 / timeout (retryable, canonical error)
    Route->>CB: record failure(A)
    CB-->>Route: threshold exceeded → OPEN(A)
    Route->>Route: attempts<max && latency<budget?
    Route->>CB: state(B)?
    CB-->>Route: closed
    Route->>P2: call model@B
    P2-->>Route: 200 + usage
    Route-->>API: success via B + decision record (failover: A→B)
    API-)Bus: usage.recorded (provider=B) ; routing.failover event
    Note over CB: A stays OPEN until active probe passes → HALF_OPEN → CLOSED
```

## Notes
- Failover is **bounded** by max attempts and total latency budget (FR-035); if exhausted or no healthy
  eligible provider remains → `no_provider_available` (fail closed, [ADR-0009](../../adr/0009-fail-open-fail-closed-matrix.md) row 9).
- Only **retryable** canonical errors trigger failover (error normalization, [ADR-0003](../../adr/0003-provider-abstraction-strategy.md)).
- Retries are **idempotent** and **budget-safe**: the single reservation covers the attempt; usage is
  committed only for the successful call (FR-036).
- Circuit breaker recovers via active probe: OPEN → HALF_OPEN → CLOSED (FR-037/038).

**Requirements:** FR-034..038, FR-027; NFR-A02, NFR-P01.
