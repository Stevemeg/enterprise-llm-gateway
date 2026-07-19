# Project Overview — Enterprise LLM Gateway & Cost Router

**Document status:** Phase 1 (Discovery & Requirements) · Draft for approval
**Owner:** Principal Engineer / Technical Co-founder
**Last updated:** 2026-07-15

---

## 1. Elevator pitch

The Enterprise LLM Gateway & Cost Router is a self-hostable, multi-tenant control plane that sits
between enterprise applications and the full landscape of LLM providers (OpenAI, Anthropic, Google,
AWS Bedrock, Azure OpenAI, self-hosted open-weight models, and others). Applications integrate once
against a single OpenAI-compatible API; the gateway then handles provider routing, cost and latency
optimization, semantic caching, budget and quota enforcement, failover, governance, and end-to-end
observability. It gives platform, finance, and security teams centralized control over otherwise
sprawling, ungoverned LLM usage.

## 2. Problem statement

Enterprises have moved from LLM experimentation to production at scale. This creates four compounding
problems that point solutions do not solve together:

1. **Cost is opaque and unbounded.** Spend is spread across teams, providers, and API keys with no
   central attribution, no per-team budgets, and no automatic optimization. Enterprise model API
   spend exceeded **$8.4B in 2025** and is accelerating.
2. **Integration sprawl.** Every application integrates directly against each provider's bespoke SDK
   and auth model. Switching providers, adding fallbacks, or negotiating rates requires touching
   every app.
3. **Reliability risk.** A single provider outage, rate-limit, or regional degradation can take down
   customer-facing features with no automatic failover.
4. **Governance & security gaps.** No consistent enforcement of PII redaction, prompt/response
   logging policy, data residency, RBAC, or audit — a growing compliance liability.

## 3. Vision

> Become the default control plane for enterprise LLM traffic: one integration, total control.
> Every prompt is routed to the optimal model for its cost/latency/quality constraints, every dollar
> is attributable and governable, and every request is observable, secure, and compliant — whether
> the customer runs our SaaS or self-hosts inside their own cluster.

## 4. Goals and non-goals

### 4.1 Goals

- Provide a **single, provider-agnostic, OpenAI-compatible API** for chat, completions, and embeddings.
- **Intelligently route** each request based on cost, latency, availability, and policy, with
  automatic fallback.
- Reduce effective LLM spend via **semantic caching** and **model right-sizing**, targeting a
  meaningful net cost reduction at scale.
- Enforce **hard budgets and quotas** per tenant, team, and key, in real time.
- Deliver **first-class observability**: cost attribution, latency, token usage, cache hit rate, and
  per-request tracing.
- Ship **enterprise security & governance**: OAuth2/OIDC, JWT, RBAC, PII redaction, audit trails,
  data-residency controls.
- Support **two deployment modes from one codebase**: multi-tenant SaaS and single-tenant self-hosted.

### 4.2 Non-goals (for the initial product)

- We are **not** building or hosting foundation models ourselves.
- We are **not** building a general-purpose API gateway (e.g., replacing Kong for non-AI traffic).
- We are **not** building a prompt IDE, agent framework, or RAG application layer — though we expose
  the primitives those tools consume.
- We are **not** targeting on-device/edge inference in the initial release.

## 5. Target users (summary)

Detailed in [`User_Personas.md`](User_Personas.md). At a glance: **Platform/AI Infrastructure
Engineers** (integrate and operate the gateway), **Engineering Leaders & FinOps** (control cost and
attribution), **Security & Compliance Officers** (govern and audit), and **Application Developers**
(consume the API).

## 6. Deployment modes

| Mode                  | Description                                                                 | Primary drivers                          |
|-----------------------|-----------------------------------------------------------------------------|------------------------------------------|
| Multi-tenant SaaS     | Many orgs on shared infra with strong logical isolation, managed by us.     | Fast onboarding, no ops burden.          |
| Single-tenant self-hosted | Deployed into the customer's own VPC/Kubernetes; data never leaves their boundary. | Data residency, air-gap, compliance. |

Both modes are served from **one codebase** with configuration-driven differences. This constraint
shapes architecture (Phase 2) and NFRs (see [`Non_Functional_Requirements.md`](Non_Functional_Requirements.md)).

## 7. High-level capabilities

1. Unified OpenAI-compatible API (chat, completions, embeddings, streaming).
2. Provider abstraction layer with a pluggable adapter per provider.
3. Cost/latency/policy-aware routing engine with health-checked failover.
4. Semantic + exact-match response caching backed by `pgvector`/Redis.
5. Budget, quota, and rate-limit enforcement (tenant → team → key hierarchy).
6. Cost attribution, metering, and usage analytics.
7. Observability: metrics, traces, structured logs, dashboards, alerting.
8. Security & governance: authN/Z, RBAC, PII redaction, audit, data residency.
9. Admin dashboard (Next.js) for configuration, keys, budgets, and analytics.

## 8. Success criteria (summary)

Detailed in [`Success_Metrics.md`](Success_Metrics.md). Headline targets: measurable **net cost
reduction** on covered traffic via caching + routing, **99.95% gateway availability**, **p99 routing
overhead within a tight budget**, and demonstrable **budget-enforcement correctness**.

## 9. Scope of Phase 1

This phase produces **requirements documentation only** — no application code. Deliverables are
enumerated in [`docs/README.md`](README.md). Architecture, database, and API design follow in later,
separately-approved phases.

## 10. Related documents

- [`PRD.md`](PRD.md) — product requirements
- [`SRS.md`](SRS.md) — software requirements specification
- [`Functional_Requirements.md`](Functional_Requirements.md) · [`Non_Functional_Requirements.md`](Non_Functional_Requirements.md)
- [`Competitor_Analysis.md`](Competitor_Analysis.md) · [`Risks.md`](Risks.md) · [`Assumptions.md`](Assumptions.md)
- [`Success_Metrics.md`](Success_Metrics.md) · [`Glossary.md`](Glossary.md)
