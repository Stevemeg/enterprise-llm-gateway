# Backend Style Guide

Concrete coding standards for the backend. Enforced by `ruff`, `mypy`, and `import-linter` in CI.
Extends [Backend Implementation Guide §16](../docs/Backend_Implementation_Guide.md#16-code-style-rules).

## 1. Language & tooling
- **Python 3.13**, fully type-annotated. `mypy --strict` must pass (no untyped defs; no `Any` in public
  signatures without justification). Dependencies & envs via **uv**.
- **Format:** `ruff format`, line length **100**. **Lint/imports:** `ruff check` (includes isort rules).
  Zero warnings.
- **No `print`**; use structured logging. **No blocking I/O** in async paths (offload to executor with a
  comment if unavoidable).

## 2. Naming
| Kind | Convention | Example |
|------|-----------|---------|
| Module/package | `snake_case`, domain-named | `budget`, `providers`, `eventbus` |
| Class | `PascalCase` | `RoutingEngine`, `BudgetReservation` |
| Function/variable | `snake_case` | `reserve_budget`, `request_id` |
| Constant | `UPPER_SNAKE` | `DEFAULT_LIMIT` |
| Port (interface) | `<Thing>Port` | `LLMProviderPort`, `CachePort` |
| Adapter | `<Backend><Thing>Adapter` | `RedisLuaBudgetAdapter`, `OpenAIAdapter` |
| Use-case | verb-noun class/callable | `CreateChatCompletion`, `CreateBudget` |
| Repository | `<Aggregate>Repository` | `BudgetRepository` |
| Test | `test_<unit>__<scenario>` | `test_reserve__denies_when_over_limit` |

Match DB/API field names (`snake_case`) so mapping stays 1:1.

## 3. Types & data
- **Pydantic v2** only at boundaries (`delivery/http/schemas`, `config/settings`). Domain uses plain typed
  classes / frozen dataclasses — no Pydantic in `domain`.
- **Value objects are immutable** (`frozen=True`); prefer new objects over mutation.
- **Money** is a typed value object over `Decimal` — never `float`. Times are timezone-aware UTC.
- Use **typed ids** (newtypes in `shared/`) rather than bare `str`/`UUID` where it prevents mix-ups.
- Prefer `Protocol` for ports (structural) unless an ABC is needed; keep them minimal.

## 4. Functions & classes
- Small, single-purpose functions; pure where possible (domain services are pure).
- **Constructor injection**; no service locators, no module-level singletons for dependencies.
- Public classes/functions have docstrings (what + why); comments explain intent, not mechanics.
- Avoid deep nesting; early-return over nested `if`. No cleverness that hurts readability.

## 5. Errors & control flow
- Raise the **typed exceptions** from the hierarchy (Implementation Guide §11): `DomainError`,
  `ApplicationError`, `InfrastructureError`. Never raise bare `Exception`.
- **No bare `except:`**; catch specific types; on catch, log with context and make an explicit decision
  (retry / fail-open / fail-closed per [ADR-0009](../docs/adr/0009-fail-open-fail-closed-matrix.md)).
- **No `assert`** for runtime control flow (asserts are for tests/invariants only).
- HTTP error mapping happens **only** in `delivery/http/errors.py`; domain/application never build responses.
- Never swallow errors silently; never leak internals/secrets to clients (FR-010).

## 6. Async & concurrency
- `async def` on request/worker paths; `await` all I/O. Use connection pools created at startup.
- Do **not** hold a DB transaction across a provider/network call (ADR-0004).
- Bound concurrency (semaphores) where fan-out could exhaust pools; make retries idempotent.

## 7. Imports & layering
- Absolute imports under `gateway.*`; no wildcard imports.
- Respect layer contracts (import-linter): `domain` imports only `shared`/stdlib; `application` imports
  `domain`/`shared`; `adapters` import `application`(ports)/`domain`; `delivery` imports `application`/
  `domain`; only `config` imports outward.
- No cross-adapter imports.

## 8. Logging & observability
- Structured JSON via the shared logger; always include `request_id` (contextvar).
- **Never log** secrets, keys, tokens, or raw prompts/responses unless policy permits; a redaction filter
  enforces this and CI scans for violations.
- Hot paths emit an OTel span and the relevant metrics — no silent code on the hot path.

## 9. Configuration
- All config via `config/settings.py` (typed); secrets via `SecretsPort`. No scattered `os.environ`
  reads; no secret defaults. Fail-fast at startup on missing/invalid config (FR-146).

## 10. Tests
- Mirror `src/` layout. Unit tests use **fakes** for ports (behavioral), not brittle mocks. Integration
  tests use real Postgres/Redis (SQLite locally). Name tests by scenario (§2).
- Every bug fix adds a regression test. Concurrency/isolation/fail-mode tests are mandatory where relevant.

## 11. Documentation
- Update the relevant `docs/*` and ADRs when behavior/contract changes (same PR).
- Public ports/use-cases carry docstrings describing contract + failure modes.

## 12. Enforcement
`ruff check`, `ruff format --check`, `mypy --strict`, `import-linter`, and `pytest` (coverage
>=90% meaningful) run in CI (Phase 11) and locally (CONTRIBUTING §4). A failing check blocks merge.

## 13. Cryptographic boundary (single audited surface)
All cryptography goes through one boundary (Cryptographic_Architecture.md):
- **Primitives** — CSPRNG (`secrets`), hashing (`hashlib`), timing-safe compare (`hmac`), and zeroization
  live **only** in `shared/secrets.py`. No other module may import `secrets`/`hmac`/`hashlib`.
- **Asymmetric signing** — JWT/JWKS (`jwt`, `cryptography`) live **only** in `adapters/security/`.
- Enforced by import-linter contracts. Any exception must be justified in code + this guide.
Never call `secrets.token_urlsafe`, `os.urandom`, `hashlib.*`, `hmac.compare_digest`, or sign a JWT
outside that boundary.
