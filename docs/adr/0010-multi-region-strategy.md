# ADR-0010: Multi-region strategy

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, SRE, Security Architect
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** Multi-region strategy
- **Resolves open question:** OQ-05 (SaaS multi-region topology)

## Context & problem
SaaS must meet **99.95% availability** (NFR-A01), **RTO ≤30 min / RPO ≤5 min** (NFR-A05), have **no
single point of failure** (NFR-A03), support **data residency** so a tenant's data stays in permitted
regions (NFR-C02, FR-116/117), and scale horizontally (NFR-S01/S02). We must decide the regional
topology and the data-consistency model that backs budget enforcement (which is latency-sensitive and
correctness-critical, [ADR-0004](0004-reserve-commit-cost-accounting.md)). Self-host is typically
single-region (customer's cluster) and must not be burdened by SaaS multi-region complexity.

## Decision drivers
- NFR-A01/A03/A05 (availability, no SPOF, RTO/RPO), NFR-C02/FR-116-117 (residency), NFR-S01/S02
  (scale), NFR-D01 (one codebase), ADR-0004 (budget correctness).

## Options considered
### Option A — Single-region, multi-AZ (HA within one region)
- **Pros:** Simplest; strong consistency; meets HA within a region.
- **Cons:** A full-region outage breaks RTO/RPO; can't satisfy residency for multiple jurisdictions.
  Good as a baseline, not sufficient for large-enterprise SaaS.

### Option B — **Global active-active** with a globally-distributed database (multi-master)
- **Pros:** Lowest latency everywhere; survives region loss transparently.
- **Cons:** Multi-master conflict resolution is hard precisely for **monotonic budget counters** (risk
  of double-spend across regions — worsens RISK-T03); higher cost/complexity; residency becomes harder
  (data may replicate globally). Over-engineered and risky for the budget invariant.

### Option C — **Regional cells (cell-based), active-active across regions but single-writer per tenant**, with data pinned to a tenant's **home region** for residency
Each region is a self-contained **cell** (full stack: API, workers, Postgres, Redis). A tenant is
**assigned a home region** (residency) and is **served active** there; other regions can serve
read/failover. Budget counters and the ledger for a tenant are **owned by the home region** (single
writer → preserves ADR-0004 atomicity, no cross-region double-spend). Cross-region **failover** is
active-passive *per tenant* (promote a standby replica in a partner region) to meet RTO/RPO without
multi-master conflicts.
- **Pros:** Residency by construction (tenant data pinned to home region, FR-116/117); budget
  correctness preserved (single-writer per tenant, no distributed double-spend); region loss handled by
  per-tenant failover within RTO/RPO; cells scale independently (NFR-S02); blast radius contained.
- **Cons:** Cross-region failover requires replication + promotion runbooks; a tenant is briefly
  read-only/unavailable during promotion (bounded by RTO). More orchestration than single-region.

## Decision
Adopt **Option C — cell-based, region-per-cell, single-writer-per-tenant** for SaaS. Tenants are pinned
to a **home region** for residency (FR-116/117, NFR-C02). Within a region: **multi-AZ** for HA and no
SPOF (NFR-A03). Across regions: **asynchronous replication** of Postgres (streaming replica, RPO ≤5 min)
and a **documented promotion procedure** (RTO ≤30 min) → per-tenant active-passive failover. Budget
Redis counters and the Postgres ledger are **owned by the home region** (single writer) so
[ADR-0004](0004-reserve-commit-cost-accounting.md)'s atomicity holds globally without multi-master
conflicts. Global traffic is fronted by **latency/geo + health-based routing** to the correct cell.
**Self-host** uses a **single cell (single region, multi-AZ optional)** — the same code, multi-region
features simply disabled by config (NFR-D01, [ADR-0011](0011-self-hosted-deployment-architecture.md)).
Active-active multi-master (Option B) is explicitly rejected to protect the budget invariant.

## Consequences
- **Positive:** Meets availability/RTO/RPO and residency simultaneously; preserves budget correctness
  globally; independent cell scaling; contained blast radius; clean self-host reduction.
- **Negative:** Failover promotion runbooks/automation to build and drill; brief per-tenant read-only
  window during promotion; cross-region replication cost.
- **Follow-ups:** Phase 12 implements cells (Terraform/Helm), replication, and promotion automation;
  Phase 13 chaos-tests region failover against RTO/RPO; global router configured in Phase 12.

## Requirements satisfied
- Functional: FR-116, FR-117, FR-133, FR-140, FR-141.
- Non-functional: NFR-A01, NFR-A03, NFR-A05, NFR-A06, NFR-C02, NFR-C05, NFR-S02, NFR-D01.

## Review notes
Revisit for active-active *per-tenant* only if a customer needs sub-region-loss zero-downtime writes
AND we solve the budget-counter conflict (e.g., regional sub-budgets) — would be a superseding ADR.
