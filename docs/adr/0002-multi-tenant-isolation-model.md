# ADR-0002: Multi-tenant isolation model

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, Security Architect, Database Architect
- **Phase:** 2 — Architecture

## Context & problem
The SaaS mode hosts hundreds of tenants on shared infrastructure (NFR-S03) and must guarantee that no
tenant can ever read another tenant's data, keys, usage, cache, or audit (FR-130..134, NFR-SEC07,
RISK-T05 score 10). The self-hosted mode is single-tenant. We need one isolation model that is strong
enough for shared multi-tenancy, cost-efficient at hundreds of tenants, and degrades cleanly to a
single-tenant deployment — all from one codebase.

## Decision drivers
- FR-130..134 (tenant as top-level boundary; isolate all data; enforce scoping on every path).
- NFR-SEC07 (tenant isolation verified by automated tests), NFR-S03 (≥500 tenants), NFR-S06
  (noisy-neighbor isolation), NFR-D01 (one codebase → both modes).
- RISK-T05 (cross-tenant leakage), RISK-T07 (single-codebase complexity).

## Options considered
### Option A — Database-per-tenant
- **Pros:** Strongest physical isolation; simple per-tenant backup/residency.
- **Cons:** Hundreds of DBs/connection pools → operationally heavy and costly at NFR-S03 scale;
  migrations fan out; cross-tenant analytics hard. Overkill for shared SaaS economics.

### Option B — Schema-per-tenant (one DB, N schemas)
- **Pros:** Logical isolation; single DB to operate.
- **Cons:** Hundreds of schemas strain migrations and the catalog; connection/prepared-statement
  churn; still heavy at target scale.

### Option C — Shared schema with a mandatory `tenant_id` on every row + PostgreSQL Row-Level Security (RLS)
- **Pros:** Scales to many tenants cheaply; single migration path; **defense in depth** — app-layer
  tenant scoping *plus* database-enforced RLS so a missed `WHERE` cannot leak data; simplest reduction
  to single-tenant (one tenant row). Fits large-enterprise economics.
- **Cons:** Correctness depends on setting the session tenant context on every connection; requires
  rigorous testing; noisy-neighbor must be handled at the quota layer, not the DB.

## Decision
Adopt **Option C**: **shared-schema multi-tenancy with a non-null `tenant_id` on every tenant-owned
table and PostgreSQL Row-Level Security** as a hard backstop. The application sets a per-request
tenant context (from the authenticated principal / virtual key) that (a) scopes every repository
query and (b) is bound to the DB session so RLS policies filter rows automatically. Tenant context is
established once, at the edge, and propagated through the request/use-case boundary; **deny-by-default**
if absent. Noisy-neighbor isolation (NFR-S06) is enforced by per-tenant quotas/rate limits
([ADR-0004](0004-reserve-commit-cost-accounting.md), FR-064, FR-138), not by DB partitioning.
Optional per-tenant **encryption context** and, for the highest-sensitivity SaaS tenants, an escape
hatch to dedicated schema/instance is left as a documented future option (not v1).

Self-hosted mode uses the identical model with exactly one tenant, so code paths are shared and
tested once (NFR-D01).

## Consequences
- **Positive:** Meets isolation guarantees with defense-in-depth; economical at hundreds of tenants;
  one migration path; trivial single-tenant reduction.
- **Negative:** RLS + app scoping must be verified relentlessly; a bug in tenant-context propagation
  is high-severity — mitigated by mandatory automated **cross-tenant isolation tests** (NFR-SEC07) in
  CI and by RLS catching app-layer misses.
- **Follow-ups:** Phase 3 encodes `tenant_id` + RLS policies in the schema; Phase 13 adds isolation
  test suite; large-tenant "dedicated" escape hatch tracked as a future ADR.

## Requirements satisfied
- Functional: FR-130, FR-131, FR-132, FR-133, FR-134, FR-138.
- Non-functional: NFR-SEC07, NFR-S03, NFR-S06, NFR-D01.

## Review notes
Revisit if a whale tenant's volume or a regulatory demand requires physical isolation — introduce the
dedicated-instance path as a superseding/complementary ADR rather than changing the default.
