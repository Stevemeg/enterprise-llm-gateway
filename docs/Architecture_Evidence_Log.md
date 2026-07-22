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

