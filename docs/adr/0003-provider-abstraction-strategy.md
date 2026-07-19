# ADR-0003: Provider Abstraction Layer strategy

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, AI Platform Engineer
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** Provider abstraction strategy

## Context & problem
The gateway must call many heterogeneous providers (OpenAI, Anthropic, Google, AWS Bedrock, Azure
OpenAI, plus generic OpenAI-compatible/self-hosted models) each with different auth, request/response
shapes, streaming semantics, error formats, and usage/token reporting. Adding or disabling a provider
must require **no change to the API or routing layers** (FR-026), and provider API drift must not
destabilize the core (RISK-T04, likelihood 4). We must normalize everything to one internal model.

## Decision drivers
- FR-020..029 (register providers/models; uniform adapter contract; normalized errors; runtime
  enable/disable; per-provider connection settings).
- NFR-M02 (open/closed), NFR-P01/P04 (low overhead, streaming), NFR-A02 (failover depends on uniform
  error taxonomy).
- RISK-T04 (provider drift), and the OpenAI-compatible external contract (FR-001..007).

## Options considered
### Option A — Adopt a third-party unifying SDK (e.g., a LiteLLM-style library) as the provider layer
- **Pros:** Fast; 100+ providers out of the box.
- **Cons:** We inherit its abstractions, error model, and release cadence; hard to guarantee our
  latency budget, our normalized taxonomy, our governance hooks (PII, metering) at exactly the right
  seam; supply-chain/maintenance risk; weakens our core differentiation. Rejected as the *core* (may be used
  behind our own port for exotic providers).

### Option B — Direct per-provider integration in the routing/use-case layer
- **Pros:** Full control, minimal indirection.
- **Cons:** Provider specifics leak into core logic; violates open/closed; every new provider touches
  routing; drift ripples widely. Rejected.

### Option C — First-party **Provider Port + Adapter** contract (Strategy pattern) with a registry
A single `LLMProviderPort` interface with methods for `chat`, `complete`, `embed`, `stream`, plus
capability metadata; one adapter per provider translating to/from the internal canonical model; a
**Provider Registry** (backed by the Model Registry, see Architecture.md) that resolves a model alias
→ concrete provider+model and yields the adapter; normalized **error taxonomy** and **usage
extraction** enforced by the contract.
- **Pros:** New provider = new adapter, zero core change (open/closed, FR-026); we own the latency
  path, error normalization, streaming, and the exact hooks for metering/PII/governance; runtime
  enable/disable via registry (FR-028); contract tests pin each adapter against drift (RISK-T04).
- **Cons:** We build/maintain each adapter ourselves.

## Decision
Adopt **Option C**: a first-party **Provider Abstraction Layer** built on a `LLMProviderPort`
interface (Ports & Adapters, [ADR-0001](0001-clean-architecture-and-runtime.md)) plus a Provider
Registry. Each adapter maps: request → provider payload, provider response → canonical response,
streaming chunks → canonical stream events, provider error → **canonical error taxonomy**, and
provider usage → canonical token/usage record (feeding metering, [ADR-0004](0004-reserve-commit-cost-accounting.md)).
A **generic OpenAI-compatible adapter** covers self-hosted/open-weight models (FR-024). Adapters are
loaded via a registry so providers/models can be enabled/disabled at runtime without redeploy
(FR-028). A third-party unifying SDK *may* be wrapped behind the port for long-tail providers, but is
never exposed to the core. Every adapter ships **contract tests** replaying recorded provider
fixtures to detect drift.

## Consequences
- **Positive:** Full control of the hot path and governance seams; clean extensibility; drift is
  caught at the adapter boundary; failover relies on a stable internal error taxonomy (NFR-A02).
- **Negative:** Ongoing adapter maintenance as providers evolve — bounded by contract tests and
  runtime disable (FR-028) for emergencies.
- **Follow-ups:** Define the canonical request/response/stream/error/usage models in Phase 4; adapter
  contract-test harness in Phase 13.

## Requirements satisfied
- Functional: FR-020, FR-021, FR-022, FR-023, FR-024, FR-025, FR-026, FR-027, FR-028, FR-029.
- Non-functional: NFR-M02, NFR-P01, NFR-P04, NFR-A02.

## Review notes
Revisit the "wrap a third-party SDK for long-tail providers" boundary annually; if maintenance of
first-party adapters becomes the bottleneck, reconsider the split (new ADR).
