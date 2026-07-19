# ADR-0006: Semantic cache architecture

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, AI Platform Engineer, Security Architect
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** Semantic cache architecture

## Context & problem
Caching is a core cost lever (SM-P01 ≥25% savings, SM-P02 ≥40% hit rate). We need both **exact-match**
caching (FR-050) and **semantic** caching that serves a response for a prompt sufficiently similar to a
prior one (FR-054..056), while guaranteeing **tenant isolation** (FR-057, no cross-tenant serving) and
**correct invalidation** (FR-058). The danger is a false-positive semantic hit returning a wrong/stale
answer (RISK-T02, score 12). Latency budgets are tight: exact hit p99 ≤25 ms (NFR-P02), semantic
lookup overhead p99 ≤40 ms (NFR-P03). The cache must be net cost-positive (NFR-COST03).

## Decision drivers
- FR-050..058 (exact + semantic cache, config, flags, scoping, invalidation).
- NFR-P02/P03 (latency), NFR-COST03 (net positive), NFR-SEC07/FR-057 (tenant isolation), RISK-T02
  (false positives).

## Options considered
### Option A — Exact-match only (hash of normalized request), no semantic layer
- **Pros:** Trivial, fast, zero false positives.
- **Cons:** Leaves most savings on the table (near-duplicate prompts miss). Insufficient for SM-P01/P02.

### Option B — Semantic-only via an external vector database (Pinecone/Weaviate/Milvus)
- **Pros:** Purpose-built ANN performance at scale.
- **Cons:** New external dependency (cost, ops, air-gap problems for self-host, NFR-D05); another data
  store to isolate per-tenant and keep consistent with responses; over-engineered given we already run
  PostgreSQL. Rejected as default.

### Option C — **Two-tier: exact (Redis) + semantic (PostgreSQL + `pgvector`)**, tenant-scoped, gated
- **Tier 1 — Exact:** normalized-request hash → response in **Redis** (sub-ms), TTL per policy
  (FR-050..053).
- **Tier 2 — Semantic:** on exact miss (and only for cacheable, low-variance requests), embed the
  prompt ([ADR-0007](0007-embedding-strategy.md)) and run a **`pgvector` ANN search** (HNSW index)
  **within the tenant's partition**, returning a hit only above a **per-policy similarity threshold**
  (FR-055) and recording the **similarity score + source entry** (FR-056) for auditability.
- **Pros:** Reuses mandated stores (no new dependency; air-gap-friendly, NFR-D05); `pgvector` HNSW
  meets the ≤40 ms budget at expected volumes; tenant isolation via `tenant_id` + RLS
  ([ADR-0002](0002-multi-tenant-isolation-model.md)); conservative thresholds + auditability directly
  mitigate RISK-T02; invalidation by TTL, explicit purge, and model/version change (FR-058).
- **Cons:** `pgvector` at extreme scale may need tuning/partitioning vs a dedicated vector DB; embedding
  adds cost/latency (bounded by gating + the exact tier).

## Decision
Adopt **Option C** — a **two-tier cache**: Redis exact-match in front of a `pgvector` semantic tier,
both strictly **tenant-scoped**. Semantic caching is **opt-in per policy** and applied only to
**cacheable, deterministic-enough** requests (FR-053: high-temperature/randomness requests bypass
cache). Hits require score ≥ threshold (default conservative), carry the **similarity score and source
id** in the response/trace (FR-052, FR-056), and never cross tenant boundaries (FR-057). Invalidation
is driven by TTL, manual purge, and model/version change (FR-058). Embeddings are produced
asynchronously via the event bus for cache *population* ([ADR-0005](0005-eventing-backbone.md)); lookup
embedding is synchronous but gated to protect NFR-P03. A **safety valve**: semantic caching can be
globally disabled per tenant/policy instantly (config), and is disabled by default in air-gapped
installs lacking a local embedding model ([ADR-0007](0007-embedding-strategy.md)).

## Consequences
- **Positive:** Captures near-duplicate savings toward SM-P01/P02 while keeping exact-tier speed;
  no new datastore; strong isolation; false-positive risk bounded by thresholds + audit + easy disable.
- **Negative:** Correctness hinges on threshold tuning per workload; `pgvector` scaling needs monitoring;
  a wrong threshold could serve stale content — mitigated by conservative defaults, per-policy control,
  and score logging.
- **Follow-ups:** Phase 3 designs `cache_entry` + vector columns + HNSW index + RLS; Phase 8 builds the
  embedding pipeline and threshold-tuning tooling; Phase 13 measures hit-rate, false-positive rate, and
  net savings (NFR-COST03).

## Requirements satisfied
- Functional: FR-050, FR-051, FR-052, FR-053, FR-054, FR-055, FR-056, FR-057, FR-058.
- Non-functional: NFR-P02, NFR-P03, NFR-COST01, NFR-COST03, NFR-SEC07, NFR-D05.

## Review notes
Revisit the datastore choice (pgvector → dedicated vector DB) only if Phase 13 shows `pgvector` cannot
meet NFR-P03 at production vector volumes; would be a superseding ADR behind the same cache port.
