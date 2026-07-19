# Risk Register

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

Risks are scored **Likelihood (L)** × **Impact (I)** on a 1–5 scale; **Score = L×I**. Each has an
owner-role and mitigation. Reviewed at each phase gate.

Severity band: 1–6 Low · 8–12 Medium · 15–25 High.

---

## Technical risks

| ID | Risk | L | I | Score | Mitigation |
|----|------|---|---|-------|------------|
| RISK-T01 | Gateway adds latency that erodes value (esp. streaming TTFB). | 3 | 4 | 12 | Strict overhead budget (NFR-P); async metering; benchmark from Phase 5; edge/co-location options. |
| RISK-T02 | Semantic cache returns wrong/stale answers (false positive similarity). | 3 | 4 | 12 | Conservative thresholds; tenant-scoped; per-policy opt-in; record similarity; easy invalidation (FR-054..058). |
| RISK-T03 | Budget enforcement races cause overspend under concurrency. | 3 | 5 | 15 | Atomic reserve/commit; most-restrictive-wins; load-test concurrency (FR-063, AC-US-040). |
| RISK-T04 | Provider API drift/breaking changes break adapters. | 4 | 3 | 12 | Adapter contract + contract tests; provider version pinning; fast-disable at runtime (FR-028). |
| RISK-T05 | Cross-tenant data leakage. | 2 | 5 | 10 | Deny-by-default; tenant scoping on every path; automated isolation tests (NFR-SEC07, FR-132). |
| RISK-T06 | Metering/cost inaccuracy vs. provider invoices erodes trust. | 3 | 4 | 12 | Effective-dated price tables; reconciliation tolerance tests (FR-074/075, AC-US-051). |
| RISK-T07 | Single codebase for SaaS + self-host accretes conditional complexity. | 3 | 3 | 9 | Config-driven boundaries; Clean Architecture; ADRs; parity tests (FR-141, NFR-D01). |
| RISK-T08 | Scaling the metering write path (10k rec/s) becomes a bottleneck. | 3 | 4 | 12 | Async pipeline; batching; evaluate stream backbone (OQ-04); load test (NFR-S05). |

## Security & compliance risks

| ID | Risk | L | I | Score | Mitigation |
|----|------|---|---|-------|------------|
| RISK-S01 | PII leaks to providers despite policy. | 3 | 5 | 15 | Gateway-side detection/redaction; fail-closed options; audit; tests (FR-110..112). |
| RISK-S02 | Audit log tampering undermines compliance. | 2 | 5 | 10 | Append-only/hash-chained; API cannot mutate; export for review (FR-113/114, NFR-SEC09). |
| RISK-S03 | Data-residency violation routes data out-of-region. | 2 | 5 | 10 | Residency policy excludes non-compliant routes; fail closed (FR-116/117). |
| RISK-S04 | Secret/credential exposure. | 2 | 5 | 10 | External secrets manager; hashed keys; scans; no plaintext (FR-022/097, NFR-SEC03). |
| RISK-S05 | Compliance posture (SOC2/ISO) slips vs. enterprise sales needs. | 3 | 4 | 12 | Design controls in from Phase 2; treat as GA gate (NFR-C04). |

## Product & market risks

| ID | Risk | L | I | Score | Mitigation |
|----|------|---|---|-------|------------|
| RISK-M01 | Basic routing commoditized by free OSS (LiteLLM/OpenRouter). | 4 | 3 | 12 | Differentiate on governance, cost-enforcement, dual-mode parity (see Competitor_Analysis §4). |
| RISK-M02 | Incumbents (Portkey/Kong/TrueFoundry) out-execute on governance/self-host. | 3 | 4 | 12 | Lead with dual-mode parity + cost-enforcement correctness as wedge. |
| RISK-M03 | Provider landscape shifts (pricing, concentration) faster than we adapt. | 4 | 3 | 12 | Provider-agnostic core; runtime enable/disable; effective-dated pricing. |
| RISK-M04 | Adoption friction: teams reluctant to add a hop in the critical path. | 3 | 4 | 12 | Low latency budget; drop-in OpenAI compatibility; clear ROI (cost-saved metric). |

## Operational & delivery risks

| ID | Risk | L | I | Score | Mitigation |
|----|------|---|---|-------|------------|
| RISK-O01 | Scope creep across 15 phases delays a usable core. | 4 | 3 | 12 | Strict phase gating; MoSCoW; milestone M1 = core inference path. |
| RISK-O02 | Operability gaps make the gateway itself an incident source. | 3 | 4 | 12 | Golden signals, SLOs, runbooks, health checks, safe rollback (NFR-O). |
| RISK-O03 | Self-hosted support burden (many customer environments). | 3 | 3 | 9 | Reproducible IaC/Helm; config validation; fail-fast startup (FR-144/146). |
| RISK-O04 | ≥90% coverage + quality gates slow delivery if retrofitted. | 3 | 3 | 9 | Testing-first from Phase 5; CI gates from Phase 11. |

---

### Top risks to watch (Score ≥ 15)
RISK-T03 (budget race → overspend), RISK-S01 (PII leak). Both are addressed by Must-level FRs and
must have dedicated tests before GA. Full mitigation traces via
[`Traceability_Matrix.md`](Traceability_Matrix.md).
