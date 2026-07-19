# Sequence — Budget reserve → commit / release

The two-phase cost-accounting flow that guarantees hard enforcement under concurrency without blocking
metering. Back to [index](README.md) · [ADR-0004](../../adr/0004-reserve-commit-cost-accounting.md).

```mermaid
sequenceDiagram
    autonumber
    participant API as Inference API
    participant Lua as Redis (Lua reserve)
    participant Prov as Provider
    participant Bus as Event Bus
    participant WM as Worker (metering)
    participant PG as PostgreSQL (ledger)
    participant Rec as Reconciler

    API->>Lua: EVAL reserve(key,team,tenant, estimate)
    alt any scope insufficient
        Lua-->>API: DENY (most-restrictive-wins)
        API-->>API: reject budget_exceeded (fail closed)
    else all scopes ok
        Lua-->>API: OK reservationId (counters decremented)
        API->>Prov: call model
        alt provider success
            Prov-->>API: response + actual usage
            API-)Bus: usage.recorded(reservationId, actualCost)
            Bus->>WM: deliver (at-least-once, idempotent)
            WM->>PG: append double-entry ledger row
            WM->>Lua: reconcile(reservationId, actual) (refund/debit delta)
        else provider failure
            Prov-->>API: error
            API->>Lua: release(reservationId) (restore estimate)
        end
    end
    Note over Rec,PG: Periodically & at period reset:<br/>Rec rebuilds Redis counters from PG ledger (bounds drift, FR-069)
```

## Notes
- **Reserve** decrements **most-restrictive-first** (key→team→tenant); a failure at any level denies
  (FR-062). Atomic Lua → correct under concurrency (FR-063, kills RISK-T03).
- **Estimate** is an upper bound (`max_tokens`×price); **commit** reconciles to actual → accurate ledger
  (SM-T07) without blocking the response (NFR-P06).
- If Redis is unavailable for a **hard-limited** scope, reserve **fails closed**
  ([ADR-0009](../../adr/0009-fail-open-fail-closed-matrix.md) row 1).
- The **ledger** (Postgres, append-only) is the system of record; Redis is a fast, reconstructable cache
  of counters.

**Requirements:** FR-060..063, FR-069, FR-070..073; NFR-P05/P06/S05; SM-P06.
