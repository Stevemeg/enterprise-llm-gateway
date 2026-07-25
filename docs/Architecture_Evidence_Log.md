# Architecture Evidence Log

**Purpose:** empirical record of whether [ADR-0016](adr/0016-enterprise-ai-os-architecture.md)'s
governance survives contact with implementation. **This is not an ADR** and carries no authority -
it records observations. A change to Rules 1-5 or GP-1/GP-2 requires a *superseding ADR*.

Five rules were induced from a single subsystem (Authentication), so whether they generalise is
unknown. These records are the experiment.

## How to use this

**Write the Prediction section before implementation begins.** A rule marked ✓ after the fact is
nearly unfalsifiable - it is easy to conclude a rule held once the outcome is known. Stating the
falsification conditions up front makes the result binding.

**A ✗ is a successful experiment, not a project failure.** It means a rule gave real information
about where an abstraction was wrong, which is the entire reason for running it. A model that
records no ✗ across several milestones is more likely to be unfalsifiable than correct.

---

## Template

```text
Evidence Record: <Milestone>            Type: Foundation | Capability

PREDICTION (written BEFORE implementation)
------------------------------------------
Rules exercised:        Rule X, Rule Y, GP-Z
Falsification conditions:
  - If <observable thing happens>, Rule X was wrong.
Expected outcome:       <what should happen if governance holds>

OBSERVED (written AFTER Gate 2)
-------------------------------
Gate 2:                 PASS | FAIL
Rule status:            Rule X ✓/✗   Rule Y ✓/✗
Unexpected observations:
Decision:               No action | Supersede ADR-0016 via ADR-00XX
Lessons:
```

---

## Evidence Record: Phase 4 Slice 2 — Agent Runtime — Type: Foundation

> **Evidence strength: WEAK.** The prediction below was **reconstructed after implementation**,
> not written in advance. A post-hoc prediction cannot falsify anything - it is written knowing the
> outcome. Recorded for completeness and to show the rules being exercised, but it carries less
> weight than Tool Registry's, whose prediction *was* written first. This is the last record that
> will have this weakness.

### PREDICTION *(reconstructed 2026-07-19, after implementation)*

**Rules exercised:** Rule 3 (typed domain objects), Rule 4 (a seam is unproven until one real
implementation exists), Rule 5 (a protocol may evolve only through an active consumer).

**Falsification conditions**

- If `AgentRoutingStage` had required changes to `PipelineStage`'s *members*, **Rule 1's admission
  test would have been wrong** — the seam would not have anticipated its own first consumer.
- If any protocol had changed without an active consumer demanding it, **Rule 5 failed**.
- If a guard passed without ever being observed failing, **the enforcement was theatre**.

**Expected outcome:** the runtime becomes a pipeline stage against unchanged protocols; four
guards each observed failing before being trusted.

### OBSERVED *(after Gate 2, 2026-07-19)*

**Gate 2: PASS** — 206 passed, 0 skipped, 95% coverage, mypy strict clean (138 files),
import-linter 13 kept / 0 broken.

| Rule | Status | Evidence |
|---|---|---|
| Rule 3 — typed domain objects | ✓ | `RoutingDecision` and `StageResult` are agreed on by runtime, stage and future consumers; disagreement would be silent, which is the trigger test |
| Rule 4 — seam unproven until implemented | ✓ **strong** | `AgentRoutingStage`, the first real consumer of `PipelineStage`, surfaced a defect the protocol alone had not exposed (see below) |
| Rule 5 — protocol evolves only via active consumer | ✓ | One protocol change occurred, driven by an active consumer, and was surfaced rather than made silently |

### Unexpected observations

**1. Rule 4 paid out immediately (protocol defect).** `PipelineStage` was missing
`@runtime_checkable`, while `BaseAgent` had it. Nothing revealed this until a consumer tried to
assert conformance and mypy rejected `isinstance()`. The protocol *looked* complete in isolation.
This is the clearest evidence so far that Rule 4 is doing real work rather than adding ceremony.

**Rule 5 classification:** this was a genuine protocol change driven by an active consumer, so
Rule 5 was triggered and satisfied. It added no members and corrected an inconsistency rather than
evolving the interface, so **no superseding ADR is warranted** — but it is recorded here rather
than left silent, which is the behaviour Rule 5 exists to produce.

**2. Governance caught protocol drift but NOT responsibility drift.** The first implementation of
`AgentRoutingStage` returned `BLOCK` on a non-selection, embedding execution control into the
seam's first consumer. Every rule and every guard passed. It was caught by **human review**, not by
governance, and would have forced rework once Policy, Evaluation and Reflection became stages.

This is a real gap: Rules 1-5 govern *whether a seam exists, how it is introduced, when it is
typed, when it is proven, and when it may change* — none govern **where a responsibility belongs**.
Recorded as an observation only. Per ADR-0016, no Rule 6 is proposed; if this recurs in Tool
Registry or MCP, that becomes evidence under GP-1 and justifies a superseding ADR.

**3. Guard 1 could not be expressed with import-linter.** The forbidden operation is
*instantiation*, not *import* — legitimate consumers must import `RoutingDecision` to read it.
Required a separate AST-based scan. Worth remembering when designing future guards: "which tool
answers this question?" is a real design step, not a formality.

### Decision

**No action.** ADR-0016 stands unchanged. No superseding ADR required.

### Lessons

- A seam is not proven by review; it is proven by a consumer. Rule 4 earned its place here.
- Rules constrain *structure* well and *responsibility placement* not at all. Human review remains
  load-bearing for the latter — do not assume green gates mean a correct design.
- Choose the enforcement tool from the question being asked. Import graphs, AST scans and
  conformance tests answer different questions, and using the wrong one yields a guard that passes
  while checking nothing.

---

## Evidence Record: Tool Registry — Type: Foundation

### PREDICTION *(written before implementation, 2026-07-19)*

**Rules exercised:** Rule 4 (a seam is unproven until one real implementation exists),
Rule 5 (a protocol may evolve only through an active consumer).

**Falsification conditions**

- If adding a **second** registry backend requires changing `ToolRegistry`, **Rule 4 was wrong** —
  one implementation was not sufficient to prove the shape, and the rule should demand two.
- If any field is added to `ToolDescriptor` without an active consumer needing it,
  **Rule 5 failed to prevent speculative evolution**.
- If the milestone ships without an ADR, the Foundation/Capability classification is not doing its
  job as a reviewer check.

**Expected outcome:** a second implementation lands against the **unchanged** protocol.
`InMemoryToolRegistry` already forced two decisions the interface left open (newest-version
resolution on unversioned `get()`, fail-closed `permitted()`), which is Rule 4 working as intended.

### OBSERVED *(after Gate 2, 2026-07-19)*

> **Evidence strength: STRONG.** This is the first milestone whose prediction was written **before**
> implementation. Unlike Slices 1 and 2, the result below could have come out otherwise.

**Gate 2: PASS** — 252 passed, 0 skipped, 95% coverage, mypy strict clean,
import-linter 15 kept / 0 broken.

| Falsification condition | Fired? | Evidence |
|---|---|---|
| Second backend requires changing `ToolRegistry` ⇒ **Rule 4 wrong** | **No** | `StaticManifestToolRegistry` satisfies all four methods; `application/ports/tools.py` untouched |
| Field added to `ToolDescriptor` without an active consumer ⇒ **Rule 5 failed** | **No** | No field added. Rule 5 not triggered |
| Milestone ships without an ADR ⇒ classification not working | **Unevaluable** | See below — the condition was ill-specified |

| Rule | Status | Evidence |
|---|---|---|
| Rule 4 — a seam is unproven until one real implementation exists | ✓ **strong** | One implementation *was* sufficient: a second backend with a different storage model fit unchanged, and a real consumer ran against the protocol alone |
| Rule 5 — protocol evolves only via an active consumer | ✓ **not triggered** | `ToolCatalog` was implementable without any protocol change |

### Unexpected observations

**1. One of my own falsification conditions was badly written.** *"If the milestone ships without an
ADR, the classification is not doing its job"* could not be evaluated. Tool Registry is a Foundation
milestone but **completed** a seam that ADR-0016 already introduced — it did not create a new one, so
no new ADR was warranted. The condition conflated *creating* a seam with *finishing* one.

**A condition that cannot fire is not a falsification condition.** The two conditions that were
concrete (protocol change, field addition) produced real evidence; the vague one produced none. When
writing the MCP prediction, every condition must name an observable artifact and state which
observation would count as failure.

**2. Guard C needed an AST scan, not import-linter — the second occurrence of this pattern.** Guard A
already forbids consumers *importing* implementations, but the composition root must import them
legitimately, so the open question was *who calls the constructor*. Same shape as Guard 1
(`RoutingDecision`) in Slice 2. Two instances now: **"which tool answers this question?" is a design
step, not a formality.** Import graphs and AST scans answer different questions, and reaching for the
familiar one yields a guard that passes while checking nothing.

**3. Guard C currently constrains no production code.** Nothing constructs a registry yet — container
wiring was out of scope. Its deliberate-violation proof shows it bites, so it is not theatre, but it
becomes load-bearing only when a composition-root wiring exists. Recorded rather than glossed,
because "passes because nothing exercises it" is the exact failure mode this project keeps finding.

**4. Rule 4 paid out again, quietly.** Building the second backend forced a decision the protocol left
open: whether a manifest-seeded registry should accept `register()`. Refusing would have been *partial
conformance* — a backend silently not implementing part of the contract. The parity tests exist to
catch precisely that.

### Decision

**No action.** ADR-0016 stands unchanged. No superseding ADR required.

### Lessons

- **Rule 4 holds under a genuine test.** One implementation proved the seam; the second fit unchanged.
  This is the strongest evidence to date that the governance generalises beyond Authentication.
- **Write falsification conditions against observable artifacts.** Two of three were usable; the third
  was prose. Predictions are only as good as their sharpest condition.
- **Match the enforcement tool to the question.** Second confirmation that dependency checks and
  construction checks are different problems.

---

## Evidence Record: MCP Gateway — Type: Foundation

### PREDICTION *(written before implementation, 2026-07-19)*

**Rules exercised:** Rule 1 (invariant admission test), Rule 4, Rule 5.

**Falsification conditions**

- If MCP cannot be represented without changing `ToolRegistry` or `McpGateway`, **Rule 1 was
  incomplete** — the counterfactual admission test failed to anticipate a real external constraint.
  This is the single most likely place for the constitution to break, because MCP is a
  specification we do not control.
- If MCP requires the tool-execution path to bypass the registry, **invariant 2 was mis-scoped**.

**Expected outcome:** MCP arrives as one registry *backend*, plugging into both seams unchanged.

### OBSERVED
*Pending.*

---

## Evidence Record: RBAC — Type: Capability

### PREDICTION *(written before implementation, 2026-07-19)*

**Rules exercised:** Type A/Type B classification, Rule 5, GP-2.

**Falsification conditions**

- If RBAC introduces **any new Tier-1 protocol**, then either it was misclassified as a Capability
  milestone, or a foundational seam is missing. Both are valuable findings.
- If RBAC needs to modify `PipelineStage`, `RoutingDecision` or `BaseAgent`, **Rule 5 is triggered**
  and the milestone must stop before any code changes.

**Expected outcome:** RBAC consumes the pipeline, `AgentRuntime` and `RoutingDecision` seams and
introduces no new protocol. Authorization was deliberately sequenced *after* the agent runtime
precisely so it evaluates agents, tools and pipeline stages rather than only HTTP endpoints.

**Known watch item:** authorization checks fail the same way authentication guards did — a
permission check matching nothing is indistinguishable from one that passes. Every RBAC guard needs
a test proving it denies on known-bad input.

### OBSERVED
*Pending.*

---

## Completed (no prediction recorded — pre-dates this log)

| Milestone | Type | Rules exercised | Exceptions |
|---|---|---|---|
| AI OS Foundation (Slice 1) | Foundation | 1, 2, 3, 4 | None |
| Agent Runtime (Slice 2) | Foundation | 3, 4, 5 | Rule 5 triggered and satisfied; no ADR needed |
| **Tool Registry (Slice 3)** | **Foundation** | **4, 5** | **None — first pre-registered prediction; Rule 4 held** |

Both are recorded honestly as **weaker evidence**: their predictions were not written in advance,
so ✓ reflects hindsight rather than a binding test. Slice 2 has a full record above. Tool Registry
is the first milestone with a genuine, pre-registered prediction.

## Evidence Record - Phase 4 Slice 4: MCP Gateway

**Classification:** Foundation milestone. **Evidence strength: STRONG** - the prediction was
registered before any MCP code existed, and MCP is a specification we do not control, so the
seams could not have been shaped to fit it after the fact.

**Pre-registered prediction.** An external protocol (MCP) can be integrated by implementing the
existing `McpGateway` and `ToolRegistry` seams without changing either protocol.

**Primary falsification condition.** If implementing MCP requires changing `McpGateway` or
`ToolRegistry`, Rule 1 is falsified and Rule 5 is triggered.

**Outcome: prediction held. Rule 1 HOLDING. Rule 5 NOT TRIGGERED.**
`ports/mcp.py` and `ports/tools.py` are byte-identical to their Slice-1 and Slice-3 state. Two
MCP gateway implementations (`NullMcpGateway`, `InMemoryMcpGateway`) and one consumer
(`McpToolProvisioner`) were built against them unchanged, and the consumer works identically
across both registry backends.

### The one condition that came close

The secondary condition *"MCP cannot be represented through existing `ToolDescriptor` semantics"*
was the only one that required a judgement rather than an observation. MCP describes a tool with
three fields; `ToolDescriptor` has six. The adapter supplies `version`, `capabilities` and
`required_permissions` from deployment-local knowledge.

Ruled **NOT TRIGGERED**: the adapter supplied deployment-specific domain metadata rather than
exposing a protocol deficiency. Recorded explicitly because "the adapter had to invent three of
six fields" is the kind of fact that should survive in the record even once it is ruled
non-firing - if a later external protocol forces the same judgement again, the pattern matters
more than either instance.

### Security finding promoted out of the mapping

`required_permissions` is not a defaulting decision, it is an authorization boundary. Had the
adapter accepted permission metadata from MCP, a remote server would declare its own
authorization bar and could lower it to nothing by omitting the field. The adapter therefore
never reads permission metadata from the server in any spelling, and a test asserts this against
a deliberately hostile server. This was discovered while writing the mapping documentation, not
while designing it.

The residual risk is recorded rather than solved: an **unconfigured** MCP tool receives `()`,
which `permitted()` treats as "no permission required". Deployment safety therefore rests on the
operator declaring requirements. A default-deny alternative was not adopted because it belongs to
RBAC, which is out of this slice's frozen scope.

### Enforcement (each violated, observed failing, restored, observed passing)

| Guard | Mechanism | Violation | Observed |
|---|---|---|---|
| D | import-linter | consumer imports `InMemoryMcpGateway` | 14 kept / 3 broken |
| E | import-linter | MCP adapter imports `InMemoryToolRegistry` | 15 kept / 2 broken |
| F | AST scan | consumer constructs `InMemoryMcpGateway` | exit 1, offender named |

Guard F is the **third** occurrence of import-linter being unable to express a construction
constraint. Two occurrences were a coincidence; three is a category. Dependency questions and
construction questions are structurally different, and every future seam should be assumed to
need both kinds of check unless shown otherwise.

### Finding: the two validation entry points have drifted

`validate.sh` contains none of the Phase-4 guards - not Guard F, and not the RoutingDecision or
registry guards from Slices 2 and 3 either. Gate 2 runs `validate.ps1`, so enforcement is real on
the machine that matters, but a guard present in one entry point and absent from the other is
half-enforced, and the earlier lesson of this project is that a check which cannot fail is worse
than no check because it reports success. Not fixed here: out of frozen scope. Logged as a
blocking item for the next slice.

## Evidence Record - Phase 4 Slice 6: Routing Engine

**Classification:** Capability milestone. **Evidence strength: STRONG** - the Rule 5 determination
was stated in full, protocol by protocol, *before any code was written*, and the milestone was
authorised on that basis. Slightly weaker than Slice 4's written pre-registration in that the
prediction was recorded in the review thread rather than in this log first; it was nonetheless
genuinely prior, not reconstructed.

**Pre-registered prediction.** A production Routing Engine can be built by consuming
`AgentRuntime`, `RoutingDecision`, `PipelineStage` and the published ports, without modifying any
Tier-1 protocol.

**Falsification condition.** If orchestration required changing `AgentRuntime.decide()`,
`RoutingDecision`, or any Tier-1 protocol, Rule 1 is falsified and Rule 5 triggered.

**Outcome: prediction held.**

| Item | Result |
|---|---|
| Rule 5 | **NOT TRIGGERED** - contracts 19 -> 20, all kept; no Tier-1 file modified |
| Rule 4 | Satisfied by **real implementation + stub `ProviderCatalog`** (see below) |
| Validation | **307 passed, 0 skipped, 96% coverage** - Gate 1 + Gate 2 PASS |

Three predictions were checked against the code rather than assumed, before implementing: an empty
catalog resolves to `NO_CANDIDATE` through the runtime's existing short-circuit logic; ambiguity is
already expressed by `ProviderAgent` via `confidence`; and an unresolvable selection is
unreachable, because the runtime can only select from candidates the engine supplied.

### Prior record (superseded framing)


Detail of the same milestone, retained in full.

### Finding: Rule 4 could not be satisfied in its usual form, and Invariant 3 is why

Rule 4 asks that a new port be validated by a trivial or null implementation. **This port cannot
have one.** Any `RoutingEngine` must return a `RoutingExecution`, which carries a
`RoutingDecision`, and only `AgentRuntime` may construct one (Invariant 3, CI-enforced). A null
engine would therefore have to fabricate a decision - an unexplained routing outcome, which is
exactly what the explainability invariant exists to prevent.

Rule 4 was instead satisfied with **one real implementation plus a stub `ProviderCatalog`**: the
port's substitutability is demonstrated at the collaborator boundary rather than by a degenerate
engine.

This is the first time two ADR-0016 rules have constrained each other. Invariant 3 correctly won,
and the useful generalisation is that **Rule 4 is subordinate to Invariant 3 wherever a port's
return type includes a decision record.** Any future port returning a `RoutingDecision` will hit
the same wall, and the correct response is a stub collaborator, not a fabricated decision. This is
recorded rather than resolved by amending ADR-0016, which is frozen (GP-2).

### Supporting decisions

* `RoutingExecution` is limited to `{decision, provider}` - no reason, status or message. A second
  explanation would eventually disagree with the first; a test asserts the field set.
* `RoutingIntegrityError` is an exception, never a routing outcome. A catalog that disagrees with
  the runtime is an engine defect, not a fact about the request, and must not enter the decision
  record dressed as an explained denial.
* `AgentRoutingStage` was refactored to depend on `RoutingEngine`, moving orchestration out of a
  pipeline adapter. Guard L (sole application caller of `AgentRuntime`) exists to stop that
  refactor silently reverting.

### Enforcement

| Guard | Mechanism | Violation | Observed |
|---|---|---|---|
| J | import-linter | engine imports an adapter | 18 kept / 2 broken |
| K | AST scan | non-root module constructs the engine | exit 1 |
| L | AST scan | second application caller of `AgentRuntime` | exit 1 |
| inv. 3 | AST scan | engine constructs a `RoutingDecision` | exit 1 |

**Vacuous evidence:** the "engine must not call provider adapters" guard constrains nothing - no
provider adapter package exists. It is subsumed by Guard J (which forbids all adapters), so no
separate contract was added naming a non-existent module. To be re-evaluated when provider
adapters land.

**No longer vacuous:** Guard K became live in this slice - the composition root now constructs the
routing engine. The registry, MCP and resolver construction guards remain vacuous pending their
own wiring.

## Evidence Record - Phase 4 Slice 7: Provider Execution

**Classification:** Capability milestone. **Evidence strength: STRONG** - the falsification
condition was stated in full, protocol by protocol, before any provider-execution code was
written, and the reuse-vs-duplicate decision for Guard L was made explicit in advance rather than
discovered while coding.

**Pre-registered prediction.** A `ProviderExecutor` can turn a `RoutingExecution` into a provider
call by consuming the existing `RoutingExecution`/`RoutingDecision` seam and a new
capability-owned `ProviderClient` port, without modifying `RoutingDecision`, `RoutingExecution`,
or any Tier-1 protocol - and Guard L, built in Slice 6 to keep `AgentRuntime` reachable only from
the routing engine, generalises unmodified to a second application-layer module without needing a
duplicate guard.

**Falsification conditions**

- If executing a provider call required widening `RoutingDecision` or `RoutingExecution` with
  request payload, **Rule 1 was falsified and Rule 5 triggered**.
- If `ProviderExecutor` needed its own `AgentRuntime`-reachability guard because Guard L's AST
  scan (which matches *any* file referencing `AgentRuntime`, not a hardcoded list of Slice-6
  files) failed to catch a violation in a module Guard L's author never anticipated, **guard
  reuse across slices does not generalise**.
- If `ProviderClient` needed a null implementation to be considered proven, **Rule 4's "real
  implementation" clause was insufficient** and needed a trivial/null exception carved out for it,
  as already happened once for `RoutingEngine` in Slice 6.

**Outcome: prediction held on every condition.**

| Item | Result |
|---|---|
| Rule 5 | **NOT TRIGGERED** - contracts 20 -> 21, all kept; `domain/routing/models.py` and `application/ports/routing.py` byte-unchanged |
| Guard L reuse | **Confirmed by deliberate violation**: an `AgentRuntime` reference added to `application/providers/provider_executor.py` (a file that did not exist when Guard L was written) was caught immediately - `[L] gateway/application/providers/provider_executor.py: references AgentRuntime; only the routing engine may` - with **zero changes to `check_routing_engine.py`** |
| Rule 4 | Satisfied by **two real implementations** (`InMemoryProviderClient`, `FakeProviderClient`), no null variant - same resolution pattern as Slice 6's `RoutingEngine`, now observed a second time |
| Validation | **Gate 1 + Gate 2: 315 passed, 0 skipped, 96% coverage** - full pass, including every Postgres-backed RLS/integration/security test |

### Finding: Guard L generalises across slices without modification - the reuse claim is now evidence, not a design intention

Slice 6 built Guard L to answer one question: is `AgentRuntime` reachable from anywhere but the
routing engine? The guard is implemented as an AST scan over every `*.py` file under
`src/gateway`, not as a list of files known at the time it was written. Slice 7 is the first test
of whether that generality was real or accidental. Adding `application/providers/provider_executor.py`
- a module Guard L's author could not have named in Slice 6 - and referencing `AgentRuntime`
inside it caused an immediate, correctly-attributed failure with no guard-script change. This is
the intended payoff of choosing "who references this name" over "who imports this specific file"
as the scan's question, and it is now demonstrated rather than assumed.

The decision to **not** write a second guard (e.g. a "Slice-7-specific AgentRuntime guard") was
made before implementation, not discovered as a simplification afterward - avoiding that
duplication was itself a falsifiable prediction, and it held.

### Finding: `InferenceRequest` needed to exist as a typed object, not a dict, from the first line

`ProviderExecutor.execute(execution, request)` takes `RoutingExecution` and `InferenceRequest` as
two separate parameters by design (per the governing decision, before code existed). This is
Rule 3's trigger test applied prospectively rather than discovered by refactor: `ProviderExecutor`
and every `ProviderClient` implementation must agree on the request shape, and that agreement
would drift silently if left as a `dict[str, Any]` convention - exactly the failure Rule 3 exists
to prevent. `InferenceRequest` was typed in `application/ports/providers.py` alongside the port it
serves (matching the `McpInvocation`/`McpResult` precedent from Slice 4, not `domain/`, since it
carries no CI-enforced structural invariant of its own).

### Enforcement (each violated, observed failing, restored, observed passing)

| Guard | Mechanism | Violation | Observed |
|---|---|---|---|
| 1 (new) | AST scan (`check_provider_construction.py`) | non-root file constructs `InMemoryProviderClient` | exit 1, offender named; PASS after removal |
| 2 (new) | import-linter (independence) | `fake_client` imports `in_memory_client` | 20 kept / 1 broken (`provider client implementations are mutually independent`); 21/21 after revert |
| L (reused, unmodified) | AST scan (`check_routing_engine.py`) | `provider_executor.py` references `AgentRuntime` | exit 1, offender named; PASS after removal |

**No longer vacuous:** Guard 1 is live from construction - the composition root builds both
`provider_client` and `provider_executor` in the same commit that introduces them, unlike the
registry/MCP/resolver construction guards, which remain vacuous pending their own wiring.

### Decision

**No action.** ADR-0016 stands unchanged. No superseding ADR required.

### Lessons

- **A guard built to answer "who references X" rather than "who imports file Y" survives the
  seam's own author being wrong about who will need it later.** This is now demonstrated twice
  in one direction (Guard L catching a file it predates) rather than assumed from its design.
- **Deciding not to build a guard is a decision that can itself be falsified.** Stating in advance
  "Guard L should catch this without changes" and then proving it, rather than writing a
  redundant guard "to be safe," produced sharper evidence than either silence or duplication
  would have.

## Evidence Record - Phase 4 Slice 8: Usage Metering, Cost Accounting & Budget Enforcement

**Classification:** Capability milestone. **Evidence strength: STRONG** - the falsification
conditions below, the estimate/actual boundary, the money representation, and which of the six
candidate guards would be genuinely new vs. redundant vs. vacuous were all determined and stated
in full before any accounting code was written.

**Pre-registered prediction.** Provider usage can be converted into deterministic monetary cost
and evaluated against a tenant budget by consuming the existing routing/execution seams and one
additive, backward-compatible widening of the Slice-7 `ProviderResponse` port, without changing
any Tier-1 protocol and without `CostAgent`, `ProviderExecutor`, or `RoutingDecision` acquiring any
monetary responsibility.

**Falsification conditions**

- If accounting required widening `RoutingDecision`, `RoutingExecution`, `PipelineStage`,
  `BaseAgent`, `ToolRegistry` or `McpGateway`, **Rule 1 was falsified and Rule 5 triggered against
  Tier 1**.
- If `ProviderResponse` could not represent provider-reported usage without a change, and that
  change could not be justified as a capability-owned Rule 5 event (active consumer named, why
  insufficient, why not in the consumer instead), the milestone would stop.
- If `ProviderExecutor` ended up computing cost, updating a budget, or writing a ledger entry,
  the responsibility separation this slice exists to enforce had already failed.
- If distinguishing a configuration defect (unknown price, malformed usage) from a business
  outcome (budget exceeded) required conflating them into one return type, that would be recorded
  as a design defect, not smoothed over.

**Outcome: prediction held on every condition.**

| Item | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** - zero diff on `domain/`, `application/ports/routing.py`, `pipeline.py`, `tools.py`, `mcp.py`, `agents.py`, and `application/agents/cost.py` (verified by `git diff --stat`, not by inspection alone) |
| Rule 5 against `ProviderResponse` (capability-owned) | **TRIGGERED and satisfied** - additive `usage: ProviderUsage \| None = None` field; active consumer `CostAccountant`; every Slice-7 construction remains valid unchanged |
| Rule 4 | Satisfied by one real implementation per new port (`StaticPriceTable`, `InMemoryBudgetStore`) - no null variant for either, for the same reason Slice 6's `RoutingEngine` had none: a fabricated price or budget would misrepresent "unconfigured" as "free" or "unlimited" |
| Validation | **Gate 1 + Gate 2: 352 passed, 0 skipped, 96% coverage** - full pass, including every Postgres-backed RLS/integration/security test |

### The estimate/actual boundary, held under test

`CostAgent` (routing-time affordability estimate, unchanged) and `CostAccountant` (post-execution
actual cost) were kept as two different concepts on purpose - the falsification condition was that
merging them, or having `CostAccountant` mutate `RoutingDecision`, would indicate the boundary
was never real. Neither occurred: `CostAccountant` never imports `domain.routing.models`, and
`BudgetEnforcer.evaluate()` runs entirely after `ProviderExecutor.execute()` returns, over data
`RoutingDecision` never carries.

### Finding: the only new Rule-5 event is additive, and the reasoning generalises from Slice 2

Widening `ProviderResponse` with `usage: ProviderUsage | None = None` is the same shape as
`PipelineStage` gaining `@runtime_checkable` in Slice 2: a capability-owned seam evolving because
its first real consumer cannot be built without the change, recorded here rather than requiring a
new ADR (Rule 2's ADR->protocol->enforcement sequence governs a seam's *birth*, not an existing
capability-owned seam's evolution under Rule 5). The field being optional and additive is what
kept every Slice-7 test passing unmodified - a non-optional field would have been a breaking
change disguised as an addition.

### Finding: not every "obvious" guard was worth building - three of six candidates were redundant or vacuous, and saying so was more useful than padding the count

Six candidate enforcement properties were evaluated before writing any script:

| Candidate | Verdict | Why |
|---|---|---|
| ProviderExecutor cannot import pricing/budget/accounting *adapters* | **Redundant** | Already covered by "application is framework-free and inward-only" (forbids all `gateway.application` -> `gateway.adapters`) |
| Accounting depends on pricing/budget ports, not adapters | **Redundant** | Same blanket contract as above |
| ProviderExecutor cannot import the accounting *orchestrators* (same layer, different package) | **Genuinely new** | The blanket contract only governs application->adapters; nothing stopped one application module importing a sibling. Built as Guard B |
| Cost accounting cannot invoke `AgentRuntime`/`RoutingEngine` | **Already enforced, reused** | Guard L's AST scan is unconditional over `src/gateway`, not scoped to Slice-6/7 files; proven by deliberate violation with zero script changes |
| Cost accounting cannot construct/mutate `RoutingDecision` | **Already enforced by two independent mechanisms** | `check_routing_decision_construction.py` (blanket scan) plus the dataclass's own `frozen=True` (a mutation attempt raises `FrozenInstanceError` regardless of any guard) - not re-proven here since accounting never imports `domain.routing.models` at all |
| Pricing/budget adapters mutually independent | **Not applicable, not built** | Exactly one implementation exists per port this slice (`StaticPriceTable`, `InMemoryBudgetStore`) - an independence contract needs two to be meaningful, and a second adapter built solely to make a guard non-vacuous would be exactly the speculative generality Rule 5 forbids |

Only Guard 1 (construction confinement, new AST script) and Guard B (import-linter, new) were
built. Redundant candidates were named and dismissed rather than silently skipped, and the
not-applicable one is recorded as absent-on-purpose rather than as an oversight to be embarrassed
about later.

### Enforcement (each violated, observed failing, restored, observed passing)

| Guard | Mechanism | Violation | Observed |
|---|---|---|---|
| 1 (new) | AST scan (`check_accounting_construction.py`) | non-root file constructs `StaticPriceTable` | exit 1, offender named; PASS after removal |
| B (new) | import-linter (forbidden) | `provider_executor.py` imports `cost_accountant.py` | 21 kept / 1 broken (`provider execution does not depend on accounting`); 22/22 after revert |
| L (reused, unmodified) | AST scan (`check_routing_engine.py`) | `cost_accountant.py` references `AgentRuntime` | exit 1, offender named; PASS after removal - the **second** slice in a row this exact guard has caught a violation in a file that did not exist when it was written |

**No longer vacuous:** Guard 1 is live from construction - the composition root builds
`StaticPriceTable`, `InMemoryBudgetStore`, `CostAccountant` and `BudgetEnforcer` in the same
commit that introduces them, both adapters starting empty (no prices, no budgets configured),
mirroring the "nothing configured yet" posture of the routing catalog and provider client before
them.

### Design decisions recorded as decisions, not defaults

- **Money is `Decimal` + an explicit 3-letter currency, quantized to 8 decimal places with
  `ROUND_HALF_EVEN`.** This is the project's *first* established rounding rule - nothing existed
  to defer to. 8 places mirrors `docs/Schema.sql`'s `numeric(18,8)` columns; half-even was chosen
  over half-up because repeated half-up rounding inflates a long-run sum, which is precisely the
  drift this type exists to prevent. Proven, not asserted: `test_decimal_summation_avoids_float_drift`
  shows `0.1 + 0.1 + 0.1 != 0.3` in float but exact via `Money`, and
  `test_fractional_token_pricing_accumulates_without_drift` repeats the same shape across three
  independent `CostAccountant.account()` calls.
- **Only input/output token pricing exists.** `docs/Schema.sql`'s `price_table` documents nothing
  beyond per-model input/output rates either; cached-token, image, audio and tool-call pricing are
  real provider dimensions with zero consumers in this slice (Rule 5) and were not added.
- **Pricing is global, not tenant-scoped**, despite `price_table.organization_id` existing in the
  documented schema for future negotiated rates. Nothing in this slice's required test list needs
  per-tenant pricing, and the tenant-isolation property that actually matters here - spend
  isolation - is exercised entirely on the budget side instead.
- **Every budget in this slice is hard-enforced; no `limit_kind` field exists.** `docs/Schema.sql`
  documents a `soft` variant (FR-067, warn-but-allow); nothing in this slice's failure-semantics
  list exercises that branch, so no field was added for it to sit unused.
- **No migration was added.** `docs/Schema.sql` documents `budget`, `reservation`, `price_table`
  and `usage_ledger`, but none of the five applied Alembic migrations create them - this slice's
  persistence does not exist in the real database yet. Introducing it now would be exactly the
  "casual migration" the brief warned against; the capability-owned in-memory ports
  (`StaticPriceTable`, `InMemoryBudgetStore`) prove the architecture instead, matching every prior
  capability slice's own-implementation pattern.

### Known limitations, stated rather than concealed

- **Not hard concurrency-safe enforcement.** `BudgetPort.snapshot()` (read) and `.record()`
  (write) are two separate awaits; nothing serializes them across concurrent callers. ADR-0004
  explicitly rejected this exact shape ("Option A - post-hoc accounting only") as insufficient for
  FR-063/RISK-T03, in favor of an atomic Redis Lua reserve/commit that does not exist anywhere in
  this codebase. This slice provides deterministic accounting of already-incurred cost plus a
  budget-store failure policy (ADR-0009 row 1: unavailable -> fail closed); it does not provide,
  and does not claim to provide, atomic concurrent budget enforcement. That remains a
  database-backed milestone.
- **Idempotency is process-local and best-effort.** `BudgetPort.record()` takes an
  `idempotency_key` and the in-memory adapter deduplicates on it, preventing a retried accounting
  call from double-charging the same execution *within one process*. The key reused is
  `correlation_id` - the only stable per-execution identifier the current architecture attaches to
  a request (`InferenceRequest.correlation_id`) - deliberately not a new identifier minted inside
  the accounting layer, per the instruction to reuse rather than invent execution identity. This
  does not survive a process restart and does not coordinate across replicas; durable,
  distributed exactly-once settlement is out of scope and is not simulated.
- **Tier-2 compatibility reasoning, not fields.** Future Reflection distinguishing attempt-1 cost
  from attempt-2 cost from final-request cost needs no change to `CostRecord`'s shape: a
  multi-attempt caller can pass a distinct `correlation_id` per attempt today. No
  `attempt_number` field was added - there is no active consumer for it yet (Rule 5).

### Decision

**No action.** ADR-0016 stands unchanged. No superseding ADR required.

### Lessons

- **A capability-owned port's Rule 5 evolution can be as disciplined as a Tier-1 one.**
  `ProviderResponse` widened exactly the way `PipelineStage` did in Slice 2: named consumer, named
  insufficiency, additive change, zero breakage - proving the discipline isn't special-cased to
  Tier 1.
- **Naming a redundant or vacuous guard candidate is evidence, not a gap.** Three of six
  candidates in this slice were dismissed with a stated reason rather than built reflexively;
  that record is more useful to the next slice than a guard count padded with overlapping checks.
- **When a project has no existing convention for something as basic as money, establishing one
  explicitly - and proving it under the exact failure mode it exists to prevent - is cheaper than
  discovering the gap during a later slice that assumes one already exists.**

## Evidence Record - Phase 4 Slice 9: Persistent Usage Ledger & Atomic Budget Settlement

**Classification:** Capability milestone. **Evidence strength: STRONG** - the Rule 5 determination,
the reservation-vs-settlement analysis, the schema-shape divergence from the Phase-1 illustrative
tables, and the six-candidate guard evaluation were all determined and stated before any
persistence code was written.

**Pre-registered prediction.** A tenant-scoped, transactionally safe usage ledger and atomic
budget settlement can be built entirely as a capability consuming existing seams (`UnitOfWork`,
RLS binding, `PricingPort`, `CostAccountant`), without widening any Tier-1 protocol, and without
disguising post-hoc settlement as pre-call hard enforcement.

**Falsification conditions**

- If hard enforcement could be expressed only by widening `RoutingDecision`, `RoutingExecution`,
  `PipelineStage`, `BaseAgent`, `ToolRegistry` or `McpGateway`, **Rule 5 would be triggered against
  Tier 1** and the milestone would stop before implementation.
- If genuine hard-budget enforcement turned out to require reservation *before* provider execution,
  and the existing architecture could not represent that capability-locally (without Redis or a
  Tier-1 change), the milestone would stop and report the architectural finding rather than ship a
  settlement-only mechanism mislabeled as hard enforcement.
- If the Phase-1 illustrative `budget`/`reservation`/`usage_ledger` tables (already migrated in
  `0001_initial.sql`, discovered by inspecting actual Alembic state rather than trusting
  `docs/Schema.sql`) could be reused without fabricating unconsumed catalog/scope data or coercing
  a non-UUID `correlation_id` into a `uuid NOT NULL` column, they should be reused rather than
  duplicated.
- If atomic reservation could not be proven against real PostgreSQL (only asserted, or only proven
  against an in-memory stand-in), the concurrency claim would not count as evidence.

**Outcome: prediction held; one falsification condition materialized honestly rather than being
argued around.**

| Item | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** - zero diff on `domain/`, `application/ports/routing.py`, `pipeline.py`, `tools.py`, `mcp.py`, `agents.py`, `application/agents/cost.py`, and `docs/adr/0016-*.md` (verified by `git diff --stat`) |
| Reservation-before-execution required for genuine hard enforcement | **Confirmed, and represented capability-locally** - `BudgetLedgerPort.reserve()` gates `ProviderExecutor.execute()`; a rejected reservation means the provider is never called. No Tier-1 change was needed to express it |
| Phase-1 illustrative tables reusable as-is | **Falsified, honestly reported, new tables built (ADR-0017)** - `budget`/`reservation`/`usage_ledger` (0001_initial.sql) model hierarchical scope, a provider/model catalog FK, and a `uuid NOT NULL request_id` with a *global* `UNIQUE` constraint; none of that is populated or consumed anywhere in this codebase, and `InferenceRequest.correlation_id` is an arbitrary `str`. Reusing them would have meant either fabricating unconsumed data (Rule 5 violation) or an unsafe type coercion. New tables (`org_budget`, `budget_reservation`, `cost_ledger`) model exactly what Slice 8's ports already define |
| Concurrency proven, not asserted | **Proven against real PostgreSQL** - `test_two_requests_racing_for_the_last_budget_only_one_succeeds` and `test_concurrent_reservations_never_exceed_the_budget_total` use `asyncio.gather` across genuinely separate connections; `InMemoryBudgetLedger` explicitly disclaims this property |
| Rule 4 | Satisfied by two real implementations (`SqlBudgetLedger`, `InMemoryBudgetLedger`) - the in-memory one proves the port's business semantics without a database but is documented as not proving atomicity, mirroring `InMemoryBudgetStore`'s own disclaimer in Slice 8 |
| Validation | **Gate 1 + Gate 2: 397 passed, 0 skipped, 96% coverage** (394 on the first pass, before the pre-commit review below found and fixed two concurrency defects and one coverage gap) - full pass, including every Postgres-backed concurrency/RLS/idempotency/precision/append-only test |

### The reservation/settlement boundary, and why settlement-only was rejected

Slice 8's `BudgetEnforcer` runs *after* `ProviderExecutor` already called the provider - honest
about its own limitation ("there is no call left to block"), but exactly the shape ADR-0004
rejected as insufficient for FR-063. This slice's falsification condition was direct: can
reservation happen *before* the call, atomically, without Redis or a Tier-1 change? It can -
`ReservationService.reserve()` -> only if permitted, `ProviderExecutor.execute()` -> `settle()` or
`release()`. `BudgetEnforcer`/`BudgetPort`/`InMemoryBudgetStore` (Slice 8) are unchanged and still
valid for their own purpose (post-hoc classification for a future alerting/reconciliation
consumer); nothing here deletes them, and nothing here pretends the new path replaces them by
fiat - it replaces them in practical enforcement value, which is recorded as an honest observation,
not acted on by deleting still-tested code with no stated mandate to do so.

### Finding: ADR-0004 already decided the mechanism question, and the honest move was a companion ADR, not a quiet reinterpretation

ADR-0004 mandates atomic Redis Lua reserve/commit, explicitly rejecting a single Postgres
transaction ("Option B") - but reading the rejection closely, it is a **performance** finding
(hot-path latency/throughput at full SaaS scale), not a **correctness** finding. This project has
no load-testing milestone yet and no Redis client anywhere in the codebase; building one now, for a
milestone with no stated throughput requirement, would have been exactly the speculative
infrastructure Rule 5 warns against one layer below protocols. Per GP-2's spirit (evidenced by
ADR-0013/14/15: a rule bent quietly is a defect waiting to be found later), this was written up as
**ADR-0017** rather than silently implementing Postgres-only reservation and calling it done. The
new ADR is explicit that it scopes, not reverses, ADR-0004: Redis Lua remains the target once a
load-testing milestone or a concrete latency requirement makes Postgres-only reservation
insufficient - evidence (GP-1), not a hypothetical.

### Finding: the "obvious" schema reuse was the wrong move, and only inspecting actual migration state (not Schema.sql) revealed it

The initial assumption - reuse `docs/Schema.sql`'s documented `budget`/`reservation`/`usage_ledger`
- would have been wrong in a way that only surfaced by reading `backend/migrations/sql/0001_initial.sql`
directly: those tables already exist (migrated, not merely documented), but shaped for a
capability this project has not built (a provider/model catalog with real rows, project/api_key
budget hierarchy, period rollover) and keyed by a `uuid` this project's actual identifier
(`correlation_id: str`) cannot safely populate. Building on the assumption that "the schema already
exists, just wire it up" would have produced either fabricated catalog rows with no reader (Rule 5
violation, the same category of finding as Slice 8's `limit_kind`) or a runtime failure the first
time a non-UUID correlation id was inserted. New, narrower tables were the correct, non-speculative
answer - not a workaround.

### Finding: not every "obvious" guard was worth building - reuse dominated over new construction

| Candidate | Verdict | Why |
|---|---|---|
| `BudgetLedgerPort` implementations mutually independent | **Genuinely new** | Two real implementations now exist (`SqlBudgetLedger`, `InMemoryBudgetLedger`); nothing previously prevented one importing the other. Built as Guard C |
| Ledger/reservation classes constructed only in the composition root | **Reused, extended** | `check_accounting_construction.py` (Slice 8's Guard 1) is a generic AST scan over a `TARGETS`/`IMPLEMENTATIONS` list - extended with the three new class names rather than writing a second script with identical logic |
| `ProviderExecutor` must not depend on the ledger/reservation seam | **Already enforced, reused unchanged** | Guard B (`provider execution does not depend on accounting`, Slice 8) forbids `gateway.application.providers` -> `gateway.application.accounting`; `ReservationService` lives under `gateway.application.accounting`, so it is already covered with zero script or contract changes |
| Tenant isolation on the three new tables | **Already enforced, reused unchanged** | `check_migration_guardrails.py`'s tenant-table detection is generic (any `CREATE TABLE` body containing `organization_id`) - it caught all three new tables with no changes to the guardrail script itself |
| Reservation/settlement atomicity | **New claim, proof mechanism is the database, not a script** | Nothing to lint here - the property is "does PostgreSQL's own row lock serialize this," provable only by real concurrent connections (`test_budget_ledger_postgres.py`), not by static analysis |
| Cost ledger append-only enforcement | **New, proven by grant + a failing-write test** | `REVOKE UPDATE, DELETE ON cost_ledger FROM app_rw` (migration 0006), proven by `test_cost_ledger_rejects_update_from_the_runtime_role` attempting the forbidden write and observing `permission denied` |

Only Guard C (import-linter, new) and the extension to the existing Guard 1 AST script were built.
Every other candidate was already covered by a prior slice's guard with zero modification - the
strongest reuse result of any slice so far, and recorded as such rather than building parallel
scripts that would have checked the same thing twice under a different name.

### Enforcement (each violated, observed failing, restored, observed passing)

| Guard | Mechanism | Violation | Observed |
|---|---|---|---|
| C (new) | import-linter (independence) | `in_memory_budget_ledger.py` imports `sql_budget_ledger.py` | 22 kept / 1 broken (`budget ledger implementations are mutually independent`); 23/23 after revert |
| 1 (extended, unmodified script logic) | AST scan (`check_accounting_construction.py`) | `settings.py` constructs `ReservationService` | exit 1, offender named (`gateway/config/settings.py: constructs ReservationService`); PASS after removal |

A third property - genuine atomic concurrency - was proven positively rather than by
deliberate-violation: `test_concurrent_reservations_never_exceed_the_budget_total` asserts exactly
5 of 10 concurrent 10-unit reservations succeed against a 50-unit budget, regardless of scheduling
order. There is no "violate it" step for a database-level guarantee; the falsifiable claim is that
the count could ever exceed 5, and it did not across the run.

### Design decisions recorded as decisions, not defaults

- **New tables, not the pre-existing `budget`/`reservation`/`usage_ledger`.** See ADR-0017 and the
  finding above - `org_budget`, `budget_reservation`, `cost_ledger`, scoped to exactly what
  `BudgetPort`/`PricingPort`/`CostAccountant` (Slice 8) already model.
- **Idempotency identity is `UNIQUE (organization_id, correlation_id)`, not a bare unique
  `correlation_id`.** The pre-existing illustrative `reservation.request_id` carries a *global*
  unique constraint; `correlation_id` is caller-supplied and tenant-local by nature, so a composite
  key is the correct identity, not an accidental global one (explicitly called out as a required
  check in the brief, and confirmed by `test_two_tenants_may_independently_reuse_the_same_correlation_id`
  / `test_rls_prevents_settling_a_reservation_through_the_wrong_tenant`).
- **The atomic primitive is a single conditional `UPDATE ... WHERE ... RETURNING`, not an explicit
  `SELECT ... FOR UPDATE`.** PostgreSQL's own `UPDATE` re-evaluates its `WHERE` clause against the
  latest committed row when unblocked from a lock wait (the "first updater wins, re-check" rule) -
  the same indivisible read-check-write property ADR-0004 wanted from a Lua script, without a
  second explicit locking statement.
- **`settle()` takes a port-local `SettlementDetail`, not the accounting layer's `CostRecord`.** The
  port must not import a concrete orchestrator's type; `SettlementDetail` restates the same facts
  so the budget update and the `cost_ledger` insert happen in one transaction (no partial write
  between "spend booked" and "ledger entry written").
- **Reservation estimate reuses `CostAccountant`'s own rounding math (`compute_cost`), not a
  separate formula.** An estimate and its own settlement rounding the same fractional cost
  differently would be exactly the silent-disagreement Rule 3 exists to prevent.
- **The estimator is a deliberately conservative, character-based heuristic** (no tokenizer exists
  in this project) - `completion_tokens` is assumed as large as `prompt_tokens`, more conservative
  than `InMemoryProviderClient`'s own actual-usage synthesis (half the prompt), so a reservation is
  expected to exceed the fake client's real usage in tests, not fall short of it.

### Known limitations, stated rather than concealed

- **Not yet at ADR-0004's original hot-path performance target.** A single row-locked `UPDATE` on
  a hot budget row becomes a serialization point under very high concurrent QPS *against the same
  organization* - correctness is proven, NFR-P05 (≤5ms)/NFR-S05 (≥10k records/s) at full SaaS scale
  is not claimed. ADR-0017 records this explicitly and names Redis Lua reserve/commit as the future
  mechanism once a load-testing milestone provides the evidence (GP-1) that Postgres-only
  reservation is insufficient.
- **No reservation-expiry reconciler.** A reservation abandoned mid-flight (process crash between
  provider execution and settlement) holds its budget reservation until the same `correlation_id`
  is retried by the caller. ADR-0004 itself deferred a "reconciler" to a later milestone; this
  narrower mechanism inherits the same deferred obligation rather than fabricating one.
- **Pricing remains `StaticPriceTable` (Slice 8), unchanged.** This slice did not touch pricing
  persistence - `price_table` (0001_initial.sql) is not populated or consumed, same posture as
  Slice 8's own decision not to touch it.
- **Project/api_key-scoped budgets are still out of scope.** `org_budget` is organization-scoped
  only, matching `BudgetPort`'s existing shape; no consumer exists for hierarchical scope (Rule 5).

### Pre-commit architectural review found two genuine concurrency defects - both fixed, re-validated

Before committing, ADR-0017 and migration `0006_budget_ledger` were checked line-by-line against
what the code actually does, per an explicit review request. Two of the eight claims under review
did not hold as originally implemented; both were data-integrity defects, not style issues, and
both were fixed rather than argued around.

1. **"Settlement cannot double-charge" was false under true concurrency.** `settle()` and
   `release()` read `budget_reservation.status` with a plain `SELECT`, then branched on it. Two
   concurrent `settle()` calls for the *same* `correlation_id` could both read `status="reserved"`
   before either committed, and both would then apply their own `org_budget` update -
   `budget_reservation.status` still ended up correctly `"committed"` (looking idempotent), but the
   monetary side-effect ran twice. **Fix:** both reads now take `SELECT ... FOR UPDATE` on the
   reservation row, so the second caller blocks until the first commits, then re-reads the
   now-terminal status and takes the no-op path. This also closes the symmetric `release()`-races-
   `settle()` case the same review line item implicitly covers ("release cannot incorrectly alter
   a settled reservation").
2. **The `(organization_id, correlation_id)` idempotency boundary was incomplete for a true
   concurrent double-submit of a brand-new id.** `reserve()`'s "already reserved?" lookup and its
   atomic budget `UPDATE` are two separate statements; two concurrent `reserve()` calls for the
   same never-before-seen `correlation_id` could both pass the lookup, and the loser's budget
   `UPDATE` would then evaluate against the winner's *already-committed* reserved amount and
   correctly-by-its-own-logic-but-wrongly-for-this-case report `EXCEEDED` for what is actually its
   own already-satisfied duplicate, not a competing request. **Fix:** `reserve()` now opens with a
   transaction-scoped PostgreSQL advisory lock (`pg_advisory_xact_lock`) keyed on
   `(organization_id, correlation_id)` - there is no row to lock yet, so a row lock cannot serve
   this purpose. The second caller blocks until the first fully commits, then correctly finds the
   existing reservation and replays it idempotently.

Both were caught by adding tests that exercise genuine concurrent duplicate calls with
`asyncio.gather` (`test_concurrent_settlement_of_the_same_reservation_never_double_charges`,
`test_concurrent_duplicate_reservation_never_double_holds_budget`) - the original test suite only
exercised concurrent *different* correlation ids (a true race for scarce budget, which was already
correct) and *sequential* duplicate retries (already correct via the idempotency lookup); neither
exercised concurrent *identical* correlation ids, which is exactly where both defects lived. A
third gap surfaced while re-checking the review's "release cannot incorrectly alter a settled
reservation" line item against the test suite: the reverse order (`settle()` then `release()`) had
no test, only `release()` then `settle()`. Added
`test_release_of_an_already_settled_reservation_is_a_safe_no_op` to close it - the behavior was
already correct in the implementation, this closed a coverage gap, not a third defect. Full Gate 1
+ Gate 2 was re-run after each change: **397 passed, 0 skipped, 96% coverage** (up from 394,
reflecting the three new tests), import-linter 23 kept / 0 broken, mypy strict clean.

An initial, more complex fix attempt (catching the `IntegrityError` a concurrent duplicate `INSERT`
would raise and recovering via a fresh idempotent-replay lookup) was implemented, tested, and then
deliberately removed once the advisory lock proved sufficient on its own: with the lock in place,
that recovery path becomes unreachable dead code, and carrying it anyway would have been exactly
the unnecessary defensive complexity this project's own conventions warn against. One correct
mechanism was kept in preference to two, one of which was inert.

### Decision

**No action against ADR-0016** (frozen, unchanged). **New ADR-0017 accepted**, scoping (not
reversing) ADR-0004: PostgreSQL-transactional reserve/commit is the current, verified hard-
enforcement mechanism; Redis Lua remains the documented future mechanism for when scale evidence
demands it.

### Lessons

- **Reading actual migration state instead of trusting `docs/Schema.sql` changed the entire design.**
  The instruction to treat Schema.sql as documentation, not proof, was not a formality - the
  Phase-1 tables genuinely exist, and reusing them without checking would have produced either
  fabricated data or a runtime type error, not merely redundant work.
- **A rejected ADR option can still be correct under a narrower claim than the one it was
  rejected for.** ADR-0004 rejected Postgres transactions for a *performance* reason; treating that
  as a blanket correctness rejection would have forced Redis infrastructure with no consumer.
  Reading *why* a decision was made, not just *that* it was made, was what unlocked this slice.
- **The strongest guard-reuse result yet came from a slice that added the least new enforcement
  surface.** Three of five relevant guards required zero new code - a sign the prior slices'
  contracts were drawn at the right level of generality, not that this slice skipped enforcement.

## Evidence Record - Phase 4 Slice 10: Semantic-Safe Response Caching & Request Deduplication

**Classification:** Capability milestone. **Evidence strength: STRONG** - the Rule 5 determination,
the cache-identity-vs-deduplication-identity distinction, and the schema-reuse finding were all
determined and stated before any caching code was written.

**Pre-registered prediction.** Exact-match response caching and process-local request
deduplication can be built entirely as a capability consuming existing seams (`RoutingExecution`,
`ProviderExecutor`, `ReservationService`, `UnitOfWork`/RLS), without widening any Tier-1 protocol,
without treating a cache hit as provider execution, and without conflating cache identity with
deduplication identity.

**Falsification conditions**

- If a cache lookup could only be expressed by widening `RoutingDecision`, `RoutingExecution`,
  `PipelineStage`, `BaseAgent`, `ToolRegistry` or `McpGateway`, **Rule 5 would be triggered against
  Tier 1** and the milestone would stop before implementation.
- If caching and request deduplication turned out to be the same concept (the brief's explicit
  instruction: assume NO until proven otherwise), building one port/mechanism for both would be the
  correct move; if they are genuinely different, building one for both would silently conflate a
  durable, content-keyed identity with a transient, correlation-keyed one.
- If a cache hit could not be represented without incurring `ProviderUsage`, cost, or a budget
  reservation, "semantic-safe" caching would not be achievable without either fabricating usage
  data or bypassing budget enforcement - either would be a defect, not a feature.
- If genuine, distributed (cross-process) request deduplication were required for correctness (not
  merely desirable), and this milestone had no evidence demanding it, building Redis infrastructure
  for it would repeat exactly the speculative-infrastructure mistake ADR-0017 already identified and
  avoided for the budget ledger.
- If the pre-existing `semantic_cache_entry` table required fabricating unconsumed catalog/scope
  data (mirroring Slice 9's finding about `budget`/`reservation`), a new, narrower table would be
  required instead.

**Outcome: prediction held on every condition; one condition (distributed dedup) evaluated to "not
required" rather than "impossible", so nothing was built for it, per GP-1.**

| Item | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** - zero diff on `domain/`, `application/ports/routing.py`, `pipeline.py`, `tools.py`, `mcp.py`, `agents.py`, `application/agents/runtime.py`, and `docs/adr/0016-*.md` (verified by `git diff --stat`); `InferenceRequest`/`ProviderResponse`/`RoutingExecution` themselves are unmodified |
| Caching vs. deduplication - same concept? | **Confirmed different, by construction** - cache identity is `(organization_id, provider, model, canonical payload)` (`compute_cache_key`), deliberately excludes `correlation_id`; deduplication identity is `(organization_id, correlation_id)` (`RequestDeduplicator`), deliberately content-blind. Proven distinct by `test_different_organizations_with_the_same_correlation_id_do_not_coalesce` (dedup) and `test_different_organization_produces_a_different_key_even_for_identical_content` (cache) exercising opposite axes |
| Cache hit represented without fabricated usage/cost/budget | **Confirmed** - `InferenceCoordinator` returns `ProviderResponse(usage=None)` on a hit and never calls `ReservationService.reserve/settle` for it; proven by `test_a_cache_hit_reports_no_usage` and `test_a_cache_hit_never_calls_the_provider_or_touches_budget` |
| Distributed deduplication required? | **Not required by this milestone - not built (GP-1)** - `RequestDeduplicator` is process-local (`asyncio.Task`-based single-flight); the gap (two replicas, same `correlation_id`, same moment) is documented, not hidden, and closed only for double-*charging* by Slice 9's existing durable idempotency, not for a double provider *call* |
| Phase-1 table reusable as-is | **Confirmed reusable, no new migration (ADR-0018)** - unlike Slice 9's finding, `semantic_cache_entry`'s nullable `project_id`/`model_id`/`embedding_id`/`prompt_fingerprint` require no fabricated data; its `organization_id uuid NOT NULL`/`request_hash bytea NOT NULL`/`response jsonb NOT NULL`/`expires_at` shape already fits exact-match caching, and it already carries RLS + `app_rw` grants from `0001_initial.sql`/`0003_database_roles.sql` |
| Rule 4 | Satisfied by two real implementations (`SqlResponseCache`, `InMemoryResponseCache`) - the in-memory one proves the port's business semantics without a database but is documented as not proving RLS, mirroring `InMemoryBudgetLedger`'s own disclaimer in Slice 9 |
| Validation | **Gate 1 + Gate 2: 440 passed, 0 skipped, 96% coverage** - full pass, including every Postgres-backed RLS/TTL/malformed-entry/outage test |

### What is safe to cache, what must never be cached, and where a lookup sits in the execution path

Answered explicitly before implementation, per the brief's numbered questions:

1. **Safe to cache:** a successful (`ok=True`) provider response for a request whose entire
   canonicalized payload, provider, and model exactly match a prior cached request under the same
   organization. "Exact match" includes every field a caller sent, including any
   temperature/randomness setting - nothing here tries to guess which fields are "safe" to ignore.
2. **Never cached:** authorization decisions, budget decisions, `RoutingDecision`, exceptions,
   policy denials, authentication state, tenant context, secrets/credentials, and any failed
   (`ok=False`) provider response. Enforced structurally: `InferenceCoordinator` only calls
   `cache.put()` after a successful settlement, never on the failure branch, never on a denial
   branch, and the cache package cannot import the authorization or budget-ledger seams at all
   (import-linter Guards 2/3, Slice 10).
3. **Where a lookup can occur without bypassing authorization or budget:** after `AuthorizationStage`
   has already run (upstream, in the pipeline - this package never imports that seam) and after
   `RoutingEngine`/`AgentRuntime` have already resolved a provider (a cache hit needs to know
   *which* provider/model would have been called, which only routing decides). A hit is not a
   bypass of budget enforcement, because a hit spends nothing there is anything to enforce against.
4. **Does a cache hit represent provider execution?** No - `ProviderExecutor.execute` is never
   called on a hit.
5. **Should a hit create `ProviderUsage`?** No - none was observed; fabricating it would
   misrepresent an event that never happened (the same discipline `CostAccountant.MissingUsageError`
   already applies to a different case).
6. **Should a hit create cost?** No - `ReservationService.settle` is never called for a hit.
7. **Should a hit reserve budget?** No - `ReservationService.reserve` is never called for a hit;
   there is nothing to gate because nothing will be spent.
8. **Tenant isolation in cache identity:** `organization_id` is baked directly into the SHA-256
   digest (defence in depth), the in-memory adapter additionally keys its map by
   `(organization_id, digest)`, and the SQL adapter is RLS-bound via the same
   `AsyncUnitOfWork(tenant_id=...)` mechanism every other tenant table uses - proven even for a
   deliberately colliding raw key by
   `test_cross_tenant_lookup_is_isolated_by_rls_even_for_a_colliding_key`.
9. **Provider/model/request semantics in cache identity:** `provider.name`, `provider.model`, and
   the entire canonicalized request payload all participate in the digest.
10. **What request fields affect semantic equivalence?** All of them - the entire payload is
    canonicalized and hashed; nothing is selectively excluded (Rule 3: no undocumented convention
    about which fields "don't matter").
11. **Is `correlation_id` part of cache identity or deduplication identity?** Deduplication identity
    only. It is explicitly excluded from the cache key.
12. **Are caching and deduplication the same concept?** No - see the outcome table above.
13. **Can this be implemented without changing Tier-1 protocols?** Yes - confirmed by the zero-diff
    check above.

### The reused/new/redundant/vacuous guard evaluation

| Candidate | Verdict | Why |
|---|---|---|
| `ResponseCachePort` implementations mutually independent | **Genuinely new** | Two real implementations now exist (`SqlResponseCache`, `InMemoryResponseCache`); nothing previously prevented one importing the other |
| Cache/dedup/coordinator classes constructed only in the composition root | **Genuinely new script** | Classified NEW rather than extending `check_accounting_construction.py`/`check_provider_construction.py`: caching is a new capability boundary (new port, new adapter package, new application package), not more classes inside an existing one - the same distinction that made Slice 9 correctly *extend* an existing script instead of adding a new one |
| Cache adapters must not depend on accounting, budget ledger, or authorization | **Genuinely new contract** | Nothing previously restricted `gateway.adapters.cache`; without it, a future edit could have the cache adapter itself decide "was this authorized" or "does this affect spend" |
| Inference coordination must not depend on authorization | **Genuinely new contract** | Structural proof that cache/dedup/coordination "cannot bypass authorization": it has nothing to bypass, because it cannot even import the seam |
| `RoutingDecision` constructed only by `AgentRuntime` | **Already enforced, reused unchanged** | `check_routing_decision_construction.py` (Slice 6) is a whole-repo AST scan with no target-file allowlist beyond `agents/runtime.py` - it automatically covers every new Slice-10 file with zero changes, proven by planting a construction call in `inference_coordinator.py` and observing FAIL |
| `AgentRuntime` referenced only by the routing engine | **Already enforced, reused unchanged** | `check_routing_engine.py` Guard L scans for *any* reference to the name `AgentRuntime`, not just calls - automatically covers Slice 10, proven the same way |
| Application layer stays framework-free (no `sqlalchemy`/adapters) | **Already enforced, reused unchanged** | The general "application is framework-free and inward-only" contract (pre-existing) automatically covers `gateway.application.execution`; proven by planting `import sqlalchemy` in `deduplicator.py` and observing BROKEN |
| Tenant isolation on `semantic_cache_entry` | **Not applicable - no migration to guard** | This slice added no migration (ADR-0018); `check_migration_guardrails.py` has nothing new to scan. RLS on the table predates this slice (`0001_initial.sql`) and was verified, not (re)built |
| A `DeduplicationPort` protocol with two implementations | **Considered, rejected as vacuous/premature** | Exactly one correct implementation exists (process-local `asyncio.Task` coalescing); a `Protocol` with a single conceivable implementation and no second one to prove substitutability would be exactly the speculative-abstraction Rule 4/GP-1 warns against. `RequestDeduplicator` is a concrete class, not a port, mirroring `ReservationService`/`ProviderExecutor` |

### Enforcement (each violated, observed failing, restored, observed passing)

| Guard | Mechanism | Violation | Observed |
|---|---|---|---|
| Response cache independence (new) | import-linter (independence) | `in_memory_response_cache.py` imports `sql_response_cache.py` | 25 kept / 1 broken; 26/26 after revert |
| Cache adapters vs. accounting/ledger/authorization (new) | import-linter (forbidden) | `sql_response_cache.py` imports `gateway.application.accounting.cost_accountant` | 25 kept / 1 broken; 26/26 after revert |
| Inference coordination vs. authorization (new) | import-linter (forbidden) | `inference_coordinator.py` imports `gateway.application.authorization.requirements` | 25 kept / 1 broken; 26/26 after revert |
| Execution construction (new script) | AST scan (`check_execution_construction.py`) | `cache_key.py` constructs `InferenceCoordinator` | exit 1, offender named; PASS after removal |
| `RoutingDecision` construction (reused) | AST scan (`check_routing_decision_construction.py`) | `inference_coordinator.py` constructs `RoutingDecision(...)` | exit 1, offender named; PASS after removal |
| `AgentRuntime` reference (reused) | AST scan (`check_routing_engine.py`) | `inference_coordinator.py` references bare name `AgentRuntime` | exit 1 (`[L]` offender named); PASS after removal |
| Application framework-free (reused, general) | import-linter (forbidden) | `deduplicator.py` imports `sqlalchemy` | 25 kept / 1 broken; 26/26 after revert |

A first attempt at proving the `RoutingDecision` construction guard used a bare name reference
(`_bad = RoutingDecision`) rather than a call - this correctly did **not** trip the guard, because
the guard is deliberately scoped to *construction* (`RoutingDecision(...)`), not *reference*
(unlike Guard L for `AgentRuntime`, which is deliberately scoped to any reference). Recorded here
rather than silently corrected, because it is itself evidence the guard's AST logic was actually
exercised, not assumed - the mutation had to genuinely trigger the code path the guard scans for.

### Design decisions recorded as decisions, not defaults

- **Exact-match only, no embedding/semantic-similarity tier.** ADR-0006 decided a two-tier
  (Redis exact + `pgvector` semantic) cache; no Redis client, embedding pipeline, or event-bus
  consumer exists anywhere in this codebase. Building either for a milestone with no
  similarity-threshold or hit-rate requirement would be the same speculative-infrastructure mistake
  ADR-0017 already identified for Redis Lua reserve/commit. See ADR-0018.
- **`semantic_cache_entry` reused as-is, no new migration.** Unlike Slice 9's `budget`/
  `reservation` tables, this table's nullable dimensions (`project_id`, `model_id`, `embedding_id`,
  `prompt_fingerprint`) do not force fabricating unused catalog data, and its NOT NULL columns
  (`organization_id`, `request_hash`, `response`) are exactly what exact-match caching needs.
- **Cache identity is a SHA-256 digest via a new `shared.secrets.sha256_bytes` helper, not a raw
  `hashlib` call in the cache module.** The existing "low-level crypto primitives only via
  `shared.secrets`" import-linter contract (predates this slice) forbids importing `hashlib`
  outside that boundary; a raw-bytes-digest sibling to the existing `sha256_hex` was added there
  rather than carving an exception into the guard.
- **Deduplication wraps only the cache-miss path.** A hit is a pure read with no side effects;
  wrapping it in `RequestDeduplicator.coalesce` would add coordination overhead for a case that
  needs none.
- **`InferenceCoordinator` is a new orchestrator, not a merge into `ReservationService` or
  `ProviderExecutor`.** It composes both unchanged, plus the new cache/dedup capabilities - the
  first real, tested proof of the full reserve/execute/settle sequence those two classes'
  docstrings had described but left to "a future delivery-layer handler" since Slice 9.
- **`RequestDeduplicator.coalesce` uses `asyncio.shield`, not a bare `await task`.** Without it, a
  caller whose own request is independently cancelled (e.g. its timeout) would cancel the
  underlying operation for every other caller sharing it - proven by
  `test_a_cancelled_waiter_does_not_cancel_the_operation_for_other_waiters`.

### Known limitations, stated rather than concealed

- **No near-duplicate ("semantic similarity") caching.** Only literal exact matches hit; a prompt
  differing by one character is a full miss. Explicitly deferred to a future milestone with evidence
  of a near-duplicate hit-rate opportunity (ADR-0018).
- **No cross-process (distributed) deduplication.** `RequestDeduplicator` is process-local; two
  gateway replicas receiving the same `correlation_id` at the same moment could each call the
  provider once. Slice 9's durable ledger idempotency still prevents double-*charging* in that case,
  but not the double provider *call* itself. Deferred until running more than one replica is an
  actual deployment shape (GP-1).
- **No "cache stampede" protection across different correlation ids with identical content.** Two
  different logical requests (different `correlation_id`) with identical payloads arriving
  concurrently before either has populated the cache will both miss and both call the provider -
  deduplication is keyed on correlation identity, not content identity, by design (see the
  cache-vs-dedup finding above). Documented as a known, explicitly out-of-scope limitation, not a
  defect.
- **No explicit purge or model/version-driven invalidation.** Only TTL expiry (default one hour)
  exists; ADR-0006's FR-058 (explicit purge, model/version change) is not implemented.
- **`hit_count` and `prompt_fingerprint` are not populated.** Real, pre-existing columns on
  `semantic_cache_entry` that this slice's adapter does not maintain - left at their defaults
  rather than fabricated, matching ADR-0017's precedent for `org_budget`'s unused dimensions.

### Decision

**No action against ADR-0016** (frozen, unchanged). **New ADR-0018 accepted**, scoping (not
reversing) ADR-0006: PostgreSQL-backed exact-match caching plus process-local deduplication is the
current, verified mechanism; Redis exact-tier and `pgvector` semantic-tier caching remain the
documented future mechanism for when evidence demands them.

### Lessons

- **Not every schema-reuse finding goes the same direction.** Slice 9 found the Phase-1 tables
  needed replacing; Slice 10 found the Phase-1 table needed no changes at all. Reading the actual
  column shape and constraints each time - not applying the prior slice's conclusion by analogy -
  was what caught the difference.
- **A concept split (cache identity vs. deduplication identity) prevented a subtler bug than either
  concept alone would have.** Building one mechanism for both would likely have "worked" in the
  common case and failed exactly at a cross-tenant correlation-id collision or a stale-cache-served-
  as-a-duplicate edge - the kind of defect that passes review and fails in production.
- **Choosing not to build something is itself a recorded, falsifiable decision.** Distributed
  deduplication was evaluated, found not required by any concrete requirement in this milestone,
  and explicitly not built - the same GP-1 discipline ADR-0017 established for Redis Lua
  reserve/commit, applied a second time to a different capability.

## Evidence Record - Phase 4 Slice 11: Reflection / Retry Layer

**Classification:** Capability milestone. **Evidence strength: STRONG** - the Rule 5 determination,
the retry classification, the no-rerouting decision and the attempt-identity analysis were all
determined and stated before any reflection code was written. The slice also *falsified its own
pre-registered prediction on one point* (a capability-owned protocol did have to change) and, while
analysing retry semantics, found a genuine pre-existing defect in Slice 9's ledger that was
reachable from Slice 10's coordinator - both recorded below rather than smoothed over.

**Pre-registered prediction.** Bounded, explainable retry can be built entirely as a capability
consuming existing seams (`InferenceCoordinator`, `RoutingExecution`, `Sleeper`), without widening
any Tier-1 protocol, without creating a second routing engine/provider executor/explanation model,
and without a hidden unbounded loop.

**Falsification conditions**

- If retry could only be expressed by widening `RoutingDecision`, `RoutingExecution`,
  `PipelineStage`, `BaseAgent`, `ToolRegistry` or `McpGateway`, **Rule 5 would be triggered against
  Tier 1** and the milestone would stop before implementation.
- If deciding *whether* to retry required reflection to select a provider, reroute, or otherwise
  make a routing decision, the responsibility boundary would be violated and the slice would stop
  and report rather than build a second routing authority.
- If classifying a failure as transient-vs-permanent could not be done from typed data, the only
  alternative would be string-matching a free-form `error` message - a silent convention Rule 3
  forbids - and the slice would have to report that instead of shipping it.
- If retry across attempts could not keep budget reservation and cost accounting correct, the
  slice would stop rather than ship a retry path that double-charges or under-charges a tenant.

**Outcome: prediction held on Tier 1 and on responsibility separation; falsified (honestly) on the
"no protocol change at all" clause.**

| Item | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** - zero diff on `domain/`, `application/ports/routing.py`, `pipeline.py`, `tools.py`, `mcp.py`, `agents.py`, `application/agents/runtime.py`, `application/routing/engine.py`, and `docs/adr/0016-*.md` (verified by `git diff --stat`) |
| Rule 5 against a **capability-owned** port | **TRIGGERED AND SATISFIED** - `ProviderErrorCategory` + `ProviderResponse.error_category` added to `application/ports/providers.py`. Active consumer: `application/reflection/retry_policy.py`. Recorded here, not as a new ADR - identical in shape to Slice 8 adding `usage` to the same port (ADR-0016 Rule 2 governs a seam's *birth*; this is an existing capability-owned seam evolving under Rule 5). Additive and optional: every prior construction remains valid |
| Second routing engine / executor / explanation created? | **No** - reflection's only collaborator is `InferenceCoordinator`. It cannot import `application.providers`, `application.accounting`, `ports.ledger` or `application.routing.engine` (new import-linter contract, all four proven independently), so no path exists by which a retry could reach a provider without also passing the budget gate |
| Rerouting | **Deliberately not built** - see the finding below. Reflection retries the *same* `RoutingExecution` |
| Unbounded loop possible? | **No, by construction** - the loop is `for attempt in range(1, policy.max_attempts + 1)`, a finite range; `RetryPolicy` rejects `max_attempts < 1` at construction |
| Original `RoutingDecision` mutated? | **No** - it is a frozen dataclass, carried through untouched and asserted identical (`is`) by `test_the_original_routing_decision_is_carried_through_unmodified` |
| Validation | **Gate 1 + Gate 2: 485 passed, 0 skipped, 97% coverage** - coverage *rose* one point rather than being held flat |

### Finding: a genuine pre-existing defect in Slice 9's `reserve()`, found by analysing retry - and reachable without retry

Designing attempt-scoped budget identity required reading `SqlBudgetLedger.reserve()` closely
enough to ask what a *second* reservation of the same `correlation_id` does after the first was
released. It replayed it: the idempotent-replay branch matched **any** existing row regardless of
`status`, so `reserve -> release -> reserve` returned `RESERVED` while incrementing nothing.

This was verified empirically against real PostgreSQL before any fix was written - the probe
showed `reserved=0E-8` after the re-reservation, and a competing request for the **full** limit was
then still admitted. The caller believed it held budget; the budget believed nothing was held.

Critically, **this is not a retry-only concern**: it is reachable through Slice 10's coordinator
today, with no reflection involved, whenever a provider call fails (which releases the hold) and a
client resubmits the same `correlation_id`. It was therefore fixed as a defect in its own right,
not accommodated as a retry special case:

- `reserve()`'s replay branch now covers a *live* (`reserved`) or already-settled (`committed`) row
  only. A `released` row falls through and is genuinely re-held, via a new `_hold` helper that
  re-activates the existing row instead of inserting a duplicate (the `UNIQUE (organization_id,
  correlation_id)` constraint makes a second INSERT impossible anyway).
- The advisory lock `reserve()` already takes (Slice 9's own pre-commit fix) serializes concurrent
  callers on the same key, so the new read-then-reactivate cannot race another reservation.
- `InMemoryBudgetLedger` carried the identical bug and was fixed for parity.
- Regression tests: `test_reserving_again_after_release_genuinely_re_holds_the_budget` (Postgres and
  in-memory) and `test_a_re_held_reservation_can_be_settled_normally`.

A `committed` row deliberately still replays as `RESERVED`. That case is a *caller* defect (reusing
a completed correlation id) and its exposure is an under-charge rather than an overspend, because
`settle()` is idempotent - stated here as a known limitation rather than silently widened, since no
consumer needs it and changing it would alter the documented port contract.

### Finding: rerouting was evaluated and deliberately not built

The obvious "reflection feature" is: this provider failed, try a different one. It was not built,
and that is a decision, not an omission.

Provider selection belongs to `ProviderAgent` inside `AgentRuntime`, and the routing architecture
does not delegate it here. Building rerouting would require either fabricating a provider choice
outside the only component permitted to explain one (directly violating invariant 3), or invoking
routing again to obtain a **second** `RoutingDecision` for one logical request - two explanations of
the same request, which is precisely the failure `RoutingExecution`'s own design note exists to
prevent. Neither has a consumer in this milestone, so neither was built (Rule 5). The structural
consequence is enforced, not merely intended: reflection cannot import `application.routing.engine`
at all, proven by deliberate violation.

### Finding: retry needs attempt-scoped budget identity, and Slice 10's identity split made that free

Budget reservation and settlement key on `(organization_id, correlation_id)` (Slice 9). Had every
attempt reused the caller's bare `correlation_id`, attempt 2's `reserve` would have collided with
attempt 1's finished reservation and attempt 2's `settle` would have been swallowed as a duplicate -
the tenant receiving a provider call it was never charged for. Each attempt therefore executes under
a derived id, `<correlation_id>#<attempt>`.

That derivation is safe against both Slice-10 identities *because* Slice 10 kept them separate:

- **Cache identity ignores `correlation_id` entirely** (content-keyed), so retrying does not change
  which cache entry an attempt reads or writes.
- **Deduplication identity is `(organization_id, correlation_id)`**, so N concurrent duplicate
  callers derive the *same* attempt id at each step and coalesce at every attempt - the provider
  sees one call per attempt, not N. Proven by
  `test_concurrent_duplicates_do_not_trigger_independent_retry_storms` (3 duplicate callers x 3
  attempts = 3 provider calls, not 9).

Had Slice 10 conflated the two identities, this slice would have had to choose between breaking
caching and breaking deduplication. The concept split paid for itself one slice later.

### Retry classification (stated before implementation)

| Condition | Verdict | Why |
|---|---|---|
| Success (`EXECUTED` + `ok`) | SUCCEEDED | - |
| Cache hit | SUCCEEDED | A cached response is a complete, correct answer; reflection stops immediately with zero provider calls |
| Policy denial / no candidate / all unhealthy (`NOT_ROUTED`) | TERMINAL | Decisions already made and already explained by `RoutingDecision`; a retry asks a settled question hoping for a different answer |
| Authorization denial | TERMINAL (unreachable here) | Decided upstream in the pipeline; never reaches this layer. Structurally guaranteed - reflection cannot import the authorization seam |
| Budget denied | TERMINAL | The tenant is out of money; the answer is guaranteed identical |
| Budget store unavailable | TERMINAL | Already a fail-closed denial (ADR-0009 row 1); retrying aims more load at a struggling ledger |
| Provider `TIMEOUT` / `RATE_LIMITED` / `SERVER_ERROR` | RETRY | Transient by definition |
| Provider `INVALID_REQUEST` / `AUTHENTICATION` | TERMINAL | Permanent until a human changes something |
| Provider error with **no** category | TERMINAL | Fail closed - an error nobody classified is not known to be transient |
| Malformed provider output (missing/negative usage) | Not a retry signal at all | Surfaces as `MissingUsageError`/`MalformedUsageError` raised by `CostAccountant`, which that module documents as *a defect a human must fix*. Reflection does not catch exceptions as retry signals: retrying a defect is precisely wrong, and converting one into a silent retry would erase the signal |

### The guard evaluation

| Candidate | Verdict | Why |
|---|---|---|
| Reflection cannot bypass `ProviderExecutor`, author cost, move budget, or reroute | **Genuinely new (one contract, four targets)** | Nothing previously restricted `gateway.application.reflection`. `allow_indirect_imports = true` is essential and deliberate: reflection -> coordinator -> accounting/providers is the *intended* path, so only a direct reach-around is a violation. All four forbidden targets proven to trip it independently |
| Reflection classes constructed only in the composition root | **Reused, extended** | `check_execution_construction.py` (Slice 10) is a generic AST scan over a name list; reflection sits inside the same execution-orchestration construction boundary and the invariant is identical in shape. Extended with `ReflectiveExecutor`/`RetryPolicy` rather than writing a second script with identical logic - the same call Slice 9 made for the accounting script |
| Reflection cannot construct `RoutingDecision` | **Already enforced, reused unchanged** | Whole-repo AST scan with no per-slice allowlist; proven to catch a planted construction in `reflective_executor.py` with zero script changes |
| Reflection cannot invoke `AgentRuntime` | **Already enforced, reused unchanged** | Guard L scans for *any* reference to the name; proven the same way |
| Reflection cannot import provider adapter implementations | **Already enforced, redundant to add separately** | The blanket "application is framework-free and inward-only" contract already forbids `gateway.application` -> `gateway.adapters`; proven against `reflective_executor.py`. A reflection-specific adapter contract would have checked the same thing twice under a different name |
| A `RetryClassifier` / `ReflectionPort` protocol | **Considered, rejected as vacuous** | Exactly one correct classification exists and there is no second implementation to substitute; a `Protocol` here would be an abstraction with no consumer for its abstractness (Rule 4/GP-1). `classify()` is a pure function; `ReflectiveExecutor` is a concrete orchestrator, mirroring `ReservationService`/`ProviderExecutor`/`InferenceCoordinator` |

### Enforcement (each violated, observed failing, restored, observed passing)

| Guard | Mechanism | Violation | Observed |
|---|---|---|---|
| Reflection boundary (new) | import-linter (forbidden, `allow_indirect_imports`) | `retry_policy.py` imports `application.providers.provider_executor` | 26 kept / 1 broken; 27/27 after revert |
| Reflection boundary (new) | same | `reflective_executor.py` imports `application.accounting.cost_accountant` | 26 kept / 1 broken; restored |
| Reflection boundary (new) | same | `reflective_executor.py` imports `application.ports.ledger` | 26 kept / 1 broken; restored |
| Reflection boundary (new) | same | `reflective_executor.py` imports `application.routing.engine` | 26 kept / 1 broken; restored |
| Execution construction (reused, extended) | AST scan (`check_execution_construction.py`) | `routing/engine.py` constructs `ReflectiveExecutor` | exit 1, offender named; PASS after removal |
| Execution construction (reused, extended) | same | `config/settings.py` constructs `RetryPolicy` | exit 1, offender named; PASS after removal |
| `RoutingDecision` construction (reused) | AST scan | `reflective_executor.py` constructs `RoutingDecision(...)` | exit 1; PASS after removal |
| `AgentRuntime` reference (reused) | AST scan (Guard L) | `reflective_executor.py` references `AgentRuntime` | exit 1 (`[L]` offender); PASS after removal |
| Application framework-free (reused, general) | import-linter | `reflective_executor.py` imports `adapters.providers.fake_client` | 26 kept / 1 broken; restored |

**A failed proof attempt is recorded here as evidence rather than quietly corrected.** The first
attempt to prove the extended construction guard planted `ReflectiveExecutor(...)` and
`RetryPolicy(...)` inside `inference_coordinator.py` - and the guard **passed**, which initially
looked like a broken guard. It was not: that file is in the script's `IMPLEMENTATIONS` exemption
list, so the mutation never reached the code path being tested. Re-planting the same violations in
non-exempt files (`routing/engine.py`, `config/settings.py`) produced the expected exit 1. This is
exactly the "verify the mutation actually occurred and actually triggered the guard" discipline the
project's enforcement philosophy demands - a proof that passes for the wrong reason is worth less
than no proof, because it manufactures false confidence.

That episode also surfaced a **known limitation of the construction-guard pattern**, shared by all
four such scripts (Slices 7-11): the `IMPLEMENTATIONS` exemption is file-name-based and exempts a
file from *every* target in the list, not just the class it defines. So `inference_coordinator.py`
could legitimately construct a `SqlResponseCache` without tripping the guard. This is pre-existing
and consistent across the project rather than introduced here; it is recorded as an observed
limitation rather than silently rewritten across four scripts in a slice that has no consumer
demanding the tightening.

### Design decisions recorded as decisions, not defaults

- **`ProviderErrorCategory` has no `UNKNOWN` member.** "Not classified" is already expressible as
  `error_category=None`; a second spelling of the same fact would be two sources of truth for one
  condition (Rule 3).
- **An unclassified failure is non-retryable.** The fail-closed direction: retrying a failure
  nobody has classified spends the tenant's money on a guess.
- **`Sleeper` is a separate protocol from `Clock`, not a method on it.** Reading time and elapsing
  it are different capabilities, and most `Clock` consumers must never be able to block.
- **`max_attempts` counts total attempts, not retries.** `1` therefore means "never retry" and is
  the validated floor - an off-by-one here would silently double every tenant's provider spend.
- **Exponential backoff, no jitter.** Jitter de-synchronises a fleet of callers; this project has
  no such fleet and no requirement describing one, so it would be an untestable knob with no
  consumer (Rule 5). The delay sequence is deterministic and asserted exactly.
- **`FakeProviderClient` gained a per-call `sequence`.** A provider-keyed dict answers every call
  identically and structurally cannot express "fails twice, then succeeds" - the exact shape a
  retry layer exists to handle. Real consumer in this slice; the final entry repeats so an
  over-eager policy keeps seeing the same terminal state rather than falling through to different
  behaviour.

### Known limitations, stated rather than concealed

- **No rerouting.** A retry always targets the same provider the original routing decision selected.
  See the finding above - this is a deliberate boundary, revisited only if the routing architecture
  explicitly delegates provider selection to reflection.
- **No cross-process retry coordination.** Two replicas each running a reflection loop for the same
  request would each retry independently; deduplication is process-local (Slice 10's documented
  limitation, inherited unchanged).
- **A `committed` reservation still replays as `RESERVED`.** Documented above; an under-charge on a
  caller defect, not an overspend.
- **Reflection is not wired into any request path yet.** Like `ReservationService` and
  `InferenceCoordinator` before it, it is constructed in the composition root and proven by tests;
  no HTTP handler consumes it, because no inference endpoint exists yet in this project.
- **No per-tenant or per-route retry policy.** One deployment-wide `RetryPolicy`; nothing consumes
  a per-tenant variant, so none is built (Rule 5).

### Decision

**No action against ADR-0016** (frozen, unchanged). **No new ADR** - unlike Slices 9 and 10, this
slice contradicts no existing Accepted decision and introduces no mechanism an ADR had already
decided differently, so writing one would be ceremony rather than governance. The one protocol
change is a Rule 5 event on a capability-owned port, recorded here, exactly as Slice 8's `usage`
field was.

### Lessons

- **Analysing a new capability is one of the better ways to audit an old one.** The phantom-hold
  defect had survived Slice 9's own pre-commit review, its concurrency test suite, and all of Slice
  10 - because every existing test released *or* re-reserved, never both in sequence. Asking "what
  does retry need from this?" exposed it in minutes.
- **A prediction that is falsified in a small, specific way is more useful than one that holds
  vacuously.** "No protocol change at all" turned out to be wrong: classification genuinely could
  not be expressed without typed data on the response. Recording the trigger and its justification
  is what keeps Rule 5 a live check rather than a box to tick.
- **The previous slice's discipline paid its own cost back.** Slice 10's insistence that cache
  identity and deduplication identity are different concepts is precisely what let attempt-scoped
  retry identity be introduced without breaking either.

## Evidence Record - Phase 4 Slice 12: Evaluation Pipeline

**Classification:** Capability milestone. **Evidence strength: STRONG** - the Rule 5 determination,
the observation boundary, the first-evaluator choice and the no-persistence decision were all
settled before any evaluation code was written.

**Pre-registered prediction.** Evaluation can be built entirely as a Tier-2 consumer of already
completed execution outcomes: no Tier-1 protocol change, no capability-owned port change, no new
field anywhere, and no route by which an evaluator could participate in the request it judges.

**Falsification conditions**

- If evaluation required a new field on `ProviderResponse`, `RoutingDecision`, `RoutingExecution`,
  `InferenceRequest`, `PipelineStage` or any Tier-1 seam, **Rule 5 would fire** and the slice
  would stop before implementation.
- If the only deterministic evaluator worth writing needed data this system cannot observe
  (latency, structured-output schemas, semantic quality), the slice would have to report that
  rather than invent the metric.
- If evaluation could not be prevented *structurally* from routing, executing, budgeting or
  retrying - only by review - the "evaluation observes" claim would be a convention, not a
  boundary.

**Outcome: prediction held on every condition.**

| Item | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** - zero diff on `domain/`, `ports/routing.py`, `pipeline.py`, `tools.py`, `mcp.py`, `agents.py`, `agents/`, `routing/`, ADR-0016 |
| Rule 5 against any capability-owned port | **NOT TRIGGERED** - unlike Slice 11 (which had to add `ProviderErrorCategory`), evaluation needed no new field at all. It reads `ExecutionOutcome`, `ProviderResponse.ok/content/usage` exactly as they already exist |
| Is it a `PipelineStage`? | **Deliberately not** - see the finding below. The stage seam is untouched and remains available; Slice 13 is the capability that genuinely consumes it |
| Persistence | **None built** - no consumer needs evaluation history, so no table, no migration, no RLS work (GP-1: evidence, not anticipation) |
| Rule 4 | Satisfied by two real, independent evaluators plus the runner as consumer; a third (`ExplodingEvaluator`) exists only as a test double for the `ERROR` path |
| Validation | **Gate 1 + Gate 2: 520 passed, 0 skipped, 97% coverage** at Slice-12 completion; all new modules at 100% line coverage |

### Finding: evaluation is Tier-2 as ADR-0016 predicted, but *not* by implementing `PipelineStage`

ADR-0016 demoted Evaluation from Tier 1 on the reasoning that it should consume the stable
interception seam rather than requiring every interface to know evaluation exists. The demotion is
vindicated - nothing in Tier 1 changed - but the mechanism is not the one the ADR's wording
implies, and that difference is worth recording rather than glossing:

1. **Evaluation is post-hoc, not interception.** It needs the *finished* result: outcome, response,
   usage. `PipelineStage.after_response` receives a `StageContext` whose `attributes` is
   `dict[str, Any]` and is documented as opaque by contract. Passing a rich typed result through an
   untyped bag would convert a checked contract into a convention - exactly what Rule 3 exists to
   prevent, and a strictly *worse* guarantee than the typed alternative.
2. **No pipeline runner exists.** Nothing in this codebase executes a chain of stages around an
   inference. Implementing `PipelineStage` today would have produced a seam consumed by nothing
   (Rule 4) - the abstraction would have looked like compliance while enforcing less.

So evaluation consumes typed capability-owned objects instead. The Tier-2 claim (a capability can
be added without disturbing Tier 1) is confirmed; the assumption that *the way* it happens is
always "become a stage" is not. Slice 13 exercises the stage route on a capability that genuinely
intercepts, which is where it fits.

### Finding: the useful first evaluator was one that checks an invariant the money path already assumes

The brief warned against inventing metrics the system cannot observe. Latency is not recorded
anywhere (`ProviderResponse` carries no timing; `AttemptRecord` carries none); structured-output
schemas do not exist (`content` is `Any`). Both were rejected on that basis.

What the system *does* have is an unchecked invariant that runs in **opposite directions** depending
on how a response was produced:

- An **executed** success must carry `ProviderUsage` - `CostAccountant.account()` raises
  `MissingUsageError` without it and `ReservationService.settle()` cannot convert the reservation
  into recorded spend. A delivered success with no usage means either unbooked spend or a budget
  reservation still held.
- A **cache hit** must carry no usage - Slice 10 sets `usage=None` deliberately, because
  fabricating consumption for a call that never happened would misrepresent an observation. Usage
  on a hit would mean the cache had begun inventing consumption, and anything metering it would
  over-bill.

`UsageAccountingConsistencyEvaluator` observes both directions. Nothing else in the system checks
either, and it needed no new data to do it. `ResponseCompletenessEvaluator` covers a second real
defect class: `ProviderResponse.content` is `Any` with a `None` default, so an adapter can report
success while delivering nothing - and Slice 10 would then cache it and Slice 9 would settle real
money against it.

**A test discovered the limit of that second evaluator's reach, and it is recorded rather than
hidden.** The `EXECUTED + ok + usage=None` branch is unreachable *through the coordinator*: an
attempt to drive it end-to-end failed with `MissingUsageError`, because settlement rejects such a
response first. The branch is therefore defence in depth - it would catch the same defect if
settlement were ever made lenient - not a path exercised in today's wiring. The test was rewritten
to use a genuinely reachable scenario (content-less but settleable) rather than left asserting
something the architecture already prevents.

### Finding: four result states, because three would lie

The brief required distinguishing "the evaluator failed" from "the evaluated thing failed".
`NOT_APPLICABLE` is a fourth, and it is not padding: both evaluators need to say "this outcome is
outside what I judge" (a budget denial delivered no response to assess). Reporting that as `PASSED`
would inflate quality metrics with requests nobody evaluated; reporting it as `FAILED` would
double-count one incident in any metric built on both evaluation and `ExecutionOutcome`.

`EvaluationReport` keeps `target_failed` and `evaluation_degraded` as separate properties for the
same reason - a dashboard that cannot tell "10% of responses are bad" from "10% of evaluations
crashed" shows the same number for a quality problem and an outage.

### The guard evaluation

| Candidate | Verdict | Why |
|---|---|---|
| Evaluation cannot route, execute, budget, retry or authorize | **NEW (one contract, six targets)** | Nothing previously restricted `gateway.application.evaluation`. `allow_indirect_imports = true` is essential: evaluation -> `execution.inference_coordinator` -> accounting/providers is the *intended* path (it must name the types it judges), so only a direct reach-around is a violation |
| Evaluator implementations mutually independent | **NEW** | Same reasoning as the ProviderClient/BudgetLedgerPort/ResponseCachePort independence contracts. It also underwrites the runner's composition tests: "one evaluator's verdict cannot erase another's" is only meaningful if the two cannot reach each other |
| `EvaluationRunner` construction confined to composition root | **REUSED, extended** | `check_execution_construction.py` extended rather than duplicated. The runner owns *which* evaluators run - a component building its own would silently evaluate against a different or empty set, and its reports would look exactly as authoritative |
| The two evaluator classes confined to composition root | **NOT APPLICABLE** | Stateless, pure, no configuration authority. Constructing one elsewhere decides nothing, so guarding it would be symmetry rather than enforcement |
| Evaluation cannot import adapters | **REDUNDANT** | The blanket "application is framework-free and inward-only" contract already forbids `gateway.application` -> `gateway.adapters` |
| Evaluation cannot construct `RoutingDecision` / reach `AgentRuntime` | **REUSED, unchanged** | Both are whole-repo AST scans with no per-slice allowlist; proven against `evaluation/runner.py` |

### Enforcement (each violated, mutation verified present, observed failing, restored, observed passing)

| Guard | Violation planted | Observed |
|---|---|---|
| Evaluation observes only (new) | `runner.py` imports `application.providers.provider_executor` | 28 kept / 1 broken |
| Evaluation observes only (new) | ...`application.accounting.cost_accountant` | 28/1 |
| Evaluation observes only (new) | ...`application.ports.ledger` | 28/1 |
| Evaluation observes only (new) | ...`application.routing.engine` | 28/1 |
| Evaluation observes only (new) | ...`application.reflection.retry_policy` | 28/1 |
| Evaluation observes only (new) | ...`application.authorization.requirements` | 28/1 |
| Evaluator independence (new) | `usage_consistency.py` imports `response_completeness` | 28 kept / 1 broken |
| Execution construction (reused, extended) | `routing/engine.py` constructs `EvaluationRunner` | exit 1, offender named |
| `RoutingDecision` construction (reused) | `runner.py` constructs `RoutingDecision(...)` | exit 1 |
| Guard L / `AgentRuntime` (reused) | `runner.py` references `AgentRuntime` | exit 1 |

Every mutation was verified present in the file (`grep -c` before running the guard) so no proof
could pass for the wrong reason - the failure mode this project hit in Slice 11, where a violation
planted in an exempt file produced a false PASS. **A related hazard surfaced here and is recorded:**
`git checkout --` cannot restore an *untracked* file, so the first two restore attempts on
`runner.py` silently left the mutation in place and the second proof ran against a doubly-mutated
file (`mutation=2`). The file was cleaned programmatically and all guards re-verified green.

### Known limitations, stated rather than concealed

- **Not persisted.** Reports are returned, not stored. When a real consumer needs durable history,
  the tenant-scoped RLS-forced table it requires should be designed against that consumer's query
  shape rather than guessed at now.
- **Not wired into a request path.** Like `ReservationService`, `InferenceCoordinator` and
  `ReflectiveExecutor` before it, evaluation is composed in the container and proven by tests; no
  HTTP handler consumes it because no inference endpoint exists yet.
- **Synchronous only.** No background dispatch, deliberately - the brief warned against
  background-task races in tests, and no consumer needs asynchrony.
- **`EXECUTED + usage=None` is defence in depth**, not a live path (see the finding above).
- **No LLM-judge evaluator**, by instruction and by preference: it would add an external model
  dependency and non-determinism to prove a seam that two pure functions already prove.

## Evidence Record - Phase 4 Slice 13: Policy Engine Foundation

**Classification:** Capability milestone. **Evidence strength: STRONG** - the Rule 5 determination,
the three-way RBAC/PolicyAgent/PolicyEngine boundary, the first-policy choice and the OPA deferral
were all settled before implementation.

**Pre-registered prediction.** Policy can be added as a Tier-2 consumer of the existing
`PipelineStage` seam, unchanged, reading only `StageContext` fields that already exist - and can be
prevented structurally from becoming a second authorizer or a second router.

**Falsification conditions**

- If the first policy could not be expressed through `StageAction`'s existing
  CONTINUE/ANNOTATE/BLOCK vocabulary, or required new `StageContext` fields, **Rule 5 would fire**
  against Tier 1 and the slice would stop.
- If the only policy worth writing required data that does not exist (data classification, org
  policy flags, model capability catalog), the slice would have to report that rather than invent
  a classification system to justify itself.
- If policy-engine outage could not be made to fail closed *and* remain distinguishable from an
  ordinary denial, the security semantics would be unacceptable.

**Outcome: prediction held. This is the cleanest Tier-2 confirmation of the two slices** - policy
is exactly the shape ADR-0016 anticipated, and `PolicyStage` implements `PipelineStage` byte-for-byte
unchanged.

| Item | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** - `PipelineStage`, `StageContext`, `StageResult`, `StageAction` all unchanged; zero diff across `domain/`, all Tier-1 ports, `agents/`, `routing/`, ADR-0016 |
| `StageContext` fields consumed | `organization_id`, `correlation_id`, `attributes["request"]` - all pre-existing. The payload key is the convention `AgentRoutingStage` established in Slice 6, now named as a declared constant instead of a second magic string |
| Speculative additions | **None.** No `principal_id` on `PolicyQuery` (the first policy is identity-independent and RBAC owns identity), no provider/model (PolicyAgent owns eligibility), no evaluation results (no consumer) |
| OPA | **Deferred, explicitly** - see below |
| Fail-closed | Proven three ways, not merely documented |
| Validation | **Gate 1 + Gate 2 (combined, both slices): 546 passed, 0 skipped, 97% coverage** |

### The three-way boundary, stated before code

Three things in this system now sound like "policy". They answer different questions, and the
whole risk of this slice was letting them blur:

| Component | Question | Owns |
|---|---|---|
| RBAC - `AuthorizationStage` + `PermissionResolver` (Slice 5) | *May this **principal** perform this action?* | identity -> permission set -> declared requirement |
| `PolicyAgent` inside `AgentRuntime` (Slice 2/6) | *Which **providers/regions** is this request eligible for?* | routing-time eligibility, contributed into `RoutingDecision` |
| **Policy Engine** (this slice) | *Is this **request** permitted by deployment policy at all?* | identity-independent, provider-independent request admissibility |

The first policy - a maximum request size - sits unambiguously in the third bucket: it is not about
who is asking and not about which provider would serve it. Overlap is prevented structurally, not
by intent: the policy engine cannot import `adapters.authorization` (so it cannot resolve
permissions), cannot import `application.routing` or `application.agents` (so it cannot route or
reach `AgentRuntime`), and the stage cannot import a concrete engine (so policy source stays
swappable). Every one of those was proven by deliberate violation.

### Finding: the first policy had to be chosen from data that actually exists

Model-capability restrictions, environment restrictions and data-classification rules were all
considered and rejected: no org policy store, no model capability catalog and no data
classification exist anywhere in this repository, and inventing one to justify the Policy Engine
would have been the exact speculative-infrastructure failure GP-1 forbids.

Maximum request size survives because every input it needs already flows: the payload is in
`StageContext.attributes["request"]`, and Slice 9's estimator already derives budget reservations
from payload length - which means an unbounded payload is simultaneously a cost problem and an
abuse vector. Rejecting it in `before_request` costs nothing, since it happens before both the
budget reservation and the provider call.

An unmeasurable payload (one that cannot be canonically JSON-encoded) is **denied**, not waved
through: a limit that cannot be measured has not been satisfied, and the alternative would let an
oversized payload bypass the control by being malformed enough to defeat the check.

### Finding: outage must block *and* stay distinguishable from denial

`PolicyEffect` has exactly two members, ALLOW and DENY. There is deliberately no `UNAVAILABLE`
effect: an engine that could not decide has not produced an effect, and modelling "no answer" as a
kind of answer is precisely what lets an outage quietly become a verdict. Unavailability is an
exception (`PolicyEngineUnavailableError`), matching `LedgerUnavailableError` and
`BudgetUnavailableError`.

The stage fails closed three ways - outage, engine defect (any escaped exception), and a verdict
that is not a `PolicyVerdict` (a remote engine can deserialize into something unexpected, and
"unexpected" must not resolve to "allowed") - plus a fourth for a missing tenant, since
organization policy cannot be applied without an organization.

Both denial and outage block, and the **caller cannot tell them apart** (identical generic reason);
the **audit annotations can** (`policy_denied` + rule + measurements vs. `policy_unavailable`).
`test_an_outage_is_distinguishable_from_a_denial_in_the_audit_trail` pins both halves. Without the
split, a policy outage and a spike in legitimate denials would look identical on exactly the
dashboard an operator would use to tell them apart.

Caller reason never names the rule or the threshold, mirroring `AuthorizationStage`'s refusal to
name the missing permission: telling a caller precisely which control stopped them and where its
limit sits is a reconnaissance aid.

### OPA decision: DEFERRED

There is no OPA server, no Rego bundle, no bundle-distribution mechanism, no deployment
configuration for one, and no consumer that needs policy authored outside this process. An OPA
adapter built now would be a fake integration - an interface shaped like a remote engine with
nothing behind it - and its parity tests would compare a stub against itself.

This is the same evidence-first posture ADR-0017 took toward Redis Lua and ADR-0018 toward the
pgvector semantic tier, applied a third time. It is a decision, not an omission: when a real
policy-distribution consumer exists, it implements `PolicyEnginePort` beside `LocalPolicyEngine`
and **the stage does not change** - that substitutability is the entire reason the port exists, and
is what makes deferring OPA safe rather than merely convenient. **No ADR was written**, because
nothing here contradicts an existing Accepted decision; ADR-0016 already names OPA as the eventual
mechanism and this slice does not reverse that.

### The guard evaluation

| Candidate | Verdict | Why |
|---|---|---|
| Policy consumers depend on the port only | **NEW** | Exactly Guard G's shape for RBAC. A stage importing a concrete engine binds enforcement to one policy source - which would also make deferring OPA meaningless, since substituting it is the port's whole purpose |
| Policy engines decide policy only (8 targets) | **NEW** | Nothing previously restricted `gateway.adapters.policy`. Each forbidden target is one claim: no routing, no `AgentRuntime`, no provider invocation, no cost authorship, no budget, no retry, no permission resolution, no dependency on Slice 12 |
| Policy stage cannot import authorization resolvers | **REUSED, unchanged** | Guard G (Slice 5) already forbids `adapters.pipeline` -> `adapters.authorization`, and was proven to catch a violation planted in `policy_stage.py`. Adding a policy-specific duplicate would have inflated the count without enforcing anything new |
| Policy cannot construct `RoutingDecision` / reach `AgentRuntime` | **REUSED, unchanged** | Both whole-repo AST scans; proven against `policy_stage.py` and `local_policy_engine.py` respectively |
| Policy adapter implementations mutually independent | **NOT APPLICABLE** | Exactly one implementation exists. An independence contract needs two modules to be independent *of*; writing one now would name a module that does not exist |
| Policy construction confined to composition root | **REDUNDANT** | `check_resolver_construction.py` and the blanket adapter contracts already confine adapter construction, and `LocalPolicyEngine` holds no shared state or deployment-wide authority the way `RequestDeduplicator`/`RetryPolicy` do |

### Enforcement (each violated, mutation verified present, observed failing, restored, observed passing)

| Guard | Violation planted | Observed |
|---|---|---|
| Policy consumers depend on the port only (new) | `policy_stage.py` imports `adapters.policy.local_policy_engine` | 30 kept / 1 broken |
| Policy engines decide policy only (new) | `local_policy_engine.py` imports `application.routing.engine` | 30/1 |
| ...same | ...`application.agents.runtime` | 30/1 |
| ...same | ...`application.providers.provider_executor` | 30/1 |
| ...same | ...`application.accounting.cost_accountant` | 30/1 |
| ...same | ...`application.ports.ledger` | 30/1 |
| ...same | ...`application.reflection.retry_policy` | 30/1 |
| ...same | ...`application.evaluation.runner` | 30/1 |
| ...same | ...`adapters.authorization.null_resolver` | 30/1 |
| Guard G / RBAC consumers (reused) | `policy_stage.py` imports `adapters.authorization.null_resolver` | 30 kept / 1 broken |
| `RoutingDecision` construction (reused) | `policy_stage.py` constructs `RoutingDecision(...)` | exit 1 |
| Guard L / `AgentRuntime` (reused) | `local_policy_engine.py` references `AgentRuntime` | exit 1 |

### Design decisions recorded as decisions, not defaults

- **`PolicyVerdict`, not `PolicyDecision`.** `PolicyDecision` already exists in
  `domain/routing/models.py` as PolicyAgent's routing contribution. Reusing or shadowing that name
  would have made two different concepts look like one in every stack trace and import list.
- **`PolicyEffect` has no `UNAVAILABLE` member** - see the fail-closed finding.
- **A `DENY` verdict must carry a caller reason**, validated at construction, mirroring
  `StageResult` requiring a reason for `BLOCK`.
- **A missing payload key is evaluated as empty, not skipped.** Policy is not bypassed by omitting
  an attribute - `test_a_missing_payload_is_evaluated_as_empty_not_skipped` pins this.
- **The engine lives in `adapters/policy/`, not `application/`.** It is a named implementation of a
  port with a future remote sibling, matching `InMemoryBudgetLedger`/`InMemoryResponseCache`
  placement rather than the pure-logic `application/` placement used for evaluators.

### Known limitations, stated rather than concealed

- **One policy, one engine.** No rule composition, no policy DSL, no admin API, no policy database
  - all explicitly out of scope, and none has a consumer.
- **Not wired into a request path.** `PolicyStage` is composed in the container and proven by
  tests; no pipeline runner exists to execute stages around an inference, so - like
  `AuthorizationStage` before it - it is enforced-by-construction but not yet enforced-in-traffic.
  This is the single largest piece of outstanding debt across Slices 5-13.
- **No policy caching**, deliberately: no performance requirement exists, and caching a policy
  decision introduces invalidation semantics that are not free.
- **Policy does not consult evaluation results.** No first consumer needs it, and coupling the two
  would collapse capabilities that were deliberately kept independent.

### Decision

**No action against ADR-0016** (frozen, byte-unchanged). **No new ADR for either slice** - neither
contradicts an existing Accepted decision, and ADR-0016 already anticipates both capabilities.
Writing ADRs here would be ceremony rather than governance, in contrast to Slices 9 and 10 where a
genuine conflict with ADR-0004/ADR-0006 existed.

### Lessons

- **A Tier-2 prediction can be confirmed by two different mechanisms, and saying which one applies
  matters.** Policy consumed `PipelineStage` exactly as ADR-0016 imagined; evaluation confirmed the
  same Tier-2 claim while deliberately *not* becoming a stage, because it is post-hoc rather than
  interceptive and the stage route would have been less type-safe. Recording the difference keeps
  the ADR's claim testable instead of turning "Tier 2" into a synonym for "a stage".
- **Choosing the first capability instance from existing data is what keeps a foundation honest.**
  Both slices had to reject the more impressive option - LLM-as-judge, OPA, data classification -
  because none had data or a consumer. What remained was smaller and genuinely useful.
- **A restore step is part of a guard proof, and untracked files break the usual one.**
  `git checkout --` silently cannot restore a file git does not track, which let one mutation
  survive into the next proof. Verifying the mutation *and* verifying the restore is the complete
  discipline; only verifying the mutation is not.

## Evidence Record - Phase 4 Slice 14: Request Admission Pipeline

**Milestone type: Foundation** - and the one place in Phase 4 where "a Foundation milestone with no
ADR is suspect" does not apply. Rule 2 requires ADR -> protocol -> CI enforcement before
implementation. ADR-0016 is the ADR, `PipelineStage` has been the protocol since Slice 1, and this
slice supplies the third artifact that invariant 5's own enforcement column always demanded and
never had: **"stage registration + ordering"**. No new seam is born here, so no new ADR is written;
what changes is that the existing seam finally executes.

### The roadmap discrepancy, recorded rather than worked around

The brief named `Phase4_Master_Execution_Plan.md` and `AIOS_Architecture.md`. **Neither exists in
this repository.** ADR-0016 line 242 says it "establishes the framing for the Phase-4 Master
Execution Plan" - a document that was never committed. The authoritative roadmap is therefore
ADR-0016's Tier-1 table plus its Tier-2 list, reconciled against this log. Read that way, the next
slice was not a matter of interpretation:

| Source | What it says |
|---|---|
| ADR-0016 invariant 5 | CI enforcement = "stage **registration + ordering** + protocol tests" - never built |
| This log, Slice 13 | "the single largest piece of outstanding debt across Slices 5-13" is that no runner exists |
| `noop_stage.py` docstring (Slice 1) | exists "to give ordering/registration tests something concrete" - a consumer anticipated for 13 slices |
| `ports/evaluation.py` (Slice 12) | declined to become a stage partly because "no pipeline runner exists yet" |
| Container, before this slice | `AuthorizationStage` **was not constructed anywhere at all** |

### Rule 5 determination

| Question | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** - zero diff on `domain/`, `ports/pipeline.py`, `ports/tools.py`, `ports/mcp.py`, `ports/agents.py`, `agents/`, ADR-0016 |
| Rule 5 against any capability-owned port | **NOT TRIGGERED** - the runner consumes `PipelineStage`, `StageContext`, `StageResult` and `StageAction` exactly as they already exist and adds no field to any of them |
| Migration / persistence | **None** - admission decides; it stores nothing. Alembic head unchanged |

### Finding: `StageResult` documents an invariant it does not enforce

`StageResult`'s docstring states that `BLOCK` "must carry a `reason`", because "a stage that blocks
without saying why produces an unexplainable denial". The dataclass has **no `__post_init__` and
never checked it**. For thirteen slices nothing executed a stage, so nothing could observe the gap.

**Rule 5 was applied and came back NOT TRIGGERED, deliberately.** Rule 5's third question - why the
change does not belong in the consumer instead - answers itself here: `RequestPipeline` is the only
component that will ever read a `StageResult`, so compensating in the runner closes the gap
completely, whereas adding validation to a frozen Tier-1 type would invalidate previously legal
constructions across three slices of existing stages and buy no additional guarantee. An unexplained
block stays a block: the generic reason is substituted and `unexplained_block` recorded for audit.
It is never upgraded to admission.

### Finding: ordering was derived from side effects, not from intuition

The obvious ordering (authorization -> policy -> routing) turns out to be right for a reason that is
checkable rather than aesthetic. Routing is the **only** admission stage with a real downstream
effect: `AgentRoutingStage` invokes the routing engine, which runs the entire five-agent chain.
Authorization and policy are pure decisions. Routing therefore runs last not because it is "least
important" but because it is the one stage a denial must be able to prevent - and
`test_an_authorization_denial_means_no_policy_evaluation_and_no_routing` asserts exactly that
against a spy wrapping the *real* engine.

The rejected alternative is recorded too: policy before authorization. It is cheaper (pure local
computation vs. a resolver call), but it would evaluate a deployment's request limits for a caller
who may not act at all, and a policy denial discloses that a threshold exists. Identity first.

### Finding: stages must not communicate through the context

Each stage receives its own copy of `StageContext.attributes`. Stricter than today's three stages
need - none reads another's output - and chosen for a concrete reason: `attributes` is opaque by
contract *and caller-supplied*, so a shared mutable bag would let a stage, or a caller crafting an
attribute shaped like a stage's annotation, influence a control that runs after it. Annotations come
back in the per-stage audit record, where they cannot be mistaken for request input.

### The guard evaluation

| Candidate | Classification | Reasoning |
|---|---|---|
| `RequestPipeline` construction confined to the composition root | **NEW** (`check_pipeline_construction.py`) | A new file, applying `check_execution_construction.py`'s own stated test: extend for more classes inside a boundary it already fences, new file for a new boundary. Admission is not execution - different package, different question, and it runs before the execution guard's subjects exist. It is also the **strongest** version of the invariant in the codebase: every earlier construction guard confines a component that chooses *how* something is done; this one confines the component that chooses **which controls run at all** |
| The request pipeline reaches no capability (import-linter, 10 forbidden targets) | **NEW** | Makes "the runner executes and decides nothing" structural. Deliberately **not** `allow_indirect_imports` - unlike the Slice 11/12 contracts this package has no sanctioned collaborator to reach through, so any path at all is a violation |
| Permission-resolver construction (Guard I, Slice 5) | **REUSED - and exercised for the first time** | Guard I was never *vacuous* (it could always fail), but it was **unexercised**: no resolver was constructed anywhere in `src/gateway`, so it guarded code that did not exist. Wiring `NullPermissionResolver` gives it a real subject. Re-proven here |
| `RoutingDecision` construction / Guard L | **REUSED, unchanged** | Whole-repo AST scans; proven against the new `application/pipeline/runner.py` |
| The stages themselves confined to the composition root | **NOT APPLICABLE** | A stage holds no authority over whether it is consulted - only membership in the pipeline makes a control run, and the pipeline is confined. Guarding them would inflate the count without enforcing anything new |
| `application.pipeline` must not import `adapters` | **REDUNDANT** | Already covered by "application is framework-free and inward-only". Not added, not counted |

### Enforcement (each violated, mutation verified present, observed failing, restored, restore verified, observed passing)

**15/15 proven.** Restores were verified by content comparison rather than `git checkout --`, because
`runner.py` is untracked and git cannot restore it - the Slice-12 lesson, applied.

| Guard | Violation planted | Observed |
|---|---|---|
| Pipeline construction (new) | `RequestPipeline([])` in `routing/engine.py` | exit 1 |
| ...same | ...in `config/settings.py` | exit 1 |
| Runner reaches no capability (new) | one direct import per forbidden target, 10 proven separately | 31 kept / 1 broken, each |
| Guard I (reused) | `NullPermissionResolver()` in `routing/engine.py` | exit 1 |
| `RoutingDecision` (reused) | `RoutingDecision(...)` in `pipeline/runner.py` | exit 1 |
| Guard L (reused) | `AgentRuntime` referenced in `pipeline/runner.py` | exit 1 |

Both planting sites for the construction guard are outside its `ALLOWED` **and** `IMPLEMENTATIONS`
lists - the Slice-11 false-positive trap, avoided by construction.

### Known limitations, stated rather than concealed

- **`after_response` and `on_error` are still not executed by anything.** Deliberate: this slice has
  no response and no error to hand a stage, and building both halves with no consumer would be the
  speculative shape GP-1 forbids. Slice 15 is their first real consumer.
- **The default composed pipeline denies every request** (`NullPermissionResolver` grants nothing; no
  endpoint declares a requirement). That is the fail-closed direction and the same "nothing
  configured yet" posture as the empty provider catalog and price table - and it is asserted, not
  assumed, by `test_the_default_deployment_admits_nothing`.
- **No HTTP endpoint.** Admission runs around an application-layer call, not around a route. The
  delivery surface remains outstanding debt.

### Decision

**No action against ADR-0016** (frozen, byte-unchanged). **No new ADR** - see the milestone-type
note above. Validation at Slice-14 completion: **583 passed, 0 skipped, 97% coverage, mypy strict
clean (227 files), import-linter 32 kept / 0 broken**, `runner.py` at 100% line coverage.

## Evidence Record - Phase 4 Slice 15: Served Inference Path

**Milestone type: Capability.** It consumes seams that already exist and introduces no extension
point: `PipelineStage` (Tier 1, untouched), `RequestPipeline` (Slice 14), `ReflectiveExecutor`
(Slice 11), `EvaluationRunner` (Slice 12). No new ADR.

### Rule 5 determination

| Question | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** - zero diff on `domain/`, `ports/pipeline.py`, `ports/tools.py`, `ports/mcp.py`, `ports/agents.py`, `agents/`, ADR-0016. `StageResult.annotations` stays `dict[str, Any]`; no protocol method, field or signature changed |
| Rule 5 against a capability-owned port | **TRIGGERED, and satisfied** - `ROUTING_EXECUTION_KEY` added to `application/ports/routing.py`. Recorded below |
| Migration / persistence | **None.** Alembic head unchanged at `0006_budget_ledger` |

#### Rule 5 event: `ROUTING_EXECUTION_KEY` declared in `ports/routing.py`

1. **Active consumer:** `application/serving/inference_service.py`, new in this slice - the first
   component that reads a routing result back out of an admitted request in order to execute it.
2. **Why the current arrangement was insufficient:** the key was a private constant inside
   `adapters/pipeline/routing_stage.py`. An application-layer consumer cannot import it (Clean
   Architecture forbids application -> adapters, CI-enforced), so the only alternative was to
   re-declare the literal at the consumer - two spellings of one contract, drifting silently the
   first time either changed. Exactly the failure Rule 3 exists to prevent.
3. **Why it does not belong in the consumer instead:** producer and consumer must agree, and the
   agreement belongs beside the type being transported. Mirrors `REQUEST_PAYLOAD_KEY` in
   `ports/policy.py` (Slice 13) and `REQUIRED_PERMISSIONS_KEY` in
   `application/authorization/requirements.py` (Slice 5).

Capability-owned port, so this is a Rule 5 event recorded here rather than a new ADR - the same
shape as `ProviderUsage` (Slice 8) and `ProviderErrorCategory` (Slice 11).

### Finding: the first end-to-end integration exposed a real defect in Slice 6's transport

`AgentRoutingStage` published `execution.decision` and dropped `execution.provider`. That reads as
correct - the decision is the sole explanation, and the stage's contract is to transport an
explanation rather than adjudicate. But `RoutingExecution.routed` means "SELECTED **and** a provider
was resolved", so the transported half could report that a provider had been chosen while carrying
nothing capable of calling it. **A lossy transport, invisible for nine slices because nothing ever
executed the pipeline.**

Fixed at the smallest correct boundary: the stage transports the whole `RoutingExecution`. Still one
annotation, still one source of truth, and `decision` remains reachable as `execution.decision`. The
rejected alternative - a second key beside the first - would have put two views of one result into
the attributes bag, which is the shape the stage's own docstring warns against. Pinned by
`test_the_transported_selection_carries_the_provider_it_resolved_to`.

This is a **prediction that fired**: ADR-0016 Rule 4 says a seam is unproven until one real
implementation exists behind it. The corollary this slice supplies is that a *transport* is unproven
until something on the far side consumes what it carries.

### Finding: a guard extension silently weakened the guard it extended

Adding `InferenceService` to `check_pipeline_construction.py` also added
`serving/inference_service.py` to its `IMPLEMENTATIONS` exemption list - and that list is
**per-file, not per-target**. The service file thereby gained permission to construct a
`RequestPipeline` too: it could have assembled its own admission chain with the guard still printing
PASS.

**Caught by re-proving the Slice-14 target after the Slice-15 extension** - the proof came back
`exit 0` where it had to be `exit 1`. Nothing else would have noticed; both the guard and the whole
suite were green. Fixed by making the exemption per-class: a defining module is exempt for its own
class only.

The same flat-list weakness exists in the four earlier construction guards
(`check_execution_construction.py`, `check_accounting_construction.py`,
`check_provider_construction.py`, `check_resolver_construction.py`). Each is effectively
single-purpose per file today, so none is currently exposed; recorded here as deferred debt rather
than fixed in this slice, because rewriting four guards is not what this slice's evidence supports.

**This is the second time this project has produced a guard that passed while unable to fail, and
the second time only a deliberate-failure proof found it.** The rule that caught it is the one worth
restating: extending a guard obliges you to re-prove what it already caught, not merely to prove the
new thing.

### Finding: a refusal must not be dressed as a provider failure

`ServedInference` returns `reflection=None` and `evaluation=None` for a refused request rather than
synthesizing `ProviderResponse(ok=False, ...)`. Synthesizing one would make an admission decision
indistinguishable from a provider outage to every downstream reader, and would feed the evaluators a
call that never happened - inviting precisely the double-counting `UsageAccountingConsistencyEvaluator`
was built to catch. "Denied at admission", "routed nowhere", "denied by budget" and "the provider
failed" stay four distinguishable facts.

For the same reason a refusal is **not evaluated at all**: evaluation observes completed inferences,
and a request that never entered the system produced none. Emitting `NOT_APPLICABLE` verdicts for
rejected traffic would make every quality metric a function of how much traffic was rejected.

### Ordering, derived from existing semantics

    admit (authorization -> policy -> routing)   Slice 14
      -> reflect (bounded retry)                 Slice 11
        -> coordinate (cache -> reserve -> execute -> settle/release)   Slices 9, 10
      -> evaluate the final result, once         Slice 12

Two points were derived rather than assumed. **Cache before budget** is Slice 10's existing
semantics, unchanged: a hit spends nothing, so there is nothing to gate. **Evaluation after the
retry loop, not per attempt**, because reflection may make several attempts under attempt-scoped
identities; evaluating each would count one logical request several times and would report a
transient failure a retry already recovered from as a quality problem
(`test_a_transient_failure_a_retry_recovered_is_not_reported_as_a_quality_problem`).

### The guard evaluation

| Candidate | Classification | Reasoning |
|---|---|---|
| `InferenceService` construction confined to the composition root | **REUSED-EXTENDED** (`check_pipeline_construction.py`) | The service chooses *which pipeline guards a request*, plus which executor and evaluator chain follow it - the identical authority one step further out. A second script would have duplicated this one's logic under another name. The extension exposed and fixed the per-file exemption defect above |
| The served path composes capabilities and owns none (import-linter, 7 forbidden targets) | **NEW** | One forbidden target per ownership claim. `allow_indirect_imports` **is** set here, unlike Slice 14's runner contract: serving -> reflection -> execution -> accounting/providers is the intended path, so only a direct reach-around is a violation - the Slice 11/12 shape, for the Slice 11/12 reason |
| `RoutingDecision` construction / Guard L | **REUSED, unchanged** | Proven against `serving/inference_service.py` |
| A guard that "evaluation runs exactly once" | **NOT APPLICABLE** (static analysis cannot express it) | A call-count invariant is a runtime property. Enforced by test (`test_evaluation_runs_exactly_once_on_the_final_result`, `test_retries_go_through_the_coordinator_and_are_evaluated_only_once_at_the_end`) and recorded as such rather than dressed up as a guard |
| A contract forbidding `serving` -> `adapters` | **REDUNDANT** | Covered by "application is framework-free and inward-only". Not added, not counted |

### Enforcement (each violated, mutation verified present, observed failing, restored, restore verified, observed passing)

**13/13 proven**, plus all **15/15** Slice-14 proofs re-run and still green after the guard change.

| Guard | Violation planted | Observed |
|---|---|---|
| Pipeline construction, extended | `InferenceService(...)` in `routing/engine.py` | exit 1 |
| ...same | ...in `config/settings.py` | exit 1 |
| ...**regression check** | `RequestPipeline([])` in `serving/inference_service.py` | exit 1 (was **exit 0** before the fix - see the finding above) |
| Served path owns nothing (new) | one direct import per forbidden target, 7 proven separately | 32 kept / 1 broken, each |
| `RoutingDecision` (reused) | `RoutingDecision(...)` in `serving/inference_service.py` | exit 1 |
| Guard L (reused) | `AgentRuntime` referenced in `serving/inference_service.py` | exit 1 |
| Slice-14 contract still live | `import ...routing.engine` in `pipeline/runner.py` | 32 kept / 1 broken |

### Negative evidence produced by this slice

Every one of these was previously unassertable, because nothing composed admission with execution.

| Property | Test |
|---|---|
| authorization denial -> no policy call, no routing, no reservation, no provider call, no evaluation | `test_an_authorization_denial_reaches_nothing_downstream` |
| policy denial -> same | `test_a_policy_denial_reaches_nothing_downstream` |
| budget rejection -> provider never called, nothing settled | `test_a_budget_denial_means_the_provider_is_never_called` |
| provider failure -> reservation released, nothing settled | `test_a_provider_failure_releases_the_reservation_and_settles_nothing` |
| cache hit -> no provider call, no second reservation or settlement, `usage is None` | `test_a_cache_hit_calls_no_provider_and_accounts_no_second_time` |
| retries stay inside the coordinator, each attempt independently reserved/settled/released | `test_retries_go_through_the_coordinator_and_are_evaluated_only_once_at_the_end` |
| evaluation runs exactly once, on the final result | `test_evaluation_runs_exactly_once_on_the_final_result` |
| admitted but unroutable -> no provider call, no budget movement, still evaluated | `test_an_admitted_but_unroutable_request_calls_no_provider_and_is_still_evaluated` |
| the service reads routing from the pipeline rather than routing again | `test_the_service_reads_routing_from_the_pipeline_rather_than_routing_again` |

Spies **wrap the real collaborators** rather than replacing them: "the provider was not called" and
"budget was not touched" are only evidence if the things that did not happen are the components that
would really have done them.

### Known limitations, stated rather than concealed

- **Still no HTTP endpoint.** `InferenceService` is called by tests and the container, not by a
  route. Admission now genuinely gates the inference path, but "real inference traffic" in the sense
  of an inbound request over the network does not exist yet. This is the largest remaining piece of
  the original debt and it is deliberately not closed here: an endpoint pulls in request/response
  schemas, the API error model and streaming, none of which this slice's evidence speaks to.
- **The default deployment still denies everything** - inherited from Slice 14, unchanged.
- **`PipelineStage.after_response` and `on_error` remain unexecuted.** Slice 15 turned out **not** to
  be their first consumer after all: the service composes admission around an application call whose
  response is a typed `ReflectionResult`, and pushing that through the opaque `attributes` bag to
  reach `after_response` is the same Rule 3 violation Slice 12 rejected. They stay unexecuted, and
  saying so is more useful than manufacturing a consumer for them.
- **`RoutingTransportError` is a defect path, not a request outcome.** Reachable only by composing a
  pipeline with no routing stage - a real misconfiguration, tested through the public `serve()` call
  rather than by reaching into the private helper.

### Decision

**No action against ADR-0016** (frozen, byte-unchanged). **No new ADR** - the Rule 5 event is on a
capability-owned port, and nothing here contradicts an Accepted decision. Validation at Slice-15
completion: **606 passed, 0 skipped, 97% coverage, mypy strict clean (230 files), import-linter 33
kept / 0 broken**; `serving/inference_service.py` and `pipeline/runner.py` both at 100% line
coverage.

### Lessons

- **A transport is unproven until something consumes what it carries.** Rule 4 says a seam needs one
  real implementation; nine slices of green validation hid a routing annotation that dropped half its
  payload, because "one real implementation" existed on the producing side only.
- **Extending a guard obliges you to re-prove what it already caught.** The per-file exemption defect
  was introduced and detected inside one slice, and only because the extension's proof included a
  regression check rather than only the new target.
- **The debt was not "a missing runner" but "a missing consumer".** Every capability from Slice 5
  onward was correct in isolation and unreachable in composition. Two slices of pure wiring - no new
  capability, no new ADR, no migration - converted thirteen slices of construction-time correctness
  into enforcement.

## Evidence Record - Phase 4 Slice 16: Production Observability

**Milestone type: Capability — reclassified from the planning checkpoint, and the reclassification
is the first finding.** The checkpoint proposed "Foundation, likely ADR-0019". That was wrong.
ADR-0016 defines Foundation as *"creates an extension point"*, and this slice creates none: no new
port, no substitutable implementation, no new seam. Rule 1's objective admission test also fails —
observability's absence would **not** have forced any public interface to change when it was added
later, which is precisely what adding it now with **zero interface changes** demonstrates.

The checkpoint had inferred "Foundation" from *cross-cutting and important* rather than from the
ADR's actual definition. Correcting it dissolves the ADR question rather than answering it: a
Capability milestone needs no ADR, and "a Foundation milestone with no ADR is suspect" never
applies.

### No new ADR, and why that is a finding rather than an omission

Everything a telemetry ADR would have decided **already existed and was already Accepted**:

| Decision an ADR would record | Where it already lives |
|---|---|
| Mechanism (module-level singletons, default registry) | `observability/metrics.py` docstring, auth milestone |
| Exposition surface | `/metrics` route in `delivery/http/ops/router.py` |
| Layer boundary | import-linter: "observability is cross-cutting and must not depend on delivery/config" |
| Cardinality/sensitivity policy | `metrics.py`: *"label values must be low-cardinality and never sensitive… never from exception text, user input, tokens, or secrets (NFR-SEC03)"* |

This slice extends an established mechanism to new call sites and converts that **written** policy
into **enforced** policy. Writing an ADR to re-decide settled questions would have been ceremony —
the same judgement Slices 12 and 13 recorded when they declined to write one.

### Rule 5 determination

| Question | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** — zero diff on `domain/`, `ports/pipeline.py`, `ports/tools.py`, `ports/mcp.py`, `ports/agents.py`, `agents/`, ADR-0016 |
| Rule 5 against a capability-owned port | **NOT TRIGGERED** — no protocol gained a field. Every fact was already published: `AdmissionOutcome.records[].action`, `RoutingDecision.outcome`, `ExecutionOutcome`, `ProviderResponse.ok/.error_category`, `AttemptRecord.verdict`, `EvaluationResult.outcome`, `ReservationResult.outcome` |
| Latency | Measured with `time.monotonic()` **in the owning caller**. The tempting alternative — a `duration` field on `ProviderResponse` — was rejected: it would be a Rule 5 change to a capability-owned port to serve instrumentation, and the caller already knows when it started and stopped |
| Migration / persistence | **None.** Alembic head unchanged |

### Finding: instrumenting the coordinator exposed a real pre-existing defect

Adding `observability.metrics` to `InferenceCoordinator` **broke the "ports declare contracts only
(no transport or framework)" contract**, via a path nobody had noticed:

    ports.evaluation -> execution.inference_coordinator -> observability.metrics -> prometheus_client

The root cause is not the instrumentation. `ExecutionOutcome` was defined **inside a concrete
orchestrator**, so three modules — including a **port** — imported an orchestrator merely to name a
vocabulary. A port depending on a concrete application service inverts the direction the ports layer
exists to establish, and it was the **only** outcome enum placed that way:

| Enum | Home |
|---|---|
| `ReservationOutcome` | `ports/ledger.py` |
| `ProviderErrorCategory` | `ports/providers.py` |
| `EvaluationOutcome` | `ports/evaluation.py` |
| `StageAction` | `ports/pipeline.py` |
| `RoutingOutcome` | `domain/routing/models.py` |
| **`ExecutionOutcome`** | **`execution/inference_coordinator.py`** ← the anomaly |

**The contract was right and the placement was wrong**, so the placement changed:
`ExecutionOutcome` moved to a new `application/ports/execution.py`. The alternative — an
`ignore_imports` entry — would have weakened a contract to accommodate a misplaced type, which is
exactly the erosion this project's evidence log repeatedly records as the failure mode.

**This is a relocation, not a protocol change**: no member added, removed or renamed, no semantics
altered. Rule 5 stays NOT TRIGGERED; it is prior-slice debt that this slice's first real integration
exposed, fixed at the smallest correct boundary (10 importers repointed, nothing else touched).

*A latent architectural inversion survived six slices because nothing had yet forced the two sides
of it into the same import graph.*

### Metric vocabulary (11 families, chosen to answer operational questions)

| Metric | Owner | Answers |
|---|---|---|
| `gateway_admission_stage_decisions_total{stage,action}` | `RequestPipeline` | which control refuses, how often |
| `gateway_served_requests_total{outcome}` | `InferenceService` | terminal outcome incl. never-admitted |
| `gateway_served_request_duration_seconds{outcome}` | `InferenceService` | end-to-end latency |
| `gateway_inference_attempts_total{outcome}` | `InferenceCoordinator` | per-attempt outcomes |
| `gateway_cache_lookups_total{result}` | `InferenceCoordinator` | cache hit rate |
| `gateway_provider_calls_total{provider,outcome}` | `ProviderExecutor` | which provider fails, and why |
| `gateway_provider_call_duration_seconds{provider}` | `ProviderExecutor` | which provider is slow |
| `gateway_reflection_attempts_total{verdict}` | `ReflectiveExecutor` | retry rate |
| `gateway_routing_decisions_total{outcome}` | `AgentOrchestratedRoutingEngine` | routing refusals |
| `gateway_evaluations_total{evaluator,outcome}` | `EvaluationRunner` | quality vs. broken evaluator |
| `gateway_budget_reservations_total{outcome}` | `ReservationService` | denials vs. ledger outage |

Deliberately **not** created: a metric per internal event. Settlement, release and dedup emit
nothing of their own — each is already derivable from an existing series, and a metric nobody
queries is cardinality without insight.

### Finding: cardinality bounded at runtime, not merely by convention

Recording goes through `record_*` functions rather than `.labels()` at call sites. Each owns three
properties the call sites must not re-implement:

1. **Runtime bounding** — a value outside its allowlist becomes `"unknown"` rather than minting a
   new series. This is the property that actually holds under a defect, and it is what a static
   guard cannot give.
2. **Failure isolation** — recording is wrapped so a broken collector cannot change a request's
   outcome. Proven twice: a unit test on the recorder, and an end-to-end test asserting an
   identical served result with a deliberately exploding metric.
3. **Dependency direction** — recorders take `str`, so `observability` imports no application code
   and stays a leaf.

`unclassified` and `unknown` are deliberately distinct: the first is a real state
(`error_category is None`), the second means a value fell outside the vocabulary. Collapsing them
would hide a genuine classification gap behind a bug indicator.

### The guard evaluation

| Candidate | Classification | Reasoning |
|---|---|---|
| Metric label cardinality/sensitivity (`check_metric_cardinality.py`) | **NEW** | Three checks: declared label names ⊆ allowlist and free of forbidden substrings; no direct `.labels()` on a request-path metric outside `metrics.py`; no forbidden identifier flows into a `record_*` call |
| Instrumented components stay within their contracts | **REUSED** | The existing import-linter suite did the real work — it *caught the ports violation*. No new contract was needed |
| A "metrics port" seam | **NOT APPLICABLE** | Prometheus is the established mechanism; a port would be the speculative abstraction 16.3 warns against |
| Forbidding `application → adapters` from new code | **REDUNDANT** | Already covered by "application is framework-free and inward-only" |

**Guard scope was bound to named metrics, not to files.** The first draft banned `.labels()`
everywhere and immediately fired on three pre-existing auth-era call sites. Two options were
rejected: rewriting approved prior-slice code to satisfy a newer convention (churn, not
enforcement), and a per-file exemption list — the exact hazard Slice 15 recorded, where exempting a
file exempts it from *everything*. Naming the protected objects keeps the exemption at the
granularity of the thing being protected.

### Enforcement (violated, mutation verified present, observed failing, restored to exact bytes, restore verified, observed passing)

**5/5 proven**, covering all three checks:

| Check | Violation planted | Observed |
|---|---|---|
| 1 | `labelnames=("organization_id",)` on a new metric | exit 1 |
| 1 | undeclared label name `"shard"` | exit 1 |
| 2 | `served_requests.labels(...)` inside `pipeline/runner.py` | exit 1 |
| 3 | `organization_id` passed into `record_served_request` | exit 1 |
| 3 | raw `response.error` passed into `record_provider_call` | exit 1 |

**A defect in the proof harness was found and fixed before any result was accepted.** Proof 5
initially reported `restored=False`: the marker used to confirm restoration (`record_provider_call(`)
legitimately exists in the original file, so "marker absent" could never hold for a *replacement*
mutation. Byte-comparison — the authoritative check — had passed. The harness now applies the
marker check only when the marker was absent from the original. *Verifying a restore is as
falsifiable as verifying a mutation, and a verification that cannot pass is as useless as a guard
that cannot fail.*

### Honest limits of the enforcement (stated, not implied)

- **Check 3 is name-based and therefore partially heuristic.** It catches an identifier passed by
  its own name; it cannot see through an alias (`x = organization_id; record_...(provider=x)`) or a
  computed string. The runtime allowlist is what holds in those cases.
- **Three labels are configuration-bounded, not enum-bounded**: `stage` (composition root's fixed
  chain), `evaluator` (wired chain), `provider` (deployment catalog). None is request-supplied —
  pinned by `test_a_provider_label_cannot_be_influenced_by_the_request_payload`, which sends an
  attacker-chosen `provider` in the payload and asserts no such series appears — but their bound is
  deployment configuration, not a Python enum. Recorded rather than claimed as closed.
- **`model` is deliberately not a label.** No controlled vocabulary exists for it and cardinality
  could not be proven, so the operational value did not justify the risk.

### Tests

`test_observability_metrics.py` (29) + `test_app.py` (+1). Prometheus isolation uses **deltas** read
through the public `REGISTRY.get_sample_value` accessor rather than registry resets: deltas are
order-independent and immune to cross-test leakage, which resetting global state is not.

### Known limitations

- **No tracing.** Deliberately out of scope: distributed tracing is a genuinely new seam (a
  propagation format, a span boundary, an exporter) and would have made this a Foundation milestone
  requiring an ADR. Metrics needed none of that.
- **No dashboards, alert rules or SLOs.** Those consume metrics; they are not metrics.
- **Business outcomes unchanged.** This slice records facts and decides nothing — no routing,
  authorization, policy, execution, accounting, reflection or evaluation behaviour differs. The 606
  pre-existing tests pass unmodified, which is the evidence for that claim.

### Decision

**No action against ADR-0016** (frozen, byte-unchanged). **No new ADR** — see above. Validation at
Slice-16 completion: **636 passed, 0 skipped, 97% coverage, mypy strict clean (232 files),
import-linter 33 kept / 0 broken**; `metrics.py`, `ports/execution.py` and every instrumented module
at 100% line coverage.

## Evidence Record - Phase 4 Slice 17: HTTP Inference Endpoint + Authentication Wiring

**Milestone type: Capability.** It consumes existing seams and creates no extension point. No ADR.

### Rule 5 determination

| Question | Result |
|---|---|
| Rule 5 against Tier 1 | **NOT TRIGGERED** — zero diff on `domain/`, `ports/pipeline.py`, `ports/tools.py`, `ports/mcp.py`, `ports/agents.py`, `agents/`, ADR-0016 |
| Rule 5 against a capability-owned port | **NOT TRIGGERED** — `StageContext` already carried exactly what an HTTP handler can supply: `correlation_id`, `organization_id`, `principal_id`, `attributes`. No HTTP concern (header, method, path, status) entered any application type |
| Migration | **None.** Alembic head unchanged |

The pressure Rule 5 exists to catch did appear and was declined: it is tempting to let the route
pass HTTP details through `StageContext` "since it is a bag anyway". The route translates instead —
it maps a `Request` into existing application objects and maps the result back into the documented
error model, and the seam is untouched.

### Finding: a control that existed, was tested, and had never executed

`AuthenticationMiddleware` shipped in the authentication milestone with unit tests, and
`build_http_app` **never added it to the app** — the factory did not even accept an authenticator.
Nothing was exposed, because every existing route is public by design, but the middleware was
enforced-by-nothing for the entire phase.

This is the **same class of debt Slice 14 spent a whole milestone eliminating for pipeline stages**,
recurring one layer out in delivery. It survived because both halves were individually green: the
middleware's tests passed, and the app's tests passed, and no test asked whether the app contained
the middleware. Slice 17 converts it from an implemented control into an executing one.

### Finding: middleware ordering is load-bearing and is now pinned

Starlette's `add_middleware` inserts at the **front**, so the last-added is outermost and runs
first. `RequestContextMiddleware` must therefore be added *last*: it establishes
`request.state.request_id`, which authentication stamps into its 401 bodies and its audit events.
Reversing them does not crash — the lookup falls back to `"unknown"` — which is exactly why it is
pinned by `test_the_401_body_carries_the_request_id_proving_middleware_ordering` rather than left
to a comment. *An ordering bug whose symptom is a degraded audit trail rather than an exception is
the kind that survives review.*

### Finding: the route-auth guard was vacuous for the new route, twice over

`tests/security/test_route_auth_coverage.py` has asserted since the auth milestone that an
unauthenticated request must not receive 200. Adding the first protected route should have made it
load-bearing. It did not — for **two independent reasons**, both found by attempting the
deliberate-failure proof rather than by reading the code:

1. **The guard's app did not contain the route.** `_app()` called `build_http_app` without an
   `inference_service`, so `/v1/inference` was absent from the routing table it enumerated.
2. **The guard only issued `GET`.** The first POST-only route answers 405 to a GET, and 405 is not
   200 — so every write endpoint would have passed this guard forever.

A third, subtler problem appeared once those were fixed: with a *denying* resolver the endpoint
returns 403 whether or not it checks authentication, so the guard would still have passed for the
wrong reason. The guard's app now wires a deliberately **permissive** service — permissions granted
to any principal, a provider offered to any tenant, unlimited budget — so that **authentication is
the only control that can refuse**. Only then can "the route forgot to require a principal" produce
a 200.

**The proof itself had to be corrected too.** Removing the auth check outright raises
`AttributeError` (a 500, not a 200), which is a different bug. The planted violation models the
mistake a developer actually makes: falling back to a fabricated default identity. That version
fails the guard, as it must.

*Three layers of vacuity in one pre-existing guard, none visible without trying to make it fail.*

### The guard evaluation

| Candidate | Classification | Reasoning |
|---|---|---|
| Route-auth coverage (`test_route_auth_coverage.py`) | **REUSED-EXTENDED, and non-vacuous for the first time** | Extended to include the inference router, to probe POST when GET is not allowed, and to be configured so only authentication can refuse. Before this slice it had no protected route and could not have failed |
| HTTP delivery reaches inference only through `InferenceService` (import-linter, 9 targets) | **NEW** | One forbidden target per ownership claim. `application.authorization.requirements` is deliberately **not** forbidden: its own docstring names the delivery layer as the *producer* of a permission declaration, and producing one is not interpreting one |
| `RoutingDecision` construction / Guard L | **REUSED, unchanged** | Proven against the new `delivery/http/api/inference.py` |
| Metric cardinality (Slice 16) | **REUSED, unchanged** | The new route records nothing directly; Slice 16's owners cover the HTTP-served path |
| A guard asserting the middleware is present in the app | **NOT APPLICABLE** to static analysis | Middleware presence is a runtime property of a constructed app. Enforced by test instead, and proven: removing the wiring fails the endpoint suite |
| Forbidding `delivery → config` | **REDUNDANT** | Already covered by "delivery must not import the composition root" |

### Enforcement (violated, mutation verified present, observed failing, restored to exact bytes, restore verified, observed passing)

**12/12 proven.**

| Guard | Violation planted | Observed |
|---|---|---|
| Route-auth coverage (extended) | route falls back to a fabricated identity | exit 1 |
| Middleware wiring | authentication wiring disabled in `app.py` | exit 1 (endpoint suite) |
| Delivery boundary (new) | one direct import per forbidden target, 8 proven separately | 33 kept / 1 broken, each |
| `RoutingDecision` (reused) | `RoutingDecision(...)` in `api/inference.py` | exit 1 |
| Guard L (reused) | `AgentRuntime` referenced in `api/inference.py` | exit 1 |

### Security behaviour

| Condition | Result | Proven by |
|---|---|---|
| No credential | 401, no routing/provider/budget | `test_an_unauthenticated_request_is_refused_and_reaches_nothing` |
| Invalid credential | 401 **at the middleware**, never reaching the route | `test_an_invalid_credential_is_refused_by_the_middleware_before_the_route` |
| Malformed `Authorization` header | 401 | `test_a_malformed_authorization_header_fails_closed` |
| Malformed / empty / extra-field body | 422 before admission or execution | three tests, each asserting no downstream call |
| Authenticated but unpermitted | 403, no routing, no provider, no reservation | `test_an_authorized_credential_without_permission_is_denied_before_routing` |
| Policy denial | 403, no routing, no provider | `test_a_policy_denial_is_403_and_reaches_no_routing_or_provider` |
| Budget exhausted | 402, provider never called | `test_a_budget_denial_is_402_and_the_provider_is_never_called` |
| Nothing routable | 503, provider never called | `test_nothing_routable_is_503_and_calls_no_provider` |
| Provider failed | 502, hold released not settled, **error text never echoed** | `test_a_provider_failure_is_502_and_never_echoes_the_provider_error_text` |
| Success | 200, spend booked exactly once | `test_a_fully_authorized_request_executes_and_returns_200` |

A denial never names the permission, the rule or the threshold
(`test_a_denial_does_not_disclose_the_permission_rule_or_threshold`) — the route adds no detail of
its own, so it cannot leak what the stages were careful to withhold. `extra="forbid"` keeps
unmodelled input out of the payload the policy engine measures.

### RBAC configuration: fail-closed default kept, and no new config surface

The default `NullPermissionResolver` grants nothing, so the production endpoint denies every
request. That was **not** weakened. No dev-permissive setting was added either, because none was
required: tests build the app through `build_http_app` with explicitly injected collaborators, the
same way the pre-existing app tests do. Durable RBAC storage remains **Slice 18**.

### Known limitations, stated rather than concealed

- **JWT credentials only.** `CompositeAuthenticator` (which also routes API keys) needs a
  request-scoped `ApiKeyRepository` — Slice 18's durable storage work. An API key today fails
  closed with a 401, which is correct for a credential type the deployment cannot verify.
  Substituting the composite later changes one line in the composition root.
- **The production endpoint denies every request** until permissions have storage (Slice 18).
- **One endpoint, deliberately minimal.** No streaming/SSE, no OpenAI compatibility, no tool-calling,
  no webhooks, pagination, SDKs, rate limiting or inference variants.
- **`PipelineStage.after_response` / `on_error` remain unexecuted** — unchanged by this slice, and
  still the oldest open piece of the stage protocol.
- **`token_authenticator.py` line 39 is uncovered**: the success path is exercised through the
  container-wired app only in production; the endpoint tests use a stub authenticator to control
  identity. Recorded rather than papered over with a test that asserts nothing.

### Decision

**No action against ADR-0016** (frozen, byte-unchanged). **No new ADR.** Combined validation:
**659 passed, 0 skipped, 97% coverage, mypy strict clean (236 files), import-linter 34 kept / 0
broken**; `api/inference.py` at 100% line coverage.

### Lessons

- **A guard that has never had a subject is not a guard.** Route-auth coverage looked green for the
  entire phase because there was no protected route to protect; three separate vacuity problems
  surfaced the moment one existed, and only because a deliberate violation was attempted.
- **"Implemented, tested, unwired" is this project's recurring defect, and it recurs one layer at a
  time.** Slices 5-13 left stages unexecuted; Slice 17 found the same shape in delivery. The common
  cause is that both halves pass their own tests and nothing asserts they are connected.
- **The realistic mutation matters more than the convenient one.** Deleting the auth check produced
  a crash, not a bypass; only the fallback-identity version modelled the bug the guard exists to
  catch, and it was the version that proved the guard.

## Evidence Record - Phase 4 Slice 18: RBAC Durable Storage + Hash-Chained Audit Sink

**Milestone type: Capability.** It puts storage behind two existing seams and creates no extension
point. One new architectural decision was required - **ADR-0019** - but not for a port.

### Rule 5 determination

| Protocol | Result |
|---|---|
| Tier-1 (`RoutingDecision`, `PipelineStage`, MCP/Tool ports, BaseAgent) | **NOT TRIGGERED** - zero diff on `domain/`, `ports/pipeline.py`, `ports/tools.py`, `ports/mcp.py`, `ports/agents.py`, `agents/`, ADR-0016 (sha256 `2735cdfa...f777c3`, byte-identical) |
| `PermissionResolver` (Slice 5, capability-owned) | **NOT TRIGGERED** - `SqlPermissionResolver` satisfies `resolve(principal_id, organization_id) -> frozenset[str]` unchanged. Pressure to return role names "for audit" declined: nothing consumes roles |
| `AuthAuditSink` (capability-owned) | **NOT TRIGGERED**, under genuine pressure - `audit_event.organization_id` is NOT NULL but `AuthAuditEvent.organization_id` is None for every rejection; `result`/`actor_type` are narrow enums. The sink maps and declines to persist a tenant-less event rather than widening the schema |
| `ApiKeyRepository` | **NOT TRIGGERED** - `SqlApiKeyRepository` already implemented it; what was missing was wiring |

### ADR-0019: the one genuinely new decision

Resolving a virtual API key to its tenant must happen *before* a tenant is known, but `api_key` is
RLS-scoped and `app_rw` is `NOBYPASSRLS` (ADR-0014, non-negotiable). Verified against real
PostgreSQL that a naively-wired repository returns zero rows for every key. The sanctioned path is a
single `SECURITY DEFINER` function exposing exactly one fact - which organization owns an exact
active prefix - paired with an owner-only `FOR SELECT` policy. This is a new architectural boundary
(the first sanctioned RLS exception), so it is an ADR, not a migration comment.

### Findings that only appeared under real PostgreSQL

- **Partitions did not inherit RLS or the append-only REVOKE.** As `app_rw` with tenant B bound, a
  tenant-A `audit_event` row was readable *and updatable* via `audit_event_2026_07`, while the same
  statements against the parent were correctly refused. Migration 0007 extends ENABLE+FORCE+policy
  and the UPDATE/DELETE revoke to every partition of `audit_event` and `usage_ledger`, over
  `pg_inherits` so future partitions are covered. `check_migration_guardrails.py` was blind to
  partitions (its regex requires a column body) - now it audits them.
- **The RBAC catalog was never seeded.** No migration inserted `permission`/`role`/
  `role_permission` rows, so a durable resolver would have resolved every principal to nothing.
  0007 seeds ADR-0008's matrix verbatim; `inference:invoke` is granted to no human role (ADR-0008:
  "via keys - application principals only"), which is why API-key verification had to ship too.
- **`audit_event` had partitions only to 2026-09-01.** The first writer would have failed on
  2026-09-01; 0007 adds a DEFAULT partition.
- **`CompositeAuthAuditSink` fan-out had never fanned out** - it had only ever held one sink, so its
  error-isolation path was at 67% coverage. Slice 18's durable sink is the second, and the
  isolation path is now proven and at 100%.

### Guard evaluation

| Guard | Classification |
|---|---|
| `check_resolver_construction.py` | **REUSED-EXTENDED** (adds `SqlPermissionResolver`), and its per-file exemption was corrected to per-class - the Slice-15 defect. Re-proved it still catches both prior targets |
| `check_migration_guardrails.py` | **REUSED-EXTENDED, and non-vacuous for partitions for the first time** - it never saw a partition before |
| "PermissionResolvers depend on nothing but their port" (Guard H) | **REUSED-EXTENDED** - added audit/accounting/ledger/execution targets now that the resolver holds a DB handle |
| "audit sinks record and reach no capability" | **NEW** - one forbidden target per ownership claim |
| RoutingDecision / Guard L | **REUSED** - proven against the two new adapter files |

**30/30 deliberate-failure proofs PROVEN** (violate -> observe fail -> restore exact bytes ->
observe pass), including re-proving each extended guard's original subjects and the per-class fix.

### Security behaviour (proven against real PostgreSQL, as `app_rw`)

RBAC resolves the ADR-0008 matrix and key scopes; an unknown principal, wrong tenant, inactive
membership, another tenant's custom role, and a revoked key all resolve to the empty set (deny). The
audit chain is recomputable from stored rows; each tenant has an independent chain; the runtime role
cannot UPDATE/DELETE any audit row or partition; a tenant cannot read or rewrite another's audit
rows through a partition; the ADR-0019 function discloses only the organization and cannot be used
to read `api_key` directly. Every storage failure fails closed (resolver -> empty set; repository ->
None -> 401; catalog/pricing -> raise -> fail closed). A tenant-less rejection is not persisted (no
tenant-scoped log exists) but is retained by the logging sink.

### Decision

**No action against ADR-0016** (frozen, byte-unchanged). **ADR-0019 created.** Migration
`0007_rbac_seed_audit_chain`.

## Evidence Record - Phase 4 Slice 19: Real Provider Adapter + Durable Catalog/Pricing

**Milestone type: Capability.** It puts storage and a real SDK behind existing seams. **No ADR.**

### Rule 5 determination

| Protocol | Result |
|---|---|
| Tier-1 | **NOT TRIGGERED** - zero diff on `domain/`, the Tier-1 ports, `agents/`, ADR-0016 |
| `ProviderClient` / `ProviderDescriptor` | **NOT TRIGGERED**, under real pressure - a real HTTP client needs a base URL, credential and timeout, and the descriptor carries "identity only". The adapter owns its own `ProviderConnection` keyed by provider name; no endpoint or credential enters `RoutingExecution` |
| `ProviderCatalog` | **NOT TRIGGERED** - already tenant-scoped |
| `PricingPort` | **TRIGGERED** - `organization_id` added to `price_for`. Capability-owned, so a Rule 5 event recorded here, not an ADR |

### The Rule 5 event on `PricingPort`

`price_table` is tenant-scoped (`organization_id NOT NULL`, RLS), so a durable pricing adapter
cannot read a row without a tenant. Slice 8 recorded the exact condition for adding the parameter:
"nothing in this slice consumes tenant-scoped pricing, so `price_for` stays global (Rule 5: no
active consumer needs the tenant dimension yet)." Slice 19 is that consumer. Active consumers:
`CostAccountant.account` and `ReservationService.reserve`, both of which already hold
`organization_id` at the call site, so the change propagates no new data through any layer.
`StaticPriceTable` keeps its deployment-wide behaviour by ignoring the argument (documented).

### What the real adapter does not do, and why it is proven

`OpenAiCompatibleProviderClient` (ADR-0003's named generic adapter, FR-024) does not retry
(reflection owns retry - `httpx` `retries=0`), does not select a provider (the descriptor arrives
chosen), does not raise for a provider-level failure (every transport error, timeout and HTTP status
becomes a classified `ProviderResponse`), and never echoes provider text or credentials. All proven
by contract tests against a scripted `httpx.MockTransport` - real library, no network, no credits.
Timeouts are explicit per provider; credentials are resolved from the secrets manager at
composition time and fail startup if unresolvable (ADR-0011 / ADR-0009 row 16).

### Durable catalog and pricing (proven against real PostgreSQL)

The catalog reads enabled provider/model rows per tenant, honours FR-028 runtime enable/disable by
reading through on every call, offers one descriptor per provider (the runtime's vocabulary is
provider names), isolates tenants via RLS, and raises rather than reporting "no providers" on an
outage. Pricing selects the row *in force by time* (not the newest), so a future price does not
apply early and a settled cost is reproducible (FR-074/075); it isolates tenants and raises rather
than looking unpriced on an outage.

### The headline, proven end to end through the real container

The exact request that returned **503 no_eligible_provider** in Slice 18 (empty catalog) now
returns **200** with spend booked exactly once against the effective-dated `price_table` - routing
has a provider to choose, pricing can cost the call, and the existing reserve/execute/settle path
runs unchanged. The in-memory client still executes in this test (wiring a live provider would spend
credits); the real adapter's behaviour is covered by the contract tests.

### Known debt introduced

A routable provider configured without a price reaches `UnknownPriceError` in the served path and
fails closed as a generic 500 (no provider detail reaches the client; no spend is booked). Mapping
it to a tailored fail-closed 5xx is deferred rather than done, because it would require importing
accounting into delivery (contract-forbidden) or reversing Slice 8's "config defect is never a
budget outcome" invariant. Recorded, not hidden.

### Guard evaluation

| Guard | Classification |
|---|---|
| `check_provider_construction.py` | **REUSED-EXTENDED** (adds the real client + both catalogs), per-file -> per-class exemption fixed; prior targets re-proved |
| `check_accounting_construction.py` | **REUSED-EXTENDED** (adds `SqlPriceTable`), per-file -> per-class fixed |
| "provider client adapters execute and own no other capability" | **NEW** |
| "the durable provider catalog supplies candidates and does not route" | **NEW** |
| "provider client implementations are mutually independent" (3) / "pricing implementations are mutually independent" (2) | **REUSED-EXTENDED / NEW** |
| "ports declare contracts only (no transport)" | **REUSED, now load-bearing** - it forbids `httpx` in ports, and a real httpx client now exists to be kept out |

**26/26 deliberate-failure proofs PROVEN**, including re-proving each extended guard's original
subjects, both per-class fixes, and behavioural proofs (reverting the container to the in-memory
catalog or static pricing, and removing the effective-dating lower bound, each break a test).

### Decision

**No action against ADR-0016** (frozen, byte-unchanged). **No new ADR.** No schema change
(`provider`/`model`/`price_table` already existed and are RLS-protected). Alembic head unchanged
at `0007_rbac_seed_audit_chain`.
