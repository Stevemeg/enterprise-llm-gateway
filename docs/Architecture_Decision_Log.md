# Architecture Decision Log

**Phase:** 2 — Architecture · Draft for approval
**Last updated:** 2026-07-15

Quick-reference summary of every major architectural decision (also serves as design-review / interview
prep). Full reasoning lives in each linked [ADR](adr/). All nine Phase-1 architecture-blocking questions
are resolved (marked ✅ **Blocking**).

## Legend
FR/NFR columns list the primary requirements each decision satisfies (not exhaustive — see the ADR).

---

### AD-01 — Use ADRs to record decisions
- **Problem:** Long, multi-phase build needs a durable, reviewable decision trail.
- **Chosen:** Markdown ADRs in-repo, immutable + superseding, with FR/NFR traceability.
- **Alternatives:** Single design doc; external wiki.
- **Why:** Versioned with code, diff-able, air-gap-available, satisfies decision-workflow mandate.
- **Advantages:** Transparent, low-friction, doubles as interview material.
- **Disadvantages:** Authoring discipline.
- **FR:** — · **NFR:** NFR-M06 · **ADR:** [0000](adr/0000-record-architecture-decisions.md) · **Review:** if tooling changes.

### AD-02 — Clean/Hexagonal architecture + async FastAPI runtime
- **Problem:** Maintainable, extensible core; one codebase → two modes; low overhead at high RPS.
- **Chosen:** Hexagonal (Ports & Adapters) + Clean layering; Python 3.12 + FastAPI async; modular monolith of stateless processes.
- **Alternatives:** N-tier layered; framework-centric (Django) / Go / Node.
- **Why:** Swappable adapters (open/closed), testable domain, async fits I/O-bound proxy, mode differences isolated to composition root.
- **Advantages:** Extensibility, testability, one codebase both modes.
- **Disadvantages:** Upfront structure + dependency-rule discipline.
- **FR:** FR-025/026/141 · **NFR:** NFR-M01/M02/M03/M04, NFR-P01/P04, NFR-D01 · **ADR:** [0001](adr/0001-clean-architecture-and-runtime.md) · **Review:** extract services if a module's scaling diverges.

### AD-03 — Multi-tenant isolation: shared schema + `tenant_id` + RLS ✅ Blocking (multi-tenancy)
- **Problem:** Guarantee no cross-tenant access at hundreds of tenants; reduce cleanly to single-tenant.
- **Chosen:** Shared schema, `tenant_id` on every row, PostgreSQL **RLS** as DB backstop under app scoping (defense in depth).
- **Alternatives:** DB-per-tenant; schema-per-tenant.
- **Why:** Economical at scale, single migration path, DB-enforced isolation even if app misses a filter, trivial single-tenant reduction.
- **Advantages:** Scales, defense-in-depth, one code path both modes.
- **Disadvantages:** Correctness depends on tenant-context propagation → relentless isolation tests.
- **FR:** FR-130..134/138 · **NFR:** NFR-SEC07, NFR-S03/S06, NFR-D01 · **ADR:** [0002](adr/0002-multi-tenant-isolation-model.md) · **Review:** add dedicated-instance escape hatch for whale/regulated tenants.

### AD-04 — Provider Abstraction Layer (first-party Port + Adapters) ✅ Blocking (provider abstraction)
- **Problem:** Many heterogeneous providers; add/disable without touching core; survive API drift.
- **Chosen:** First-party `LLMProviderPort` + adapter per provider + registry; canonical model + normalized error taxonomy; generic OpenAI-compatible adapter; contract tests.
- **Alternatives:** Adopt a third-party unifying SDK as core; direct per-provider integration.
- **Why:** Own the latency/governance/error seams; open/closed extensibility; drift caught at adapter boundary.
- **Advantages:** Control, extensibility, uniform failover.
- **Disadvantages:** We maintain adapters (bounded by contract tests + runtime disable).
- **FR:** FR-020..029 · **NFR:** NFR-M02, NFR-P01/P04, NFR-A02 · **ADR:** [0003](adr/0003-provider-abstraction-strategy.md) · **Review:** revisit wrap-3rd-party-for-long-tail boundary yearly.

### AD-05 — Reserve/Commit cost accounting ✅ Blocking (reserve vs commit)
- **Problem:** Hard budget enforcement, correct under concurrency, but true cost known only post-call and metering must not block.
- **Chosen:** **Reserve (atomic Redis Lua, most-restrictive-first) → Commit (async ledger in Postgres) → Release**; reconciler repairs counters.
- **Alternatives:** Post-hoc accounting only; synchronous ledger transaction per request.
- **Why:** Atomic ≤5 ms enforcement kills overspend race; async durable ledger keeps accuracy without blocking.
- **Advantages:** Correct + fast + accurate + scalable.
- **Disadvantages:** Two surfaces need reconciliation; Redis is enforcement-critical (HA + fail-closed).
- **FR:** FR-060..073 · **NFR:** NFR-P05/P06, NFR-S05 · **ADR:** [0004](adr/0004-reserve-commit-cost-accounting.md) · **Review:** revisit estimator if reconciliation drift high or provider usage unreliable.

### AD-06 — Eventing backbone: Redis Streams default, Kafka-pluggable ✅ Blocking (eventing)
- **Problem:** Off-path durable events ≥10k/s; must run air-gapped self-host with minimal ops AND scale for SaaS.
- **Chosen:** `EventBus` port; **Redis Streams** default adapter (both modes); Kafka/Redpanda adapter for high-scale SaaS; idempotent consumers + DLQ.
- **Alternatives:** Kafka everywhere; cloud-managed queue.
- **Why:** No new dependency for self-host/air-gap; pluggable to scale; no cloud lock-in.
- **Advantages:** Minimal surface, air-gap-friendly, scalable via adapter.
- **Disadvantages:** Idempotency mandatory; Redis retention/memory managed; two adapters at top tier.
- **FR:** FR-066/070-077/086-088/113 · **NFR:** NFR-S05/P06/A05/D01/D05/M02 · **ADR:** [0005](adr/0005-eventing-backbone.md) · **Review:** define RPS threshold to flip SaaS default to Kafka.

### AD-07 — Semantic cache: two-tier Redis exact + pgvector semantic ✅ Blocking (semantic cache)
- **Problem:** Capture near-duplicate savings without cross-tenant leaks, false positives, or new datastore; tight latency.
- **Chosen:** Exact (Redis) → semantic (`pgvector` HNSW), tenant-scoped, per-policy threshold + score logging, opt-in, easy disable.
- **Alternatives:** Exact-only; external vector DB.
- **Why:** Reuses mandated stores (air-gap-friendly), meets latency, isolation via RLS, conservative thresholds mitigate false positives.
- **Advantages:** Cost savings + speed + isolation + no new dependency.
- **Disadvantages:** Threshold tuning; pgvector scaling monitored.
- **FR:** FR-050..058 · **NFR:** NFR-P02/P03, NFR-COST01/03, NFR-SEC07, NFR-D05 · **ADR:** [0006](adr/0006-semantic-cache-architecture.md) · **Review:** swap to dedicated vector DB only if pgvector misses NFR-P03 at scale.

### AD-08 — Embedding strategy: local-default, pluggable, versioned ✅ Blocking (embedding)
- **Problem:** Embeddings for semantic cache must work air-gapped, respect governance, meet latency, stay swappable.
- **Chosen:** `EmbeddingProvider` port; **bundled local model default** + optional external; async population; vectors tagged model/version/dim; re-embed on model change.
- **Alternatives:** External-only; local-only.
- **Why:** Air-gap-safe default, governance-aware, cost-controlled, upgrade-safe via versioning.
- **Advantages:** Works everywhere; no silent vector-space mixing.
- **Disadvantages:** Operate local model; maintain re-embedding migration.
- **FR:** FR-054-056/058, FR-110-112 · **NFR:** NFR-P03, NFR-COST03, NFR-D05, NFR-M02, NFR-C05 · **ADR:** [0007](adr/0007-embedding-strategy.md) · **Review:** update default model as landscape evolves (versioned migration).

### AD-09 — Authorization: RBAC over permission catalog ✅ Blocking (RBAC)
- **Problem:** Two principal types; least-privilege, deny-by-default, same rules in API+UI, separation of duties, auditable.
- **Chosen:** RBAC (owner/admin/operator/finance/auditor/developer) over a fine-grained permission catalog behind `AuthorizationPort`; OIDC/JWT for humans, scoped virtual keys for apps; ABAC-ready.
- **Alternatives:** Hard-coded checks; full ABAC/OPA now.
- **Why:** Enterprise-recognizable roles + fine-grained perms, one decision point, extensible later.
- **Advantages:** Separation of duties, centralized/testable, tenant-scoped.
- **Disadvantages:** Maintain role→permission matrix; coarser than ABAC (accepted).
- **FR:** FR-090..101/128/129/135-137 · **NFR:** NFR-SEC04/05/09 · **ADR:** [0008](adr/0008-rbac-model.md) · **Review:** add ABAC adapter if attribute policies needed.

### AD-10 — Fail-open vs fail-closed behavior matrix ✅ Blocking (fail-open/closed)
- **Problem:** Each dependency failure needs a *correct* mode; wrong default breaches compliance or availability.
- **Chosen:** Per-feature matrix — **fail closed** for integrity/security/financial controls; **fail open (degrade)** for availability-neutral enrichments; safe-direction tenant overrides only.
- **Alternatives:** Global fail-open; global fail-closed.
- **Why:** Correct bias per concern; satisfies NFR-A04's "documented per feature".
- **Advantages:** Governance never silently bypassed; availability preserved for optimizations.
- **Disadvantages:** More conditional handling + chaos tests.
- **FR:** FR-034-038/061/067/110-117/146 · **NFR:** NFR-A01/A02/A04/A05, NFR-SEC*, NFR-C02, NFR-P06 · **ADR:** [0009](adr/0009-fail-open-fail-closed-matrix.md) · **Review:** every new dependency adds a row; revisit after chaos tests.

### AD-11 — Multi-region: cell-per-region, single-writer-per-tenant ✅ Blocking (multi-region)
- **Problem:** Availability + RTO/RPO + residency + budget correctness together.
- **Chosen:** Regional **cells**, multi-AZ within region; tenant pinned to home region; per-tenant active-passive cross-region failover; **single writer per tenant** for budget/ledger.
- **Alternatives:** Single-region multi-AZ; global active-active multi-master.
- **Why:** Residency by construction; preserves budget atomicity (no distributed double-spend); region-loss handled within RTO/RPO; independent cell scaling.
- **Advantages:** Availability + residency + correctness + blast-radius containment.
- **Disadvantages:** Failover runbooks/automation; brief per-tenant read-only during promotion.
- **FR:** FR-116/117/133/140/141 · **NFR:** NFR-A01/A03/A05/A06, NFR-C02/C05, NFR-S02, NFR-D01 · **ADR:** [0010](adr/0010-multi-region-strategy.md) · **Review:** per-tenant active-active only if we solve counter conflicts.

### AD-12 — Self-hosted: one codebase, Helm, single cell, air-gap-ready ✅ Blocking (self-host)
- **Problem:** Feature-parity self-host from one codebase, air-gapped, in-boundary data, reproducible, safe upgrades.
- **Chosen:** Same images + Helm chart, single cell, `self_hosted` profile; private registry + egress allow-list + local embeddings + in-cluster telemetry; fail-fast startup; Helm rollback. No fork.
- **Alternatives:** Separate community fork; docker-compose only.
- **Why:** True parity + no divergence; enterprise-grade HA/upgrades; air-gap first-class; cloud-neutral.
- **Advantages:** Parity, regulated/air-gap support, portability.
- **Disadvantages:** K8s prerequisite; heterogeneous-cluster support (bounded by IaC + validation + runbooks).
- **FR:** FR-140..146 · **NFR:** NFR-D01..D05, NFR-C05, NFR-O03/O04 · **ADR:** [0011](adr/0011-self-hosted-deployment-architecture.md) · **Review:** consider single-node appliance if demand emerges.

### AD-14 — Service-account credential storage (schema change) ✅ Schema
- **Problem:** `service_account` had no credential column; client-credential auth impossible.
- **Chosen:** dedicated `service_account_credential` table (hashed secret, client_id, status, rotation).
- **Alternatives:** columns on `service_account`; reuse `api_key`.
- **Why:** rotation with grace, lifecycle separation, mirrors api_key; RLS-scoped; hash-only.
- **Advantages:** secure + rotatable + no outage. **Disadvantages:** one more table.
- **FR:** FR-098/097/093/096 · **NFR:** NFR-SEC03/04/05 · **ADR:** [0013](adr/0013-service-account-credential-storage.md) · **Migration:** 0002 · **Review:** external/mTLS identity would be a new ADR.

### AD-13 — Intelligent routing: composable strategy pipeline
- **Problem:** Optimal, explainable routing within policy + residency, with bounded failover; extensible.
- **Chosen:** Eligibility filter (fail closed) → ranking strategy (`cost/latency/quality/weighted/pinned`) → decision record → bounded failover + circuit breaking → optional right-sizing/fallback/canary; `RoutingStrategyPort`.
- **Alternatives:** Static rules table; ML/bandit adaptive router.
- **Why:** Deterministic + explainable + governable; extensible (new strategy = adapter); residency enforced pre-ranking; ML can be a future strategy.
- **Advantages:** Intelligent yet explainable; failover/residency correct by construction; predictable overhead.
- **Disadvantages:** Per-tenant tuning; not self-learning in v1.
- **FR:** FR-030..041/116/117 · **NFR:** NFR-P01, NFR-A02, NFR-M02 · **ADR:** [0012](adr/0012-intelligent-routing-engine.md) · **Review:** add adaptive strategy once feedback/eval loop exists.

---

## Blocking-question resolution summary

| Phase-1 blocking question | Resolved by | Decision (one line) |
|---------------------------|-------------|---------------------|
| Reserve vs Commit cost accounting | AD-05 / ADR-0004 | Reserve (Redis Lua) → async Commit (Postgres ledger) |
| Eventing backbone | AD-06 / ADR-0005 | Redis Streams default, Kafka-pluggable, behind a port |
| Multi-region strategy | AD-11 / ADR-0010 | Cell-per-region, single-writer-per-tenant, residency-pinned |
| Semantic cache architecture | AD-07 / ADR-0006 | Two-tier Redis exact + pgvector semantic, tenant-scoped |
| Self-host deployment | AD-12 / ADR-0011 | One codebase + Helm single cell, air-gap-ready, no fork |
| Fail-open vs fail-closed | AD-10 / ADR-0009 | Per-feature matrix; integrity closed, enrichments open |
| Embedding strategy | AD-08 / ADR-0007 | Local-default pluggable, versioned, governance-aware |
| RBAC model | AD-09 / ADR-0008 | RBAC over permission catalog behind AuthorizationPort |
| Provider abstraction | AD-04 / ADR-0003 | First-party Port+Adapters + registry + contract tests |

Related open questions resolved: **OQ-01** (embedding model → AD-08), **OQ-04** (eventing → AD-06),
**OQ-05** (multi-region → AD-11), **OQ-07** (RBAC roles → AD-09). Remaining open questions (OQ-02
streaming-cache path, OQ-03 billing timing, OQ-06 PII detector build/buy) are non-blocking for
architecture and scheduled for Phases 4/8/9 respectively (see [Assumptions](Assumptions.md)).
