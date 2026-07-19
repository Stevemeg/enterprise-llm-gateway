# ADR-0011: Self-hosted deployment architecture

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, DevOps Architect, Security Architect
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** Self-host deployment architecture

## Context & problem
The product ships as **single-tenant self-hosted** into a customer's own VPC/Kubernetes, with **feature
parity** to SaaS (FR-140), driven by **configuration from one codebase** (FR-141, NFR-D01), supporting
**air-gapped/restricted egress** (FR-142, NFR-D05), keeping **all data in the customer boundary**
(FR-143, NFR-C05), and **reproducible with health checks and rollback** (FR-144/145, NFR-O03). We must
avoid two codebases or a divergent "lite" edition, and avoid hard dependencies on any single cloud's
proprietary services for core function (NFR-D04).

## Decision drivers
- FR-140..146 (parity, config-driven, air-gap, in-boundary data, reproducible, health, safe startup).
- NFR-D01..D05 (one codebase, K8s, IaC, cloud-neutral, air-gap), NFR-C05, NFR-O03, NFR-O04, RISK-O03.

## Options considered
### Option A — Separate self-hosted fork / "community edition" codebase
- **Pros:** Can trim dependencies.
- **Cons:** Divergence, double maintenance, parity drift, security-patch lag. Directly violates NFR-D01.
  Rejected.

### Option B — Single container image, `docker-compose` only
- **Pros:** Easiest to run for tiny installs.
- **Cons:** No parity with SaaS's K8s HA/scaling; weak upgrades/rollback; not enterprise-grade.
  Rejected as the primary path (may exist as an evaluation quickstart).

### Option C — **One codebase → Helm chart on Kubernetes**, cloud-neutral, config/profile-driven, air-gap-ready
Same container images as SaaS; a **Helm chart** deploys the full stack (API, workers, PostgreSQL+
pgvector, Redis) as a **single cell** ([ADR-0010](0010-multi-region-strategy.md)) with multi-tenant
features collapsed to one tenant ([ADR-0002](0002-multi-tenant-isolation-model.md)). A **deployment
profile** (`saas` | `self_hosted`) selected in the composition root toggles multi-region, external
telemetry, and embedding backend defaults. Dependencies are **portable** (in-cluster Postgres/Redis or
customer-managed) with **no hard tie to a single cloud's proprietary services** (NFR-D04); secrets via
a pluggable secrets provider (in-cluster or the customer's Vault/KMS). **Air-gap**: all images
pre-pulled to a private registry; egress allow-list limited to approved provider endpoints; semantic
cache uses the **bundled local embedding model** ([ADR-0007](0007-embedding-strategy.md)); telemetry
stays in-cluster unless the customer configures export (FR-143, NFR-C05). **Startup validation** fails
fast on misconfiguration (FR-146); health/readiness/liveness endpoints and **Helm-based rollback**
provide safe operations (FR-145, NFR-O03/O04).
- **Pros:** True parity, one codebase, enterprise-grade HA/upgrades, air-gap-ready, cloud-neutral.
- **Cons:** Customers must run Kubernetes; supporting heterogeneous customer clusters is a support load
  (RISK-O03) — mitigated by reproducible IaC, config validation, and documented runbooks.

## Decision
Adopt **Option C**: **identical images + a Helm chart**, deployed as a **single cell**, with a
**`self_hosted` profile** toggling SaaS-only features off — **no fork, no lite edition** (NFR-D01,
FR-140/141). Air-gapped operation is first-class (private registry, egress allow-list, local
embeddings, in-cluster telemetry — FR-142/143). Terraform modules provision the cluster/data stores for
customers who want them; the chart runs on any conformant K8s (NFR-D02/D03). Startup performs strict
config validation and fails fast (FR-146). Upgrades/rollbacks are Helm-native with health-gated
rollout (FR-145, NFR-O04). A `docker-compose` quickstart may exist for **evaluation only**, explicitly
not the production path.

## Consequences
- **Positive:** One codebase serves both modes with real parity; regulated/air-gapped customers fully
  supported; cloud-neutral; reproducible and safely operable.
- **Negative:** Kubernetes is a customer prerequisite; multi-environment support burden (bounded by
  IaC + validation + runbooks).
- **Follow-ups:** Phase 11/12 build images, Helm chart, Terraform modules, air-gap bundle, and upgrade/
  rollback runbooks; Phase 13 tests air-gapped install + rollback (AC-US-110/111).

## Requirements satisfied
- Functional: FR-140, FR-141, FR-142, FR-143, FR-144, FR-145, FR-146.
- Non-functional: NFR-D01, NFR-D02, NFR-D03, NFR-D04, NFR-D05, NFR-C05, NFR-O03, NFR-O04.

## Review notes
Revisit if demand emerges for a managed-Kubernetes-free option (e.g., a single-node appliance);
would be an additional packaging ADR, not a code fork.
