# ADR-0000: Record architecture decisions (use ADRs)

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, Principal Engineer
- **Phase:** 2 — Architecture

## Context & problem
This is a long-lived, multi-phase enterprise system built one phase at a time with explicit approval
gates. Decisions made now (tenancy, eventing, routing) constrain every later phase. We need a durable,
reviewable record of *why* each significant choice was made, so that future contributors (and
interview/design reviews) can reconstruct the reasoning rather than reverse-engineering it from code.

## Decision drivers
- Project constraint CON-04 (one phase at a time, decisions justified before implementation).
- NFR-M06 (all significant decisions documented via ADRs).
- Need for consistency across a 15-phase build (project spec §3, §12).

## Options considered
### Option A — Lightweight Nygard ADRs in-repo (Markdown, one file per decision)
- **Pros:** Versioned with code; diff-able; low friction; industry standard; renders on GitHub.
- **Cons:** Requires discipline to keep updated.

### Option B — Decisions embedded in a single large design document
- **Pros:** One place to read.
- **Cons:** Poor change tracking; merge conflicts; hard to mark supersession; decisions get buried.

### Option C — External wiki / Confluence
- **Pros:** Rich editing, comments.
- **Cons:** Drifts from code; not versioned with the repo; violates "all docs under /docs";
  unavailable in air-gapped/self-hosted contexts.

## Decision
Adopt **Option A**: Markdown ADRs under `docs/adr/`, extended with explicit multi-option comparison
and FR/NFR traceability. ADRs are immutable once Accepted; changes are made by a new superseding ADR.
A tabular summary is maintained in `docs/Architecture_Decision_Log.md`.

## Consequences
- **Positive:** Transparent, versioned decision history; satisfies the project's decision-workflow
  mandate; doubles as interview/design-review material.
- **Negative:** Slight authoring overhead per decision.
- **Follow-up:** Every Phase 2+ significant decision must land as an ADR and a Decision-Log row.

## Requirements satisfied
- Functional: — (process decision)
- Non-functional: NFR-M06.

## Review notes
Revisit only if the team adopts a different, equally-versioned decision-capture tooling.
