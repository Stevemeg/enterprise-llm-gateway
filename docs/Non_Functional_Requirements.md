# Non-Functional Requirements (NFRs)

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15
**Scale target:** Large enterprise — thousands of RPS, billions of tokens/month, hundreds of tenants.

NFRs are testable and referenced by [`Traceability_Matrix.md`](Traceability_Matrix.md). Targets are
initial and will be validated by load/chaos testing in Phase 13. All latency numbers refer to
**gateway-added overhead**, excluding provider inference time, unless stated otherwise.

Legend — **M** Must · **S** Should.

---

## Performance & Latency (NFR-P)

| ID | Requirement | Target | Pri |
|----|-------------|--------|-----|
| NFR-P01 | Routing/gateway overhead on a cache-miss (excl. provider time). | p50 ≤ 15 ms, p99 ≤ 50 ms | M |
| NFR-P02 | Cache-hit response latency (exact match). | p99 ≤ 25 ms end-to-end | M |
| NFR-P03 | Semantic-cache lookup overhead. | p99 ≤ 40 ms | S |
| NFR-P04 | Streaming time-to-first-byte overhead vs. direct provider. | ≤ 20 ms added | M |
| NFR-P05 | Budget/quota check overhead per request. | ≤ 5 ms | M |
| NFR-P06 | Metering must be async/non-blocking on the request path. | 0 ms added p99 on hot path | M |

## Scalability & Capacity (NFR-S)

| ID | Requirement | Target | Pri |
|----|-------------|--------|-----|
| NFR-S01 | Sustained throughput per region. | ≥ 5,000 RPS steady, 10,000 RPS burst | M |
| NFR-S02 | Horizontal scalability of stateless services. | Linear to ≥ 50 replicas | M |
| NFR-S03 | Tenants supported per deployment (SaaS). | ≥ 500 active tenants | M |
| NFR-S04 | Monthly token accounting volume. | ≥ 5B tokens/month without degradation | M |
| NFR-S05 | Usage/metering write path throughput. | ≥ 10,000 records/s sustained | M |
| NFR-S06 | No single-tenant workload may degrade others (noisy-neighbor isolation). | Enforced via quotas/limits | M |

## Availability & Reliability (NFR-A)

| ID | Requirement | Target | Pri |
|----|-------------|--------|-----|
| NFR-A01 | Gateway control-plane + data-plane availability. | ≥ 99.95% monthly | M |
| NFR-A02 | Provider failover success (given ≥1 healthy provider). | ≥ 99.9% of failover-eligible requests | M |
| NFR-A03 | No single point of failure in the request path. | Redundant, multi-AZ | M |
| NFR-A04 | Graceful degradation when a dependency is down. | Documented fail-open/closed per feature | M |
| NFR-A05 | Recovery objectives. | RTO ≤ 30 min, RPO ≤ 5 min | M |
| NFR-A06 | Multi-region active-active option (SaaS). | Supported | S |

## Security (NFR-SEC)

| ID | Requirement | Target/Standard | Pri |
|----|-------------|-----------------|-----|
| NFR-SEC01 | Encrypt data in transit. | TLS 1.2+ everywhere | M |
| NFR-SEC02 | Encrypt data at rest. | AES-256 (DB, cache, backups) | M |
| NFR-SEC03 | Secrets never in source/DB plaintext. | External secrets manager | M |
| NFR-SEC04 | Application security baseline. | OWASP ASVS L2; Top 10 mitigated | M |
| NFR-SEC05 | AuthZ deny-by-default, least privilege. | Enforced | M |
| NFR-SEC06 | Dependency & container vulnerability scanning in CI. | Clean (no High/Critical) gate | M |
| NFR-SEC07 | Tenant isolation verified by automated tests. | No cross-tenant access | M |
| NFR-SEC08 | Rate limiting / abuse protection on all public endpoints. | Enforced | M |
| NFR-SEC09 | Audit trail integrity (tamper-evident). | Append-only/hash-chained | M |

## Privacy & Compliance (NFR-C)

| ID | Requirement | Pri |
|----|-------------|-----|
| NFR-C01 | Configurable PII handling (detect/redact/block) at the gateway. | M |
| NFR-C02 | Data-residency enforcement per tenant (region/provider constraints). | M |
| NFR-C03 | Configurable prompt/response retention & deletion (GDPR erasure support). | M |
| NFR-C04 | Architecture compatible with SOC 2 Type II / ISO 27001 controls. | S |
| NFR-C05 | Self-hosted mode keeps all data within customer boundary. | M |
| NFR-C06 | Data Processing Agreement-friendly logging (configurable, minimizable). | S |

## Maintainability & Extensibility (NFR-M)

| ID | Requirement | Pri |
|----|-------------|-----|
| NFR-M01 | Clean Architecture: domain independent of frameworks/providers. | M |
| NFR-M02 | SOLID; new providers/strategies added without modifying core (open/closed). | M |
| NFR-M03 | Strong typing (Pydantic v2 + mypy strict; TypeScript strict on frontend). | M |
| NFR-M04 | ≥ 90% meaningful test coverage where practical (per Quality Gates). | M |
| NFR-M05 | Enforced linting/formatting (ruff/black; eslint/prettier). | M |
| NFR-M06 | All public interfaces documented; ADRs for significant decisions. | M |

## Observability & Operability (NFR-O)

| ID | Requirement | Pri |
|----|-------------|-----|
| NFR-O01 | Golden-signal metrics + tracing + structured logs for every request. | M |
| NFR-O02 | SLOs defined with error budgets and burn-rate alerts. | M |
| NFR-O03 | Health/readiness/liveness endpoints for all services. | M |
| NFR-O04 | Runbooks for common incidents; documented rollback. | M |
| NFR-O05 | Metrics freshness (dashboard/analytics). | ≤ 60 s | S |

## Portability & Deployment (NFR-D)

| ID | Requirement | Pri |
|----|-------------|-----|
| NFR-D01 | One codebase serves SaaS multi-tenant and single-tenant self-hosted. | M |
| NFR-D02 | Containerized; runs on any conformant Kubernetes 1.29+. | M |
| NFR-D03 | Infrastructure as Code (Terraform) + Helm charts; reproducible. | M |
| NFR-D04 | No hard dependency on a single cloud provider's proprietary services for core function. | S |
| NFR-D05 | Air-gapped/restricted-egress deployment supported. | M |

## Cost-Efficiency (NFR-COST)

| ID | Requirement | Pri |
|----|-------------|-----|
| NFR-COST01 | Deliver net LLM cost reduction on covered traffic via cache + routing (target ≥ 25% where cacheable/right-sizable). | M |
| NFR-COST02 | Gateway infra cost per 1M requests kept within a documented budget envelope. | S |
| NFR-COST03 | Semantic cache must be net cost-positive (savings > embedding+storage cost) at target hit rates. | S |

## Accessibility & UX (NFR-UX)

| ID | Requirement | Pri |
|----|-------------|-----|
| NFR-UX01 | Admin dashboard meets WCAG 2.1 AA. | S |
| NFR-UX02 | API errors are actionable and documented. | M |

---

### Verification
Performance/scale NFRs are verified by load tests (Phase 13); availability/reliability by chaos
tests; security by SAST/DAST/dependency scans and isolation tests; the rest by inspection/analysis.
Targets may be revised once Phase 2 architecture and Phase 13 baselines exist — changes tracked via
ADR.
