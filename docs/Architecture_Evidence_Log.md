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
