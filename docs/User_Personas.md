# User Personas

**Document status:** Phase 1 · Draft for approval
**Last updated:** 2026-07-15

These personas ground the requirements. Each persona has an ID used in the
[`Traceability_Matrix.md`](Traceability_Matrix.md).

---

## P-01 · Priya — Platform / AI Infrastructure Engineer (Primary buyer-user)

- **Role:** Owns the internal AI platform for a large enterprise; 500+ developers depend on her team.
- **Context:** Multiple products call OpenAI, Anthropic, Bedrock, and two self-hosted open-weight
  models. Integrations are duplicated and inconsistent.
- **Goals:** One governed integration point; add/swap providers without app changes; enforce policy
  centrally; keep latency overhead negligible.
- **Frustrations:** Per-app provider SDKs; no central failover; every outage becomes her pager.
- **Success looks like:** Apps call one endpoint; she manages providers, routing, and keys from one
  place; failover is automatic.
- **Key requirements:** PR-01, PR-02, PR-03, PR-08, PR-11, PR-12.

## P-02 · Marcus — Engineering Leader / FinOps Partner (Economic buyer)

- **Role:** VP Engineering with budget accountability; partners with a FinOps analyst.
- **Context:** LLM spend grew 6× in a year and is unattributable across teams.
- **Goals:** Predictable, attributable spend; per-team budgets with hard stops; provable cost
  reduction from caching and model right-sizing.
- **Frustrations:** Surprise invoices; no chargeback/showback; no lever to cut cost without breaking
  apps.
- **Success looks like:** Real-time spend by team/app/model; budgets that actually enforce; a monthly
  "cost saved" number he can defend.
- **Key requirements:** PR-05, PR-06, PR-03 (cost-aware routing), PR-04, PR-07, PR-10.

## P-03 · Sofia — Security & Compliance Officer (Gatekeeper)

- **Role:** Responsible for data protection, regulatory compliance, and vendor risk.
- **Context:** Regulated industry; some data must never leave the corporate boundary or a specific
  region.
- **Goals:** Enforce PII redaction; guarantee data residency; immutable audit of every request;
  least-privilege RBAC; approve self-hosting for sensitive workloads.
- **Frustrations:** LLM calls that bypass DLP; no audit trail; SaaS tools that can't self-host.
- **Success looks like:** Policy enforced at the gateway; complete, tamper-evident audit; self-hosted
  option for sensitive tenants.
- **Key requirements:** PR-09, PR-08, PR-11, PR-12, plus security NFRs.

## P-04 · Dev — Application Developer (Primary daily user)

- **Role:** Builds product features on top of LLMs.
- **Context:** Wants to ship; doesn't want to manage provider keys, retries, or failover.
- **Goals:** One API and SDK; best model auto-selected within policy; sensible errors; streaming.
- **Frustrations:** Juggling provider quirks; rate-limit handling; broken prod when a provider blips.
- **Success looks like:** Swaps base URL + key, keeps OpenAI-style code, gets routing/caching/failover
  for free.
- **Key requirements:** PR-01, PR-03, PR-04.

## P-05 · Ops — SRE / Platform Operator (Operator-user)

- **Role:** Keeps the gateway itself reliable in production.
- **Context:** Runs it on Kubernetes across regions; on call for it.
- **Goals:** Clear SLOs; health checks; metrics/traces/logs; safe rollouts and rollbacks; capacity
  planning.
- **Frustrations:** Opaque systems; no golden signals; risky deploys.
- **Success looks like:** Dashboards for the four golden signals; automated health checks; documented
  runbooks and rollback.
- **Key requirements:** PR-07, plus availability/observability/portability NFRs.

## P-06 · Ana — Tenant Administrator (SaaS customer admin) *(secondary)*

- **Role:** Admin for a customer organization on the SaaS offering.
- **Goals:** Manage her org's teams, virtual keys, budgets, and members; see her org's usage; never
  see other tenants' data.
- **Success looks like:** Self-service org administration with strict tenant isolation.
- **Key requirements:** PR-05, PR-06, PR-08, PR-10, PR-11.

---

### Persona → priority summary

| Persona | Type | Top capabilities |
|---------|------|------------------|
| P-01 Priya | Platform engineer | Unified API, routing, providers, multi-tenancy, self-host |
| P-02 Marcus | FinOps/leader | Budgets, metering, cost-aware routing, analytics |
| P-03 Sofia | Security/compliance | Governance, RBAC, residency, audit, self-host |
| P-04 Dev | App developer | Unified API, routing, caching |
| P-05 Ops | SRE | Observability, availability, portability |
| P-06 Ana | Tenant admin | Org admin, budgets, isolation |
