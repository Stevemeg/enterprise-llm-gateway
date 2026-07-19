# ADR-0007: Embedding strategy

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, AI Platform Engineer
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** Embedding strategy
- **Resolves open question:** OQ-01 (default embedding model/dimensionality)

## Context & problem
The semantic cache ([ADR-0006](0006-semantic-cache-architecture.md)) and future retrieval features need
text embeddings. The choice must satisfy the **≤40 ms** semantic-lookup budget (NFR-P03), be **net cost
positive** (NFR-COST03), work in **air-gapped self-host** with no external API (ASM-15, NFR-D05), keep
tenant data governed (must not leak PII to an external embedder against policy — [ADR-0009](0009-fail-open-fail-closed-matrix.md)),
and remain **swappable** as models improve, without changing stored vectors' meaning silently.

## Decision drivers
- NFR-P03 (latency), NFR-COST03 (net positive), NFR-D05 (air-gapped), ASM-15, FR-054..056, FR-110..112
  (governance of what leaves the boundary), NFR-M02 (pluggable).

## Options considered
### Option A — External provider embeddings API only (e.g., a hosted embedding model)
- **Pros:** High quality; no local GPU/infra.
- **Cons:** Adds network latency to the lookup path (threatens NFR-P03); per-embedding cost erodes
  savings; **cannot run air-gapped** (breaks NFR-D05/ASM-15); sends prompt text to an external service,
  conflicting with residency/PII policy for some tenants. Rejected as the *only* option.

### Option B — Self-hosted open embedding model only (bundled, runs in-cluster on CPU/GPU)
- **Pros:** Works air-gapped; no per-call external cost; data never leaves the boundary.
- **Cons:** We operate an inference component; CPU latency/throughput must be validated; model quality
  vs. best hosted models varies. Necessary for self-host, heavier for small SaaS.

### Option C — **`EmbeddingProvider` port with a pluggable, config-selected backend** (self-hosted model *default*; external API optional), governed and versioned
- **Pros:** One codebase, both modes (NFR-D01): self-host defaults to the **bundled local model**
  (air-gap-safe), SaaS may select a hosted model for quality; **governance-aware** — if a tenant's
  policy forbids external processing, the port must use a local backend or semantic cache is disabled
  (fail-closed, ADR-0009); **versioned embedding space** — each stored vector records
  `embedding_model` + `version` + `dimension`, and a model change invalidates/re-embeds rather than
  silently mixing spaces (ties to FR-058 invalidation).
- **Cons:** Must maintain ≥2 backends and an embedding-version migration path.

## Decision
Adopt **Option C**: an **`EmbeddingProvider` port** with a **bundled self-hosted open embedding model
as the default** (both modes; guarantees air-gapped operation, ASM-15/NFR-D05) and an **optional
external embedding backend** selectable per deployment/tenant where policy permits. Embedding
generation for cache *population* runs **asynchronously** on workers ([ADR-0005](0005-eventing-backbone.md))
so it never blocks the request; the *lookup* embedding is synchronous but only on gated, cacheable
requests (protecting NFR-P03). Every vector is tagged with `embedding_model`, `version`, and
`dimension`; changing the model triggers **re-embedding/invalidation** (FR-058), never silent mixing of
vector spaces. Choice of a specific default model + dimensionality is finalized in Phase 8 against the
latency/quality/cost budget; the architecture does not hard-code it (NFR-M02). If policy forbids the
only available (external) embedder for a tenant, semantic cache is **disabled** for that tenant
(fail-closed) and exact caching still applies.

## Consequences
- **Positive:** Air-gap-safe by default; governance-respecting; cost-controlled (local default);
  future model upgrades handled via versioning without corrupting the vector store.
- **Negative:** Operating a local embedding model (resource sizing) and maintaining a re-embedding
  migration path; two backends to test.
- **Follow-ups:** Phase 8 selects the concrete default model + dimension and builds the re-embedding
  job; Phase 13 validates NFR-P03 and net savings (NFR-COST03).

## Requirements satisfied
- Functional: FR-054, FR-055, FR-056, FR-058, FR-110, FR-111, FR-112.
- Non-functional: NFR-P03, NFR-COST03, NFR-D05, NFR-M02, NFR-C05.

## Review notes
Revisit the default model as the open-embedding landscape evolves; any change is a versioned migration,
recorded as a follow-up ADR if it alters dimensionality or the default backend.
