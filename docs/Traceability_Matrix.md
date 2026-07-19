# Requirements Traceability Matrix

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

Ensures every capability traces from persona → user story → functional requirements → acceptance
criteria, and that key NFRs are owned. No requirement should be orphaned; no story unimplemented.

---

## 1. Capability → Story → FR → Acceptance

| PRD Cap | Epic | Stories | FRs | Acceptance | Personas |
|---------|------|---------|-----|-----------|----------|
| PR-01 Unified API | A | US-001..004 | FR-001..010 | AC-US-001/002/004 | P-04 |
| PR-02 Providers | B | US-010..012 | FR-020..029 | AC-US-010/011/012 | P-01 |
| PR-03 Routing/failover | C | US-020..023 | FR-030..041 | AC-US-020/021/022 | P-01, P-02, P-04 |
| PR-04 Caching | D | US-030..032 | FR-050..058 | AC-US-030/031/032 | P-02, P-03, P-04 |
| PR-05 Budgets/quotas | E | US-040..042 | FR-060..069 | AC-US-040/042 | P-02, P-06 |
| PR-06 Metering | F | US-050..052 | FR-070..077 | AC-US-050/051 | P-02 |
| PR-07 Observability | G | US-060..062 | FR-080..089 | AC-US-060/061 | P-05, P-02, P-06 |
| PR-08 Auth/RBAC/keys | H | US-070..072 | FR-090..101 | AC-US-070/071/072 | P-01, P-03, P-04, P-06 |
| PR-09 Governance | I | US-080..082 | FR-110..119 | AC-US-080/081/082 | P-03 |
| PR-10 Dashboard | J | US-090..091 | FR-120..129 | (UI E2E, Phase 13) | P-01, P-02, P-06 |
| PR-11 Multi-tenancy | K | US-100..101 | FR-130..138 | AC-US-100 | P-03, P-01, P-06 |
| PR-12 Self-host | L | US-110..111 | FR-140..146 | AC-US-110/111 | P-01, P-03, P-05 |

## 2. Persona coverage check

| Persona | Appears in stories | Covered? |
|---------|--------------------|----------|
| P-01 Platform engineer | US-010,011,012,020,022,070,090,100,110 | ✅ |
| P-02 FinOps/leader | US-020,023,030,031,040,042,050,051,052,062,091 | ✅ |
| P-03 Security/compliance | US-032,072,080,081,082,100,110 | ✅ |
| P-04 App developer | US-001,002,003,004,021,030,071 | ✅ |
| P-05 SRE | US-060,061,111 | ✅ |
| P-06 Tenant admin | US-041,062,071,090,091,101 | ✅ |

All six personas appear in at least one **Must** story. ✅

## 3. FR coverage check

| FR block | Range | Owned by story | Orphans? |
|----------|-------|----------------|----------|
| Unified API | FR-001..010 | US-001..004 | none |
| Providers | FR-020..029 | US-010..012 | none |
| Routing | FR-030..041 | US-020..023 | none |
| Caching | FR-050..058 | US-030..032 | none |
| Budgets | FR-060..069 | US-040..042 | none |
| Metering | FR-070..077 | US-050..052 | none |
| Observability | FR-080..089 | US-060..062 | none |
| Auth/RBAC | FR-090..101 | US-070..072 | none |
| Governance | FR-110..119 | US-080..082 | none |
| Dashboard | FR-120..129 | US-090..091 | none |
| Multi-tenancy | FR-130..138 | US-100..101 | none |
| Self-host | FR-140..146 | US-110..111 | none |

Every FR block is owned by at least one story. ✅

## 4. Key NFR → driver → verification

| NFR | Driver | Verification (Phase 13) |
|-----|--------|-------------------------|
| NFR-P01/02/04 latency | US-001/002, US-030 | Load test overhead & TTFB |
| NFR-S01..05 scale | US-020, US-050 | Load test to target RPS/tokens |
| NFR-A01..05 availability | US-021/022, US-111 | Chaos test failover & recovery |
| NFR-SEC* security | US-070..072, US-080..082 | SAST/DAST, isolation tests |
| NFR-C* compliance | US-080..082, US-110 | Policy/residency tests |
| NFR-D01/05 portability | US-110/111 | SaaS+self-host parity + air-gap test |
| NFR-COST01 savings | US-023, US-030/031 | Cost-saved measurement |

## 5. Risk → mitigating requirement

| Risk | Mitigated by |
|------|--------------|
| RISK-T03 budget race | FR-063, AC-US-040 |
| RISK-S01 PII leak | FR-110..112, AC-US-080 |
| RISK-T05 cross-tenant | FR-132, NFR-SEC07, AC-US-100 |
| RISK-T02 bad semantic hit | FR-054..058, AC-US-031/032 |
| RISK-S03 residency | FR-116/117, AC-US-082 |
| RISK-T06 cost accuracy | FR-074/075, AC-US-051 |

---

### Result
No orphaned requirements, no uncovered personas, all Must capabilities traced end-to-end. This matrix
is updated whenever requirements change (via ADR).
