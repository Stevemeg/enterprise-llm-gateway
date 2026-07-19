# C4 — Level 4: Code (illustrative, key abstractions)

**Scope:** The most important *design-level* abstractions and their relationships. This is a **design**
sketch (interfaces/contracts), **not implementation** — no code is produced in Phase 2. It illustrates
the Ports & Adapters seams that Phases 4–7 will implement.
Back to [Architecture](../../Architecture.md) · [C4 index](README.md).

## Provider abstraction (ADR-0003)

```mermaid
classDiagram
    class LLMProviderPort {
        <<interface>>
        +chat(CanonicalRequest) CanonicalResponse
        +complete(CanonicalRequest) CanonicalResponse
        +embed(EmbedRequest) EmbedResponse
        +stream(CanonicalRequest) AsyncIterator~StreamEvent~
        +capabilities() ProviderCapabilities
    }
    class OpenAIAdapter
    class AnthropicAdapter
    class BedrockAdapter
    class AzureOpenAIAdapter
    class GenericOpenAICompatibleAdapter
    LLMProviderPort <|.. OpenAIAdapter
    LLMProviderPort <|.. AnthropicAdapter
    LLMProviderPort <|.. BedrockAdapter
    LLMProviderPort <|.. AzureOpenAIAdapter
    LLMProviderPort <|.. GenericOpenAICompatibleAdapter
    class ProviderRegistry {
        +resolve(modelAlias, tenant) ProviderBinding
        +enable(id); +disable(id)
    }
    ProviderRegistry --> LLMProviderPort : yields adapter
    class CanonicalError {
        +code: ErrorCode
        +retryable: bool
    }
    OpenAIAdapter ..> CanonicalError : normalizes to
```

## Routing engine (ADR-0012)

```mermaid
classDiagram
    class RoutingStrategyPort {
        <<interface>>
        +rank(candidates, context) RankedCandidates
    }
    class LowestCostStrategy
    class LowestLatencyStrategy
    class QualityTierStrategy
    class WeightedStrategy
    class PinnedStrategy
    RoutingStrategyPort <|.. LowestCostStrategy
    RoutingStrategyPort <|.. LowestLatencyStrategy
    RoutingStrategyPort <|.. QualityTierStrategy
    RoutingStrategyPort <|.. WeightedStrategy
    RoutingStrategyPort <|.. PinnedStrategy
    class RoutingEngine {
        +route(request) RoutingDecision
    }
    class EligibilityFilter {
        +filter(candidates, policy) candidates
    }
    class FailoverExecutor {
        +execute(ranked, budget) Result
    }
    class CircuitBreaker
    RoutingEngine --> EligibilityFilter
    RoutingEngine --> RoutingStrategyPort
    RoutingEngine --> FailoverExecutor
    FailoverExecutor --> CircuitBreaker
    RoutingEngine ..> RoutingDecision : records (FR-033)
```

## Budget reserve/commit (ADR-0004)

```mermaid
classDiagram
    class BudgetPort {
        <<interface>>
        +reserve(scopeChain, estimate) ReservationId
        +commit(ReservationId, actualCost)
        +release(ReservationId)
    }
    class RedisLuaBudgetAdapter {
        +reserve() : atomic Lua, most-restrictive-first
    }
    BudgetPort <|.. RedisLuaBudgetAdapter
    class UsageLedger {
        <<append-only>>
        +record(UsageEntry)
    }
    class Reconciler {
        +reconcile(scope); +resetPeriod(scope)
    }
    RedisLuaBudgetAdapter ..> UsageLedger : commit via events
    Reconciler --> UsageLedger : source of truth
    Reconciler --> RedisLuaBudgetAdapter : repair counters
```

## Notes
- These interfaces are **contracts**, finalized in Phase 4 (API/domain models) and implemented in
  Phases 5–9. Method signatures shown are indicative.
- Every `*Port` is an Application-layer interface; every `*Adapter` lives in the Adapters layer and is
  wired in the composition root ([ADR-0001](../../adr/0001-clean-architecture-and-runtime.md)).

**Requirements:** FR-020..041, FR-060..063; NFR-M02.
