# C4 — Level 1: System Context

**Scope:** The Enterprise LLM Gateway & Cost Router as a black box among its users and external systems.
Back to [Architecture](../../Architecture.md) · [C4 index](README.md).

```mermaid
C4Context
    title System Context — Enterprise LLM Gateway & Cost Router

    Person(dev, "Application Developer", "Builds features on LLMs; calls the unified API")
    Person(admin, "Platform / FinOps / Security Admin", "Manages providers, budgets, policies, keys, audit")
    Person(tenantAdmin, "Tenant Administrator", "Manages their org's teams, keys, budgets (SaaS)")

    System(gw, "LLM Gateway & Cost Router", "Unified OpenAI-compatible API with routing, caching, budgets, governance, observability")

    System_Ext(apps, "Enterprise Applications", "Client apps/services using LLMs")
    System_Ext(idp, "Identity Provider (OIDC)", "Okta / Azure AD / Google — admin SSO")
    System_Ext(secrets, "Secrets Manager", "Cloud KMS / Vault")
    System_Ext(providers, "LLM Providers", "OpenAI, Anthropic, Google, Bedrock, Azure OpenAI, self-hosted models")
    System_Ext(telemetry, "Telemetry Backends", "Prometheus / Grafana / OTel collector")
    System_Ext(notify, "Notification Channels", "Email / Slack / webhook for alerts")

    Rel(apps, gw, "Inference requests", "HTTPS / OpenAI-compatible + SSE")
    Rel(dev, gw, "Integrates & tests", "HTTPS")
    Rel(admin, gw, "Administers", "HTTPS (OIDC/JWT)")
    Rel(tenantAdmin, gw, "Self-service admin", "HTTPS (OIDC/JWT)")
    Rel(gw, providers, "Routed model calls", "HTTPS (per-provider)")
    Rel(gw, idp, "Authenticates admins", "OIDC")
    Rel(gw, secrets, "Fetches credentials/keys", "TLS")
    Rel(gw, telemetry, "Exports metrics/traces/logs", "OTLP / scrape")
    Rel(gw, notify, "Budget & SLO alerts", "HTTPS")
```

## Notes
- The gateway is the **single integration point** for client apps (FR-001..010) — apps change only base
  URL + key (AC-US-001).
- In **self-hosted/air-gapped** mode, external systems collapse into the customer boundary: IdP, secrets,
  and telemetry are in-cluster, and providers are restricted to an approved egress allow-list
  ([ADR-0011](../../adr/0011-self-hosted-deployment-architecture.md), FR-142/143).
- Trust boundaries over this context are detailed in
  [security/trust-boundaries](../security/01-trust-boundaries.md).

**Requirements:** FR-001..010, FR-090..093, FR-140..143; NFR-D05, NFR-C05.
