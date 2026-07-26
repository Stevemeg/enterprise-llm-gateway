# ADR-0020: Narrowing proven-vacuous Tier-1 surface

- **Status:** **Accepted and APPLIED** (2026-07-26). Written as *Proposed* during Phase 5 M2 —
  which stopped rather than making a Tier-1 change unilaterally, per GP-2 — and accepted by
  explicit decision before the M1+M2 work was published. The cleanup it authorizes is implemented;
  see "Applied outcome" below.
- **Date:** 2026-07-26
- **Deciders:** Repository owner (explicit approval, 2026-07-26)
- **Phase:** 5 — Milestone 2 (Serving correctness & debt closure)
- **Affects:** ADR-0016 Tier-1 invariants 3 and 5. **This is a deliberate Tier-1 contraction**, and
  this ADR is the sole governance mechanism authorizing it. Amends no rule; ADR-0016 remains frozen
  and byte-identical (`sha256 2735cdfa…f777c3`).

## Context & problem

The Phase-4 closeout review found three pieces of architecture with no consumer. One of them —
the Slice-8 `BudgetEnforcer`/`BudgetPort`/`InMemoryBudgetStore` layer — is **capability-owned**,
so M2 removed it under GP-1 clause 1 and recorded the evidence. No ADR was required: no accepted
decision was reversed, and Rule 2 governs a seam's birth, not the retirement of one that a whole
phase failed to give a consumer.

The other two are different in exactly one respect that changes everything: **they are Tier-1
surface.**

| Vacuous surface | Tier-1 invariant | Verified state after M1 |
|---|---|---|
| `PipelineStage.after_response`, `PipelineStage.on_error` | 5 — pipeline stage protocol | `RequestPipeline.admit` calls **only** `before_request` (`runner.py:204`). All three production stages return an inert `CONTINUE` from both. Never invoked in any path. |
| `RoutingDecision.selected_model` (and `AgentContext.selected_model`) | 3 — explainable agent routing | No writer anywhere. `runtime.py:125` is the sole reference and it is a *read*; it therefore evaluates to `None` on every decision this system has ever produced. |

Rule 5 governs how a protocol **grows**: only through an active consumer. It says nothing about
how one shrinks, and that asymmetry is the gap this ADR sits in. The project's own discipline —
"no field without a reader", "no port without a real consumer" — points at removal. ADR-0016's
freeze points at not touching Tier-1 without a decision record. Both are right, which is precisely
the situation GP-2 exists for.

## Was a consumer found in M1?

This was the honest test, and it was applied before writing anything: **streaming is the strongest
new consumer this architecture has acquired since MCP.** If a lifecycle hook or a model field were
going to become load-bearing, that is where it would have happened. Neither did.

- **`after_response` and streaming evaluation.** M1 does not evaluate streamed inferences, because
  `InferenceService.serve_stream` returns while the stream is still open and evaluation observes a
  *completed* one. A post-response stage hook looks like the answer, and is not:
  `after_response(context: StageContext)` receives no outcome, no response and no usage.
  `ports/evaluation.py:24` already records exactly this ("a stage's `after_response` would have to
  smuggle that through"). Making the hook useful would mean widening a **Tier-1** protocol to
  carry a response — a Rule 5 event against Tier 1, i.e. the thing the freeze forbids most
  directly. Streaming therefore *strengthens* the case that the hook is the wrong shape, rather
  than rescuing it.
- **`selected_model` and streaming.** The streamed path resolves its model from
  `RoutingExecution.provider.model`, the same place the unary path does. The field acquired no
  reader.

## Decision

1. **Narrow `PipelineStage` to `name` + `before_request`.** Delete `after_response` and `on_error`
   from the protocol and the four implementations, and delete the tests that assert their
   inertness. Invariant 5's substance — one stable interception seam that lets policy, evaluation
   and approval be added without changing provider, router or agent interfaces — is carried
   entirely by `before_request` + `StageResult`, and is unaffected.
2. **Remove `selected_model`** from `RoutingDecision` and `AgentContext`. Invariant 3's substance —
   a decision cannot be produced without its reasoning trace — is carried by `reasoning_steps`, and
   is unaffected. The selected model remains available, and is already read, on
   `RoutingExecution.provider`.
3. **Neither change amends ADR-0016.** Its rules, governance principles and tier assignments stay
   exactly as written. What changes is the *shape of two seams the ADR names*, recorded here.

## Why this is not "removing architecture because it is inconvenient"

The rejected reasoning, stated so a reviewer can check it:

- Not *"nothing uses it yet"*. Both survived a full phase (Slices 1–21) plus the milestone most
  likely to need them, with zero consumers and zero writers.
- Not *"it is easier without it"*. Neither costs anything to keep. The cost is that they are
  **misleading**: a reader of `PipelineStage` reasonably concludes responses pass back through the
  chain, and a reader of `RoutingDecision` reasonably concludes the model is part of the
  explanation. Both conclusions are false, and both would shape someone's next design.
- Not *"vacuity is always removable"*. The Phase-4 review deliberately classified the
  `ToolRegistryPort` and MCP seams as **LATENT-BUT-JUSTIFIED** rather than vacuous, on exactly this
  distinction: they are Tier-1 seams whose whole purpose is to exist *before* their consumer
  (ADR-0016's admission test is counterfactual). `after_response` and `selected_model` fail that
  test — nothing about adding evaluation, policy or a model-aware consumer later would force a
  published interface to change, because the seam that would carry it (`before_request` /
  `RoutingExecution`) already exists.

## Alternatives considered

- **Keep both, documented as latent.** Rejected: this is the status quo, and the Phase-4 review
  already documented them. Documentation did not stop them being read as live surface; it is the
  option that costs nothing and fixes nothing.
- **Wire `selected_model` from `ProviderAgent`.** Rejected, and this was the closest call. It is a
  one-line change and the model genuinely is a different fact from the provider. But it would
  create a *writer* without creating a *reader*, so the field would go from vacuous to
  write-only — the same defect wearing a coat. "Do not populate a field to make it used" is the
  rule, and the honest move is to remove it and re-add it when something reads it.
- **Invent a response-phase consumer for `after_response`.** Rejected outright: that is inventing a
  capability to justify a method, the inverse of Rule 5 and the most expensive possible mistake
  here.
- **Amend ADR-0016 directly.** Rejected: it is frozen, and it is not wrong. Nothing in its rules
  needs to change for these two removals to be correct.

## Consequences

- **Positive.** Two Tier-1 types stop describing behaviour the system does not have. The stage
  protocol becomes exactly what the runner executes, so "implemented but never invoked" — this
  project's documented recurring failure mode — has two fewer places to hide.
- **Negative / obligations.** `PipelineStage` is `runtime_checkable`; narrowing it means any
  out-of-tree stage implementing the old shape still satisfies the new protocol (extra methods are
  harmless), but a stage *relying* on being called back would silently stop being called back —
  except that nothing ever called it back, so there is no behaviour to lose. The protocol-shape
  test and the Phase-4 seam conformance test must be updated in the same change, and the evidence
  log must record the narrowing as a Tier-1 diff against `863ad64`.
- **Reversibility.** Both removals are additive to undo. Re-adding either is a Rule 5 event that
  must then name its consumer — which is the property this ADR is really buying.

## Requirements satisfied

Upholds ADR-0016 Rules 1, 3 and 5 and GP-1/GP-2 (this ADR *is* the GP-2 stop). Reverses no accepted
decision. Touches no security control, no tenant boundary and no persisted schema.

## Applied outcome (2026-07-26)

The evidence was independently re-confirmed against the working tree at acceptance time, **after**
M1 and M2 were complete — not carried over from when this ADR was drafted:

- `after_response` / `on_error`: **0 invocations** repo-wide. `RequestPipeline` references only
  `stage.name` and `stage.before_request`.
- `selected_model`: **0 writers**. Sole reference was the read at `runtime.py:125`.
- `RoutingDecision` is **never serialized or persisted**, so no external contract depended on its
  shape; the routing engine resolves its descriptor from `selected_provider` (the *name*).
- No `scripts/*.py` structural guard encoded any of the three surfaces.

**Applied exactly as decided, and nothing more.** Three declarations deleted, plus the four inert
implementations, `AgentContext.selected_model`, the single read, and four tests that asserted the
inertness of never-invoked methods. **No replacement abstraction was introduced, no lifecycle hook
was added, and no other field was populated to compensate for `selected_model`** — the model
remains where every consumer already read it, on `RoutingExecution.provider`.

The contraction has exactly one observable consequence, and it is a reduction in obligation: a
stage implementing only `before_request` now satisfies the protocol, where `runtime_checkable`
`isinstance` previously rejected it (verified: `False` before, `True` after). No code path, status
code, audit record, metric or persisted row differs.

Pinned against silent reversal by `tests/unit/test_tier1_contraction_adr_0020.py`, whose shape
assertions were mutation-proven (re-adding either surface fails the suite; restoring passes it).
The full record — previous shape, exact diff, consumers checked, guard proofs — is in
[`Architecture_Evidence_Log.md`](../Architecture_Evidence_Log.md) under "Phase 5 — Tier-1
contraction".

One loose thread, flagged rather than hidden: `docs/API_Examples.md` still shows an aspirational
`x_gateway.selected_model` field in a response shape the live endpoint does not implement. When
that shape is built, the value comes from the descriptor.

## Review notes

Superseding this ADR (re-adding either surface) is a Rule 5 event against Tier 1 and must name the
active consumer that forces it — which is the property this decision was really buying.
