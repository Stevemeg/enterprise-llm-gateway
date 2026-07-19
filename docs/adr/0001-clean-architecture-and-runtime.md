# ADR-0001: Clean/Hexagonal architecture & backend runtime

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, Principal Engineer
- **Phase:** 2 — Architecture

## Context & problem
The gateway must be highly maintainable and extensible: new providers, routing strategies, cache
backends, and governance policies will be added continuously without destabilizing the core. It must
also serve two deployment modes (SaaS multi-tenant and single-tenant self-hosted) from **one
codebase** (NFR-D01). We need an internal structure and a runtime that make the domain logic
independent of frameworks and external services, and that perform on the hot path at thousands of RPS.

## Decision drivers
- NFR-M01 (domain independent of frameworks/providers), NFR-M02 (open/closed extension), NFR-M03
  (strong typing), NFR-M04 (testability/coverage).
- NFR-P01 (p99 routing overhead ≤ 50 ms), NFR-S01 (≥5k RPS), NFR-P04 (streaming TTFB overhead ≤20ms).
- NFR-D01 (one codebase, two deployment modes).
- Tech stack from spec §2 (FastAPI, Python 3.12, Pydantic v2).

## Options considered
### Option A — Hexagonal (Ports & Adapters) + Clean Architecture layering, async Python/FastAPI
Domain and use-cases at the center; providers, DB, cache, IdP, event bus behind **ports**
implemented by **adapters**. Delivery (REST) and infrastructure are outermost.
- **Pros:** Providers/cache/eventing are swappable adapters → satisfies open/closed; domain is
  unit-testable without I/O; deployment-mode differences isolated to composition root; async I/O fits
  the I/O-bound proxy workload (mostly waiting on providers).
- **Cons:** More upfront structure/boilerplate; discipline needed to keep dependencies pointing inward.

### Option B — Layered "N-tier" (controller → service → repository), FastAPI
- **Pros:** Familiar; less ceremony.
- **Cons:** Business logic tends to leak into services coupled to ORM/provider SDKs; harder to swap
  infrastructure; weaker isolation of the two deployment modes.

### Option C — Modular monolith with framework-centric design (Django) or a Go/Node runtime
- **Pros:** Batteries-included (Django) or raw throughput (Go).
- **Cons:** Django's ORM-centric model fights Clean Architecture; Go/Node contradicts the mandated
  Python/FastAPI stack and the team's typing/tooling choices; higher rewrite risk. Rejected on
  stack-fit grounds.

## Decision
Adopt **Option A**: **Hexagonal + Clean Architecture** with four concentric layers —
**Domain** (entities, value objects, domain services), **Application** (use-cases/orchestrators,
port interfaces), **Adapters** (provider adapters, repositories, cache, event bus, IdP, secrets), and
**Delivery/Infrastructure** (FastAPI routers, workers, config, composition root). Runtime is
**Python 3.12 + FastAPI (ASGI) + Pydantic v2**, fully `async` on the request path. Deployment-mode
differences (SaaS vs self-host) are resolved **only** in the composition root via configuration/DI,
never in domain code.

We deploy as a **modular monolith of independently-scalable processes** initially: one API service
plus worker processes (see [ADR-0005](0005-eventing-backbone.md)), all from one codebase, with clear
module seams so services can be extracted later if a module's scaling profile diverges.

## Consequences
- **Positive:** Adding a provider/strategy/policy = new adapter, no core change (NFR-M02); domain
  tests need no I/O (NFR-M04); one codebase cleanly yields both deployment modes (NFR-D01); async
  matches the I/O-bound profile for low overhead at high RPS.
- **Negative:** Requires strict dependency-rule enforcement (linting/import rules) and DI wiring.
- **Follow-ups:** Define the port interfaces in Phase 4/5; enforce dependency direction in CI (Phase 11).

## Requirements satisfied
- Functional: FR-025, FR-026 (adapter contract, open/closed), FR-141 (config-driven modes).
- Non-functional: NFR-M01, NFR-M02, NFR-M03, NFR-M04, NFR-P01, NFR-P04, NFR-D01.

## Review notes
Revisit process extraction (monolith → services) if load tests (Phase 13) show a module (e.g.,
embedding/semantic-cache) with a scaling profile that starves the API tier. Decision to extract would
be a new ADR.
