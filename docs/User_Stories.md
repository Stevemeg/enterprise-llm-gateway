# User Stories

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

Stories are grouped by epic. Each has an ID (US-###), a persona, a MoSCoW priority, and the FRs it
drives. Acceptance criteria are in [`Acceptance_Criteria.md`](Acceptance_Criteria.md) (keyed by story
ID). Traceability in [`Traceability_Matrix.md`](Traceability_Matrix.md).

Format: *As a `<persona>`, I want `<capability>`, so that `<benefit>`.*

---

## Epic A — Unified Inference API

- **US-001** (P-04, Must, FR-001..FR-006) — As a developer, I want an OpenAI-compatible chat/completions
  endpoint, so that I can migrate by changing only base URL and key.
- **US-002** (P-04, Must, FR-007) — As a developer, I want streaming responses, so that my UI can render
  tokens as they arrive.
- **US-003** (P-04, Must, FR-008) — As a developer, I want an embeddings endpoint, so that I can build
  vector features through the same gateway.
- **US-004** (P-04, Must, FR-009, FR-010) — As a developer, I want consistent, typed error responses, so
  that I can handle failures predictably regardless of provider.

## Epic B — Provider Abstraction

- **US-010** (P-01, Must, FR-020..FR-024) — As a platform engineer, I want to register providers and models
  with credentials and metadata, so that the gateway can call them.
- **US-011** (P-01, Must, FR-025..FR-027) — As a platform engineer, I want a uniform adapter contract, so
  that adding a new provider doesn't change application code.
- **US-012** (P-01, Should, FR-028, FR-029) — As a platform engineer, I want to enable/disable providers and
  models at runtime, so that I can respond to incidents or pricing changes without redeploying.

## Epic C — Intelligent Routing & Failover

- **US-020** (P-01/P-02, Must, FR-030..FR-033) — As a platform/FinOps owner, I want routing policies based on
  cost, latency, and quality tier, so that each request goes to the optimal model.
- **US-021** (P-04, Must, FR-034..FR-036) — As a developer, I want automatic failover to a healthy provider,
  so that a single provider outage doesn't break my feature.
- **US-022** (P-01, Should, FR-037, FR-038) — As a platform engineer, I want health checks and circuit
  breaking per provider, so that unhealthy providers are removed from rotation automatically.
- **US-023** (P-02, Should, FR-039..FR-041) — As a FinOps partner, I want model right-sizing rules (e.g., cheap
  model first, escalate on low confidence), so that we cut cost without hurting quality.

## Epic D — Caching

- **US-030** (P-02/P-04, Must, FR-050..FR-053) — As a FinOps partner, I want exact-match response caching, so
  that identical requests don't incur repeat provider cost.
- **US-031** (P-02, Should, FR-054..FR-056) — As a FinOps partner, I want semantic caching of similar prompts,
  so that near-duplicate requests are served from cache within a similarity threshold.
- **US-032** (P-03, Must, FR-057, FR-058) — As a security officer, I want cache scoping and invalidation
  controls, so that cached data respects tenant isolation and TTL/policy.

## Epic E — Budgets, Quotas & Rate Limiting

- **US-040** (P-02, Must, FR-060..FR-063) — As a FinOps partner, I want hierarchical budgets (tenant→team→key)
  with hard stops, so that spend cannot exceed approved limits.
- **US-041** (P-06, Must, FR-064, FR-065) — As a tenant admin, I want per-key rate limits and quotas, so that
  one app can't starve others.
- **US-042** (P-02, Should, FR-066..FR-069) — As a FinOps partner, I want threshold alerts (e.g., 80/100%), so
  that teams are warned before enforcement kicks in.

## Epic F — Cost Metering & Attribution

- **US-050** (P-02, Must, FR-070..FR-073) — As a FinOps partner, I want every request metered (tokens, model,
  cost) and attributed to tenant/team/key, so that I can do showback/chargeback.
- **US-051** (P-02, Must, FR-074, FR-075) — As a FinOps partner, I want accurate provider price tables, so that
  computed costs match invoices within tolerance.
- **US-052** (P-02, Should, FR-076, FR-077) — As a FinOps partner, I want exportable usage data, so that I can
  reconcile with finance systems.

## Epic G — Observability & Analytics

- **US-060** (P-05, Must, FR-080..FR-083) — As an SRE, I want metrics, traces, and structured logs for every
  request, so that I can debug and meet SLOs.
- **US-061** (P-05, Must, FR-084, FR-085) — As an SRE, I want dashboards for the four golden signals plus cache
  hit rate and cost, so that I can operate the gateway.
- **US-062** (P-02/P-06, Should, FR-086..FR-089) — As a FinOps partner/tenant admin, I want usage & cost
  analytics in the dashboard, so that I can self-serve insights.

## Epic H — AuthN/AuthZ, RBAC & Keys

- **US-070** (P-01, Must, FR-090..FR-093) — As a platform engineer, I want OAuth2/OIDC + JWT for admin access,
  so that we use corporate SSO.
- **US-071** (P-04/P-06, Must, FR-094..FR-097) — As a developer/tenant admin, I want virtual API keys with
  scopes, so that apps authenticate with least privilege.
- **US-072** (P-03, Must, FR-098..FR-101) — As a security officer, I want RBAC roles, so that access to
  budgets, keys, and audit is least-privilege.

## Epic I — Governance: PII, Audit, Residency

- **US-080** (P-03, Must, FR-110..FR-112) — As a security officer, I want configurable PII detection/redaction
  on prompts and responses, so that sensitive data is protected.
- **US-081** (P-03, Must, FR-113..FR-115) — As a security officer, I want an immutable, tamper-evident audit
  log of admin and inference events, so that we pass audits.
- **US-082** (P-03, Must, FR-116..FR-119) — As a security officer, I want data-residency routing controls, so
  that requests only use providers/regions permitted for a tenant.

## Epic J — Admin Dashboard

- **US-090** (P-01/P-06, Should, FR-120..FR-124) — As an admin, I want a UI to manage providers, keys, budgets,
  and routing, so that I don't need to script every change.
- **US-091** (P-02/P-06, Should, FR-125..FR-129) — As a FinOps/tenant admin, I want usage & cost views in the
  UI, so that I can monitor and act.

## Epic K — Multi-Tenancy & Isolation

- **US-100** (P-03/P-01, Must, FR-130..FR-134) — As a security/platform owner, I want strict tenant isolation
  of data, keys, and config, so that no tenant can access another's data.
- **US-101** (P-06, Must, FR-135..FR-138) — As a tenant admin, I want to manage my org's teams and members, so
  that administration is self-service and scoped.

## Epic L — Self-Hosted Deployability

- **US-110** (P-01/P-03, Must, FR-140..FR-143) — As a platform/security owner, I want a single-tenant
  self-hosted deployment with the same features, so that sensitive workloads never leave our boundary.
- **US-111** (P-05, Must, FR-144..FR-146) — As an SRE, I want documented, reproducible deployment (Helm/Terraform)
  with health checks and rollback, so that I can operate it safely.

---

### Coverage note
Every persona (P-01…P-06) appears in at least one Must story, and every capability PR-01…PR-12 in
[`PRD.md`](PRD.md) is represented. Verified in [`Traceability_Matrix.md`](Traceability_Matrix.md).
