# Architecture Decision Records (ADRs)

An ADR captures a single significant architectural decision: the context/problem, the alternatives
considered, the decision, and its consequences. ADRs are immutable once **Accepted** — to change a
decision we add a new ADR that **supersedes** the old one (the old one is marked accordingly, never
deleted). This preserves the reasoning trail.

Format follows a Nygard-style ADR extended with explicit alternative comparison and requirement
traceability, as mandated by the project workflow.

## Status legend

`Proposed` · `Accepted` · `Superseded by ADR-XXXX` · `Deprecated`

## Index

| ADR | Title | Status | Blocking decision resolved |
|-----|-------|--------|----------------------------|
| [0000](0000-record-architecture-decisions.md) | Record architecture decisions (use ADRs) | Accepted | — |
| [0001](0001-clean-architecture-and-runtime.md) | Clean/Hexagonal architecture & backend runtime | Accepted | — (foundational) |
| [0002](0002-multi-tenant-isolation-model.md) | Multi-tenant isolation model | Accepted | Multi-tenancy |
| [0003](0003-provider-abstraction-strategy.md) | Provider Abstraction Layer strategy | Accepted | **Provider abstraction** |
| [0004](0004-reserve-commit-cost-accounting.md) | Reserve/Commit cost-accounting model | Accepted | **Reserve vs Commit** |
| [0005](0005-eventing-backbone.md) | Eventing backbone | Accepted | **Eventing backbone** |
| [0006](0006-semantic-cache-architecture.md) | Semantic cache architecture | Accepted | **Semantic cache** |
| [0007](0007-embedding-strategy.md) | Embedding strategy | Accepted | **Embedding strategy** |
| [0008](0008-rbac-model.md) | Authorization / RBAC model | Accepted | **RBAC model** |
| [0009](0009-fail-open-fail-closed-matrix.md) | Fail-open vs fail-closed behavior matrix | Accepted | **Fail-open/closed** |
| [0010](0010-multi-region-strategy.md) | Multi-region strategy | Accepted | **Multi-region** |
| [0011](0011-self-hosted-deployment-architecture.md) | Self-hosted deployment architecture | Accepted | **Self-host deployment** |
| [0012](0012-intelligent-routing-engine.md) | Intelligent routing engine design | Accepted | (routing) |
| [0013](0013-service-account-credential-storage.md) | Service-account credential storage | Proposed | (schema change) |
| [0014](0014-runtime-database-role-rls-enforcement.md) | Non-superuser runtime DB role for RLS enforcement | Accepted | (security/infra) |
| [0015](0015-oidc-login-state-storage.md) | OIDC login-state storage & RLS bootstrapping | Accepted | (schema change) |
| [0016](0016-enterprise-ai-os-architecture.md) | Evolution to an Enterprise AI Operating System | Proposed | (architecture) |
| [0017](0017-postgres-transactional-budget-reservation.md) | PostgreSQL-transactional reserve/commit as the interim hard-budget mechanism | Accepted | (scopes ADR-0004's mechanism, does not reverse it) |

All nine Phase-1 architecture-blocking questions are resolved by the ADRs marked in **bold**. A
tabular cross-reference of every decision is in
[`../Architecture_Decision_Log.md`](../Architecture_Decision_Log.md).

## Template

```markdown
# ADR-XXXX: <Title>

- **Status:** Proposed | Accepted | Superseded by ADR-YYYY
- **Date:** YYYY-MM-DD
- **Deciders:** <roles>
- **Phase:** 2 — Architecture

## Context & problem
<What forces are at play? What must the decision satisfy?>

## Decision drivers
<Requirements/constraints, referencing FR-###/NFR-### and Risks.>

## Options considered
### Option A — <name>
Pros / Cons.
### Option B — <name>
Pros / Cons.
### Option C — <name>
Pros / Cons.

## Decision
<Chosen option and the technical justification.>

## Consequences
Positive / Negative / Follow-ups.

## Requirements satisfied
- Functional: FR-###, …
- Non-functional: NFR-###, …

## Review notes
<When/why we would revisit this.>
```
