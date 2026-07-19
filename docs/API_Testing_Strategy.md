# API Testing Strategy

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

How the API contract is validated — from spec linting now to full conformance/load/security testing in
Phase 13. No test code is written in Phase 4; this defines the plan and acceptance bar (Quality Gates,
spec §12).

## 1. Test layers
| Layer | What it verifies | When |
|-------|------------------|------|
| **Spec validation** | OpenAPI 3.1 valid; all `$ref` resolve; unique operationIds; tags/responses present | now (Phase 4) + CI |
| **API linting** | Governance rules ([`API_Governance.md`](API_Governance.md)): naming, envelopes, error coverage, security per op | CI (Phase 11) |
| **Contract tests** | Requests/responses conform to schemas; examples validate; SDKs match spec (mock server) | Phase 5/13 |
| **Unit** | Handler/validation/authz logic | Phase 5–9 |
| **Integration** | Real DB + Redis: auth, RBAC, tenant isolation, budget reserve/commit, cache, routing | Phase 13 |
| **E2E** | Full inference path incl. streaming, failover, governance | Phase 13 |
| **Load** | Latency/throughput budgets (NFR-P/S) | Phase 13 |
| **Chaos** | Failover, dependency-loss fail modes (ADR-0009) | Phase 13 |
| **Security** | Authn/z, isolation, injection, headers (OWASP, NFR-SEC) | Phase 13 |

## 2. Contract & conformance testing
- **Schema conformance:** every endpoint's request/response validated against the OpenAPI schemas
  (Dredd/Schemathesis-style property testing generates inputs from the spec).
- **Examples-as-tests:** the examples in [`API_Examples.md`](API_Examples.md) and spec `examples` are
  executed against a mock/real server and must pass.
- **SDK contract tests:** each generated SDK ([`API_SDK_Guidelines.md`](API_SDK_Guidelines.md)) runs against
  a spec-derived mock to guarantee lock-step with the contract.

## 3. Behavior test matrix (maps to acceptance criteria)
| Scenario | Asserts | Ref |
|----------|---------|-----|
| OpenAI-compatible chat | shape matches; base-URL swap works | AC-US-001, FR-001 |
| Streaming SSE | ordered chunks + `[DONE]`; TTFB overhead | FR-007, NFR-P04 |
| Consistent errors | every non-2xx = `Error`; code→type→status stable | FR-009, API_Error_Model |
| Insufficient scope | chat-key on embeddings → 403 | AC-US-071 |
| Budget hard stop | 402 before provider call; **concurrency: no overspend** | AC-US-040, RISK-T03 |
| Idempotent retry | duplicate POST → one effect | FR-036, API_Idempotency |
| Rate limit | 429 + `Retry-After` + `RateLimit` | FR-065 |
| Failover | primary down → served by fallback | AC-US-021 |
| Semantic cache isolation | tenants never share cache | AC-US-032, FR-057 |
| Residency block | non-compliant route → fail closed | AC-US-082, FR-117 |
| Tenant isolation | no cross-tenant reads on any admin path | AC-US-100, NFR-SEC07 |
| Auditor read-only | budget write → 403 + audited | AC-US-072 |
| Pagination stability | keyset stable under inserts | Pagination doc |

## 4. Security testing
- AuthN/Z bypass attempts, JWT tampering, key-scope escalation, RLS/tenant-isolation probes, injection
  (SQL/prompt), header hardening, secret-leak scans on all error/response bodies (FR-010).
- Runs as CI gate (SAST/DAST + dependency/container scan, NFR-SEC06) and Phase-13 pen-style tests.

## 5. Performance/load testing (Phase 13)
- Assert NFR-P01/P02/P04/P05 (overhead, cache hit, TTFB, budget check), NFR-S01/S05 (RPS, metering rate),
  keyset pagination under large tables, ANN latency (NFR-P03). Feeds index/pooling tuning back to
  [`Query_Performance_Guide.md`](Query_Performance_Guide.md).

## 6. CI gates (Phase 11)
Spec must validate; linter must pass; contract tests green; coverage ≥90% meaningful on API handlers;
security scan clean; changelog present for spec changes ([`API_Changelog_Policy.md`](API_Changelog_Policy.md)).
A failing gate blocks merge/release (Quality Gates §12).

## 7. Tooling (indicative, finalized in Phase 11/13)
`openapi-spec-validator` (done here), Spectral (lint), Schemathesis/Dredd (conformance), pytest/httpx +
testcontainers (integration), k6/Locust (load), OWASP ZAP + Semgrep (security).

## 8. Traceability
Quality Gates (spec §12), NFR-M04 (coverage), all AC-US-* and NFR-SEC*/P*/S* above; complements
[`architecture/security/02-threat-model-stride.md`](architecture/security/02-threat-model-stride.md).
