# Product Requirements Document (PRD)

**Product:** Enterprise LLM Gateway & Cost Router
**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

---

## 1. Purpose

Define *what* the product must do and *why*, from a product/business perspective, so that
architecture, API, and implementation phases have an unambiguous, agreed foundation. This PRD is
the bridge between the vision ([`Project_Overview.md`](Project_Overview.md)) and the engineering
specification ([`SRS.md`](SRS.md)).

## 2. Market context

- Enterprise model API spend exceeded **$8.4B in 2025**; the enterprise LLM market is projected to
  grow from **~$11.3B (2026) to ~$71.1B (2034), ~25.8% CAGR**.
- The LLM middleware/gateway layer is growing even faster (**~49.6% CAGR**), with **~42% of
  enterprises** already running a gateway between apps and providers, and enterprise LLM adoption
  crossing **80% in 2026**.
- Provider concentration is shifting (Anthropic ~40% of enterprise API spend, OpenAI ~27%), which
  makes **provider portability and multi-provider routing** a strategic buyer requirement rather
  than a nice-to-have.

Full landscape in [`Competitor_Analysis.md`](Competitor_Analysis.md).

## 3. Product positioning

> For enterprise platform, FinOps, and security teams who need to control cost, reliability, and
> governance of production LLM usage, the Enterprise LLM Gateway & Cost Router is a self-hostable,
> multi-tenant control plane that unifies all LLM providers behind one API with intelligent routing,
> caching, budgets, and audit. Unlike SaaS-only gateways (Portkey, OpenRouter) or ops-heavy API
> meshes (Kong AI Gateway), it delivers **both** turnkey SaaS **and** true single-tenant self-hosting
> from one codebase, with cost governance as a first-class primitive rather than an add-on.

### 3.1 Differentiators

1. **Dual deployment parity** — identical feature set in SaaS and self-hosted, unlike SaaS-only
   competitors and unlike open-source tools that lack managed governance.
2. **Cost governance as a core primitive** — hierarchical budgets/quotas with hard enforcement and
   real-time attribution, not just dashboards.
3. **Routing that optimizes on cost + latency + quality + policy**, with health-checked failover.
4. **Governance built in** — PII redaction, data residency, RBAC, and immutable audit at the gateway
   layer.

## 4. Personas & jobs-to-be-done

Summarized here; full detail in [`User_Personas.md`](User_Personas.md).

| Persona | Job-to-be-done |
|---------|----------------|
| Priya — Platform/AI Infra Engineer | "Give my org one reliable, governed way to call any model." |
| Marcus — Eng Leader / FinOps | "Make LLM spend predictable, attributable, and optimized." |
| Sofia — Security & Compliance Officer | "Ensure every LLM request is governed, auditable, and compliant." |
| Dev — Application Developer | "Call the best model with one API and not worry about keys or outages." |
| Ops — SRE / Platform Operator | "Run the gateway reliably and see what it's doing." |

## 5. Product scope

### 5.1 In scope (v1)

- Unified OpenAI-compatible API: chat, completions, embeddings, streaming.
- Provider adapters for the major commercial providers and a generic OpenAI-compatible/self-hosted
  adapter.
- Routing engine: policy-, cost-, latency-, and availability-aware, with fallback chains.
- Semantic + exact caching with configurable TTL and invalidation.
- Hierarchical budgets, quotas, and rate limits (tenant → team → virtual key).
- Cost metering, attribution, and usage analytics.
- Observability: metrics, distributed tracing, structured logs, dashboards, alerts.
- Security & governance: OAuth2/OIDC, JWT, RBAC, API/virtual keys, PII redaction, audit log, data
  residency controls.
- Admin dashboard (Next.js) for configuration and analytics.
- Both deployment modes (SaaS multi-tenant; single-tenant self-hosted).

### 5.2 Out of scope (v1)

- Hosting/training foundation models.
- Non-AI API gateway functionality.
- Agent orchestration, prompt IDE, or RAG application layer.
- Fine-tuning management, human-labeling, or eval platforms (may be future phases).
- Billing/payment processing integration (metering data is produced; invoicing is external in v1).

## 6. Product requirements (capability level)

Each maps to functional requirements (FR-###) in [`Functional_Requirements.md`](Functional_Requirements.md).

| ID    | Capability                              | Priority | Maps to |
|-------|-----------------------------------------|----------|---------|
| PR-01 | Unified inference API (OpenAI-compatible) | Must   | FR-001..FR-010 |
| PR-02 | Provider abstraction & adapters         | Must     | FR-020..FR-029 |
| PR-03 | Intelligent routing & failover          | Must     | FR-030..FR-041 |
| PR-04 | Semantic & exact caching                | Must     | FR-050..FR-058 |
| PR-05 | Budgets, quotas & rate limiting         | Must     | FR-060..FR-069 |
| PR-06 | Cost metering & attribution             | Must     | FR-070..FR-077 |
| PR-07 | Observability & analytics               | Must     | FR-080..FR-089 |
| PR-08 | AuthN/AuthZ, RBAC & key management       | Must    | FR-090..FR-101 |
| PR-09 | Governance: PII redaction, audit, residency | Must | FR-110..FR-119 |
| PR-10 | Admin dashboard                         | Should   | FR-120..FR-129 |
| PR-11 | Multi-tenancy & isolation               | Must     | FR-130..FR-138 |
| PR-12 | Self-hosted deployability               | Must     | FR-140..FR-146 |

Prioritization uses MoSCoW (Must / Should / Could / Won't-yet).

## 7. Release strategy (indicative)

Phases 5–15 will deliver capability increments. Indicative milestone framing (subject to
architecture approval):

- **M1 — Core inference path:** unified API + provider adapters + basic routing + auth/keys.
- **M2 — Cost control:** budgets/quotas + metering + attribution + dashboard basics.
- **M3 — Optimization:** semantic cache + advanced routing + failover.
- **M4 — Governance & scale:** PII redaction, audit, data residency, multi-region, hardening.

## 8. Assumptions, constraints, dependencies

- See [`Assumptions.md`](Assumptions.md) and [`Risks.md`](Risks.md).
- Hard constraint: **one codebase serves both deployment modes**.
- Hard constraint: **no placeholder implementations**; production quality per project Quality Gates.

## 9. Success metrics

See [`Success_Metrics.md`](Success_Metrics.md). Business north-star: **net LLM cost reduction
delivered to customers**; product north-star: **share of an org's LLM traffic flowing through the
gateway**.

## 10. Open questions

Tracked in [`Assumptions.md`](Assumptions.md) §"Open questions". Notable items: default managed
embedding model for semantic cache; whether v1 exposes a streaming-cache path; billing integration
timing.
