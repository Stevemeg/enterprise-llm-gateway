# ADR-0016: Evolution to an Enterprise AI Operating System

- **Status:** Accepted and **FROZEN** for Phase 4. Rules 1-5 and the governance principles
  below may not be amended - a change requires a superseding ADR, not an edit to this one.
- **Date:** 2026-07-19
- **Deciders:** Principal Architect, Security Architect, Platform Lead
- **Phase:** 4 — Enterprise AI OS Foundation (Slice 1)
- **Affects:** all future modules. Supersedes nothing; ADR-0001 (Clean Architecture) and the
  layering/crypto contracts remain in force and are the mechanism this ADR builds on.

## Context & problem

The gateway's foundation is complete and validated: Clean Architecture with import-linter
contracts, RLS-enforced multi-tenancy, and an authentication subsystem frozen at 169/169 with a
closed security review. The remaining ~55% of the project (RBAC, providers, routing, cost,
caching) will be followed by a set of capabilities that change what the system *is*: MCP tool
execution, agent orchestration, a dynamic tool registry, evaluation, policy, memory, and
self-healing.

Those capabilities are not features that bolt onto a gateway. **They dictate what the gateway's
interfaces must look like.** If RBAC, routing and providers are designed without them, adding
them later means rewriting completed modules — precisely what this project's process exists to
avoid. Conversely, implementing them *now* would stall the core gateway and produce speculative
abstractions with no consumers.

The problem is therefore one of sequencing: **how to let future capabilities constrain today's
interfaces without implementing those capabilities today.**

## Decision drivers

- Preserve every completed module (ADR-0001; auth frozen; schema governed by ADR-0013/14/15).
- Avoid speculative generality — abstractions with no near-term consumer rot.
- The project's demonstrated lesson: **enforcement, not documentation, is what survives.**
  Clean Architecture and the crypto boundary held because import-linter fails the build. RLS held
  because the migration guardrail fails the build. Authentication became trustworthy only once the
  validation script propagated failures. Four separate checks in the last milestone reported
  success while structurally incapable of failing.

## Decision

Adopt the **Enterprise AI Operating System** as the target architecture, reached by extension
rather than rewrite. Three rules govern all remaining work.

### Rule 1 — The definition of an architectural invariant

An architectural invariant must satisfy **all three**:

1. **its absence would force modification of existing public interfaces or domain contracts when
   the capability is later introduced;**
2. it has a concrete enforcement mechanism;
3. it has an automated verification step.

Property 1 is the **objective admission test for Tier 1**, and it is deliberately stronger than
"it changes today's interfaces" - that phrasing admits anything a designer feels strongly about.
The question is counterfactual: *if we omit this seam and add the capability in six months, do we
have to alter published interfaces?* MCP changes execution interfaces; the Tool Registry changes
tool resolution; the pipeline changes request/response flow; BaseAgent changes agent lifecycle;
`RoutingDecision` changes routing contracts. Reflection, evaluation, policy and memory do not -
they consume those seams unchanged. That asymmetry is what separates the tiers, and it is
checkable by a reviewer rather than a matter of taste.

If a candidate invariant is **semantic** rather than structural, it must be **redesigned into a
structural representation** before it is treated as an invariant. It is not discarded for being
hard to lint, and a review checklist is not an enforcement mechanism. Without this clause the
architecture silently narrows to whatever is convenient to lint, dropping exactly the concerns
that matter most (explainability, least privilege, fail-closed behaviour).

### Rule 2 — Three artifacts before any implementation

Every new architectural seam requires, **in order**: an **ADR** explaining why it exists, a
**protocol/interface** defining the seam, and **CI enforcement** proving the seam cannot be
bypassed. Implementation may not begin until all three exist.

### Rule 3 — Typed domain objects over conventions

Where more than one module must agree on a concept **and disagreement would be silent**,
represent it as a typed domain object rather than a convention. The second clause is the trigger
test: without it this degrades into ceremony around values only one module consumes.

Validated repeatedly in Milestone 3 — `AuthenticationDecision` (a typo'd audit string never
fails), `AuthenticationContext` (attribute sprawl on `request.state`), `SecretsResolver`
(a reference silently used as key material), `OidcProviderPort` (raw nonce vs stored hash).

### Rule 4 — A seam is unproven until one real implementation exists

An interface is not "finished" when it is defined; it is finished when **one working
implementation** exists behind it. Additional implementations may only be added after the first
proves the shape. Designing several implementations against an unvalidated interface produces an
API that looks correct on paper and fails on contact.

Milestone 3 is the evidence: `SecretsResolver` was proven by `EnvSecretsResolver`,
`OidcProviderPort` by `OidcProviderAdapter`, `OidcLoginStateStore` by `SqlOidcLoginStateStore`.
In each case the first implementation forced a correction the interface alone had not exposed -
most sharply when `verify_id_token` had to change from `expected_nonce` to `expected_nonce_hash`,
because only a real adapter revealed that the raw nonce is never stored.

### Rule 5 — A protocol may evolve only through an active consumer

A protocol is **not** extended because a future capability might need it. It is extended only when
its current first consumer cannot be implemented correctly without the change.

Every protocol modification must identify:

1. the **active consumer** requiring the change;
2. **why the current protocol is insufficient** for it;
3. **why the change does not belong in the consumer instead** - the most common answer is that it
   does, and no protocol change is needed.

Rules 1-4 govern a seam's birth and validation; without Rule 5 nothing governs its *growth*, which
is where speculative fields accumulate one plausible addition at a time. Each looks harmless; the
aggregate is an interface shaped by imagined requirements that no code reads.

Worked example: `PlannerDecision` currently carries `intent`, `complexity` and
`required_capabilities`. Latency sensitivity, streaming, tool requirement and structured-output
flags were all considered and **deliberately excluded** - nothing consumes them yet. Adaptive
Routing (Tier 2) becomes their active consumer, and that is when the protocol may grow.

Corollary on responsibility: an agent describes its own concern and nothing else. The planner
describes *what the request needs*; it never infers provider, cost strategy, routing strategy or
fallback. Those belong to the cost, health and provider agents. Blurring that line duplicates
logic across agents, which no amount of interface discipline will later untangle.

## Governance principles

These sit *above* Rules 1-5: the rules say what good architecture looks like, these say when the
rules themselves may change.

### GP-1 — Architecture evolves only through evidence

Evidence means exactly one of:

1. a completed milestone exposes a limitation;
2. an external specification (e.g. MCP) cannot be represented without violating an existing rule;
3. two rules conflict in practice.

Nothing else justifies changing governance - least of all a hypothetical future need. This
generalises Rule 5 from protocols to the rules themselves.

### GP-2 — No rule may be weakened or reinterpreted inside a milestone

If a milestone appears to require bending a rule, the milestone **stops** and a superseding ADR is
written first. An exception is an ADR, not a patch.

*Evidence for GP-2:* ADR-0013, ADR-0014 and ADR-0015 each exist because a rule would otherwise
have been quietly bent - a missing credential column, a superuser bypassing RLS, a tenant table
outside RLS. In every case, stopping to write the ADR surfaced a defect that a patch would have
buried. The most severe finding of the project (the runtime role bypassing RLS entirely) came from
refusing to make a failing test pass.

### Deliberately not a rule

No Rule 6. Governance that accumulates a rule per milestone becomes a subsystem needing its own
maintenance. New lessons are recorded as **observed evidence** below, not as new rules.

## Observed evidence

Recorded after each Foundation milestone. This is the experiment: five rules were induced from a
single subsystem (Authentication), so whether they generalise is genuinely unknown. Tool Registry
tests Rules 4 and 5 (multiple registry backends, one unchanged protocol); MCP Gateway tests Rule 1
(if MCP forces a registry-interface change, Rule 1 was wrong); RBAC tests the Type A/Type B split
(a Capability milestone introducing new ports means a foundational seam is missing).

| Milestone | Type | Rules exercised | Exceptions | Resolution |
|---|---|---|---|---|
| AI OS Foundation (Slice 1) | Foundation | 1, 2, 3, 4 | None | - |
| Agent Runtime (Slice 2) | Foundation | 1, 3, 4, 5 | None | - |
| _Tool Registry_ | Foundation | _pending_ | | |
| _MCP Gateway_ | Foundation | _pending_ | | |
| _RBAC_ | Capability | _pending_ | | |

## Milestone classification

Every milestone declares its type, which determines the expected artifacts:

- **Foundation** - creates an extension point. ADR -> protocol -> validation implementation -> CI
  enforcement -> first consumer -> Gate 1 -> Gate 2 -> commit. A Foundation milestone with no ADR
  is suspect.
- **Capability** - consumes existing seams. No protocol changes unless Rule 5 is triggered, in
  which case the milestone stops. A Capability milestone shipping an ADR is a Rule 5 trigger.

## Two tiers

**Tier 1 — Foundational invariants.** These shape every interface from now on.

| # | Invariant | Structural seam | CI enforcement | First consumer |
|---|---|---|---|---|
| 1 | MCP-compatible execution | `McpGatewayPort` | import-linter: no direct provider/tool invocation outside adapters | MCP adapter |
| 2 | Tool Registry | `ToolRegistryPort` | import-linter forbidding direct tool imports; construction-path tests | first registered tool |
| 3 | Explainable agent routing | **`RoutingDecision`** typed record | every routing path returns it; `reasoning_steps` non-empty; each agent contributes; metrics/audit derive from the record | routing engine / PlannerAgent |
| 4 | BaseAgent SDK | lifecycle protocol | protocol-compliance + inheritance tests | PlannerAgent |
| 5 | Pipeline stage | stage protocol (inspect/annotate/block/continue) | stage registration + ordering + protocol tests | policy stage |

**First consumer is a required column, not documentation.** A seam with no identified near-term
consumer is speculative and must be deferred: an interface validated only against imagined usage
is an interface that will be wrong. Every seam above names the concrete thing that will exercise
it first.

**Tier 2 — Capability layers.** Implementations that consume Tier-1 seams and require **no**
interface changes: Reflection, Evaluation Pipeline, OPA Policy Engine, Enterprise Memory,
Benchmark Service, Adaptive Routing, Self-Healing, Production Observability.

The tiering is deliberate. An earlier draft listed Policy Engine and Evaluation Pipeline as
foundational; they are not. Neither requires every interface to know it exists — both require
**one stable interception seam**. Invariant 5 replaces them, which is a smaller and sharper
commitment: OPA and evaluation become pipeline stages, and no provider, router or agent interface
changes to accommodate them.

Invariant 3 is the worked example of Rule 1. "Routing decisions must be explainable" is semantic
and unenforceable as stated. Returning a typed `RoutingDecision` instead of a bare provider makes
it structural: a decision *cannot* be produced without its reasoning trace, because the return
type demands one.

## Consequences

- **Positive:** future capabilities become extensions, not refactors; each invariant fails the
  build when violated; the BaseAgent SDK and pipeline become reusable beyond this project.
- **Negative / obligations:** five new seams to define and enforce before RBAC; each new
  import-linter contract must be proven to fail on a deliberate violation, not merely to pass.
- **Explicitly deferred:** all Tier-2 implementations, and any concrete MCP server, agent or
  policy integration. Slice 1 defines seams only — zero business logic.

### Open design decision (must be settled with invariant 3)

`RoutingDecision` sits on the **hot path** — one per inference request, unlike the per-login auth
records. Whether `reasoning_steps` is always fully populated, sampled, or verbosity-levelled, and
what its audit retention is, must be decided **before** the type exists. Changing it later alters
a type every downstream module depends on: exactly the rewrite this ADR prevents.

## Alternatives considered

- **Implement the capabilities now.** Rejected: stalls the core gateway and produces abstractions
  with no consumers to validate them.
- **Treat the upgrades as a roadmap.** Rejected: a roadmap does not constrain today's interfaces,
  so the retrofit cost lands later — the outcome this ADR exists to prevent.
- **Document the invariants without enforcement.** Rejected by this project's own evidence:
  unenforced rules erode silently, and four checks in the previous milestone passed while
  verifying nothing.

## Requirements satisfied

Upholds ADR-0001 (Clean Architecture), ADR-0002 (tenant isolation), ADR-0009 (fail closed),
ADR-0014 (least-privilege runtime). Establishes the framing for the Phase-4 Master Execution Plan
and the Tier-1 seam definitions.

## Review notes

Revisit if a Tier-2 capability cannot be expressed through the Tier-1 seams — that would indicate
a missing invariant rather than a reason to bypass one.
