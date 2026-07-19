# Assumptions & Constraints

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

Assumptions are stated so they can be challenged. Each has an ID; where an assumption is invalidated,
the linked requirements/risks must be revisited.

---

## 1. Product & scope assumptions

| ID | Assumption |
|----|-----------|
| ASM-01 | The product targets a **real commercial** market (SaaS + self-host), not a demo. Requirements are written to production standard. |
| ASM-02 | Both **multi-tenant SaaS** and **single-tenant self-hosted** modes ship from **one codebase**; differences are configuration-driven. |
| ASM-03 | Scale targets are **large-enterprise** (thousands of RPS, billions of tokens/month, hundreds of tenants). |
| ASM-04 | We integrate with existing LLM providers; we do **not** train/host foundation models. |
| ASM-05 | The primary client integration surface is an **OpenAI-compatible** API; clients can change base URL + key. |
| ASM-06 | Billing/invoicing is **out of scope for v1**; we produce accurate metering data consumed by external finance systems. |

## 2. Technical assumptions

| ID | Assumption |
|----|-----------|
| ASM-10 | Target runtime is **Kubernetes 1.29+**; services are containerized. |
| ASM-11 | **PostgreSQL 16 + `pgvector`** and **Redis 7+** are available (managed or self-operated). |
| ASM-12 | An **OIDC identity provider** (Okta/Azure AD/Google) is available for admin SSO. |
| ASM-13 | An external **secrets manager** (e.g., Vault, cloud KMS/secrets) is available. |
| ASM-14 | Providers expose reasonably stable APIs and return token usage (or it can be computed/estimated). |
| ASM-15 | Semantic caching uses an embedding model; in air-gapped mode a **self-hosted embedding model** is available, else semantic cache is disabled and exact cache still functions. |
| ASM-16 | Network egress in self-hosted mode can be restricted to **approved provider endpoints**. |

## 3. Business & operational assumptions

| ID | Assumption |
|----|-----------|
| ASM-20 | Customers accept a gateway in the request path given the latency budget in [`Non_Functional_Requirements.md`](Non_Functional_Requirements.md). |
| ASM-21 | Provider **price tables** can be maintained with effective-dated accuracy for metering. |
| ASM-22 | Enterprises value **cost governance + residency + self-host** enough to adopt over free OSS gateways. |
| ASM-23 | Compliance targets (SOC 2 / ISO 27001 alignment) are design goals for GA, not Phase-1 deliverables. |

## 4. Constraints (hard)

| ID | Constraint |
|----|-----------|
| CON-01 | No placeholder implementations; production quality per Quality Gates (project spec §12). |
| CON-02 | Clean Architecture + SOLID; strong typing; testing-first. |
| CON-03 | Secrets never committed to source or stored in plaintext. |
| CON-04 | One phase at a time; each gated by explicit approval; no jumping ahead. |
| CON-05 | Documentation lives under `/docs`; architecture under `/docs/architecture`; ADRs under `/docs/adr`. |

## 5. Open questions (to resolve before/with the relevant phase)

| ID | Question | Needed by |
|----|----------|-----------|
| OQ-01 | Default managed embedding model + dimensionality for semantic cache? | Phase 8 |
| OQ-02 | Do we expose a streaming-response cache path in v1, or exact/semantic only for non-streamed? | Phase 4/8 |
| OQ-03 | Billing integration timing and target system (Stripe/metering export)? | Post-v1 |
| OQ-04 | Async/eventing backbone for metering at scale: Redis Streams vs. Kafka/NATS? | Phase 2/7 |
| OQ-05 | Multi-region topology for SaaS: active-active vs. active-passive at GA? | Phase 2/12 |
| OQ-06 | PII detection approach: rules/regex + ML model; build vs. integrate? | Phase 9 |
| OQ-07 | Final RBAC role set and permission matrix granularity? | Phase 9 |

Resolutions will be recorded as ADRs under [`adr/`](adr/) and reflected back into the requirement
docs.
