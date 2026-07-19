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

### OBSERVED
*Pending.*

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

Both are recorded honestly as **weaker evidence**: their predictions were not written in advance,
so ✓ reflects hindsight rather than a binding test. Slice 2 has a full record above. Tool Registry
is the first milestone with a genuine, pre-registered prediction.
