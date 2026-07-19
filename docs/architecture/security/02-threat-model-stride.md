# Threat Model — STRIDE

Systematic threat enumeration using **STRIDE**, mapped to controls, Phase-1 NFRs/Risks, and the
fail-closed matrix. Scope: the [trust boundaries](01-trust-boundaries.md) above. Back to
[Architecture](../../Architecture.md).

Method: for each STRIDE category we list representative threats, the assets/boundaries affected, the
mitigating controls (architecture), and residual risk. Rated **L×I** as in [Risks](../../Risks.md).

## S — Spoofing (identity)

| Threat | Boundary | Controls | Refs | Residual |
|--------|----------|----------|------|----------|
| Forged/stolen admin token | 2 | OIDC + JWT signature (JWKS), short expiry + refresh, key rotation/revocation | FR-090-093, ADR-0008 | Low |
| Stolen/leaked virtual key | 2 | Hashed keys, scopes, rotation/revocation, per-key rate limit, anomaly alerts | FR-094-097/064 | Low-Med |
| Provider endpoint impersonation (MITM) | Ext | TLS cert validation, pinned/allow-listed egress | NFR-SEC01, FR-142 | Low |

## T — Tampering (integrity)

| Threat | Boundary | Controls | Refs | Residual |
|--------|----------|----------|------|----------|
| Alter budget counters to overspend | 4 | Atomic Lua, ledger as source of truth, reconciliation, authz on writes | ADR-0004, FR-060-063 | Low |
| Modify/delete audit records | 4 | **Append-only + hash-chained**; API cannot mutate | FR-113/114, NFR-SEC09 | Low |
| Tamper request in transit | 1 | TLS 1.2+ end-to-end | NFR-SEC01 | Low |
| Poison semantic cache (wrong entry) | 4 | Tenant-scoped writes, thresholds, score logging, easy invalidation | ADR-0006, RISK-T02 | Med |

## R — Repudiation

| Threat | Boundary | Controls | Refs | Residual |
|--------|----------|----------|------|----------|
| Admin denies making a config change | 4 | Immutable audit of every sensitive action (actor, before/after) | FR-101/113 | Low |
| Dispute over usage/cost billed | 4 | Double-entry ledger, price-table versioning, reconciliation | FR-070-075, SM-T07 | Low |

## I — Information disclosure

| Threat | Boundary | Controls | Refs | Residual |
|--------|----------|----------|------|----------|
| **Cross-tenant data leak** | 2/4 | App tenant scoping **+ RLS** (defense in depth), isolation tests in CI | ADR-0002, NFR-SEC07, RISK-T05 | Low |
| **DB connects as superuser/BYPASSRLS role → RLS silently bypassed** | 2/4 | Dedicated least-privilege `app_rw` role (NOSUPERUSER, NOBYPASSRLS); migrations run as a separate owner; **CI bypass-containment check + `test_database_role.py`** fail if the runtime role can bypass RLS | ADR-0014, NFR-SEC07, RLS_Strategy §4/§7 | Low |
| PII sent to provider/embedder | 3/Ext | PII detection/redaction **fail closed**; governed embeddings; residency | FR-110-117, ADR-0007/0009, RISK-S01 | Low-Med |
| Secret disclosure (creds/keys) | 5 | Secrets manager, no plaintext, hashed keys, fail-fast | NFR-SEC03, FR-022/097 | Low |
| Sensitive data in logs/telemetry | 4 | PII-scrubbed structured logs; store/hash/drop policy | FR-082/118 | Low-Med |
| Residency violation (out-of-region) | 3 | Residency eligibility, **fail closed**, home-region pinning | FR-116/117, ADR-0010, RISK-S03 | Low |

## D — Denial of service

| Threat | Boundary | Controls | Refs | Residual |
|--------|----------|----------|------|----------|
| Volumetric flood at edge | 1 | WAF, DDoS protection, edge rate limiting | NFR-SEC08, FR-065 | Med |
| Noisy-neighbor tenant exhausts capacity | 2 | Per-tenant/key quotas + rate limits, budget caps | FR-064/138, NFR-S06 | Low-Med |
| Provider outage cascades | Ext | Failover, circuit breakers, bounded retries | FR-034-038, NFR-A02 | Low |
| Redis (budget) outage blocks all traffic | 4 | HA Redis; hard-limit **fail closed** but HA minimizes; cache degrade open | ADR-0009 r1, NFR-A03 | Med |
| Event bus backpressure | 4 | Durable streams, DLQ, shed non-critical, preserve audit/usage | ADR-0005/0009 r14 | Low-Med |

## E — Elevation of privilege

| Threat | Boundary | Controls | Refs | Residual |
|--------|----------|----------|------|----------|
| Developer performs admin action | 2 | RBAC deny-by-default, least privilege, permission catalog | FR-098-100, ADR-0008 | Low |
| Virtual key gains admin scope | 2 | Keys restricted to inference scopes; never admin perms | FR-095, ADR-0008 | Low |
| Auditor modifies data | 2 | Auditor read-only; writes denied + audited | AC-US-072 | Low |
| Container/supply-chain compromise | 4 | Image scanning, dependency scanning (CI gate), least-privilege runtime | NFR-SEC06 | Med |

## Priority actions (highest residual → design/test focus)
1. **Cross-tenant isolation** (I): mandatory automated isolation tests + RLS — Phase 13 (RISK-T05).
2. **PII/residency fail-closed** (I): governance chaos tests per [ADR-0009](../../adr/0009-fail-open-fail-closed-matrix.md) rows 3/5 (RISK-S01/S03).
3. **Semantic-cache poisoning/false-positive** (T): conservative thresholds + score audit + Phase-13 false-positive measurement (RISK-T02).
4. **Budget-store DoS/overspend** (T/D): HA Redis + fail-closed + concurrency load test (RISK-T03).
5. **Supply chain** (E): SAST/DAST + dependency/image scanning as CI gates (NFR-SEC06).

## Coverage
Every STRIDE category maps to concrete architectural controls and to Phase-1 NFR-SEC*/NFR-C* and the
risk register. Verification is scheduled in Phase 13 (security, isolation, chaos tests). This model is
updated whenever a new component/boundary is introduced.

**Requirements:** NFR-SEC01..09, NFR-C01..06; Risks RISK-T02/T03/T05, RISK-S01..S04.
