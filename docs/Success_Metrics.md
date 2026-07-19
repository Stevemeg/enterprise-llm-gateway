# Success Metrics & KPIs

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

Metrics are grouped into **product/business**, **technical/SLO**, and **quality** tiers. Each metric
has a definition and an initial target. SLO targets align with
[`Non_Functional_Requirements.md`](Non_Functional_Requirements.md).

---

## 1. North-star metrics

| Metric | Definition | Why it matters |
|--------|-----------|----------------|
| **Governed traffic share** | % of an org's total LLM requests flowing through the gateway. | Measures whether we are the control plane, not a side tool. |
| **Net cost saved** | $ saved via cache + right-sizing vs. counterfactual direct spend, net of gateway cost. | The core customer value proposition. |

## 2. Product / business KPIs

| ID | KPI | Definition | Initial target |
|----|-----|-----------|----------------|
| SM-P01 | Cost reduction on covered traffic | (avoided provider cost) ÷ (counterfactual cost) | ≥ 25% where cacheable/right-sizable |
| SM-P02 | Cache hit rate | cache hits ÷ cacheable requests | ≥ 40% at steady state on eligible traffic |
| SM-P03 | Failover save rate | requests rescued by failover ÷ failover-eligible failures | ≥ 99% |
| SM-P04 | Time-to-integrate | median time for a new app to send first governed request | ≤ 1 day |
| SM-P05 | Governed traffic share (north-star) | see §1 | ≥ 80% within an adopting org |
| SM-P06 | Budget-enforcement correctness | overspend incidents past hard limits | 0 |
| SM-P07 | Provider portability | median effort to add/switch a provider | no app code change (config only) |

## 3. Technical / SLO KPIs

| ID | KPI | Definition | Target |
|----|-----|-----------|--------|
| SM-T01 | Gateway overhead (cache miss) | added latency excl. provider time | p99 ≤ 50 ms (NFR-P01) |
| SM-T02 | Cache-hit latency | end-to-end on exact hit | p99 ≤ 25 ms (NFR-P02) |
| SM-T03 | Availability | monthly uptime of request path | ≥ 99.95% (NFR-A01) |
| SM-T04 | Throughput | sustained RPS per region | ≥ 5,000 (NFR-S01) |
| SM-T05 | Error rate | gateway-attributable 5xx ÷ total | ≤ 0.1% |
| SM-T06 | Metering freshness | lag from request to queryable usage record | ≤ 60 s (NFR-O05) |
| SM-T07 | Cost accuracy | |computed − invoiced| ÷ invoiced | ≤ 2% |
| SM-T08 | RTO / RPO | recovery objectives | ≤ 30 min / ≤ 5 min (NFR-A05) |

## 4. Quality KPIs (engineering)

| ID | KPI | Target |
|----|-----|--------|
| SM-Q01 | Meaningful test coverage (where practical) | ≥ 90% (Quality Gates) |
| SM-Q02 | CI security scan | 0 High/Critical (NFR-SEC06) |
| SM-Q03 | Lint/format/type checks | pass (NFR-M03/M05) |
| SM-Q04 | Tenant-isolation tests | pass, 0 cross-tenant access (NFR-SEC07) |
| SM-Q05 | Documented ADRs for significant decisions | 100% of significant decisions |
| SM-Q06 | Acceptance criteria automated | ≥ 90% of Must ACs covered by tests |

## 5. Measurement & instrumentation

- Product/business KPIs are derived from **usage/metering records** (system of record) and the
  analytics layer (FR-070..077, FR-086..089).
- Technical/SLO KPIs come from **OpenTelemetry + Prometheus + Grafana** (FR-080..085).
- Quality KPIs are enforced in **CI** (Phase 11) and reported per release.
- Each KPI will have a defined **owner, dashboard, and review cadence** established in Phase 10.

## 6. Review cadence

- **Per phase gate:** confirm the phase's relevant KPIs are measurable and on-track.
- **Monthly (post-launch):** north-star + business KPIs.
- **Weekly (post-launch):** SLO burn and error budgets.

Targets are initial and will be recalibrated after Phase 13 load/chaos baselines; changes tracked via
ADR.
