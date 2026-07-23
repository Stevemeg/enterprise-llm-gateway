#!/usr/bin/env bash
# Gate 2 - full local validation on a real developer machine (Python 3.13 via uv).
#
# This script and validate.ps1 must enforce an IDENTICAL set of checks. They drifted once:
# every Phase-4 guard existed only in the .ps1, so the same repo passed validation with three
# architectural invariants unenforced depending on which shell you happened to use. That is the
# project's recurring failure mode - a check that reports success while structurally unable to
# fail - so parity is now itself a checked invariant (check_validation_parity.py, run below).
#
# All guards run via `uv run python`, not the system python3: on Git Bash a bare `python3` may
# not exist, and if it does it is not the interpreter the project targets.
set -uo pipefail
cd "$(dirname "$0")/../backend"

fail() { echo ""; echo "FAIL - $1"; exit 1; }
step() { echo "==> $1"; }

step "uv sync (Python 3.13 + deps)"
uv sync || fail "uv sync failed."

step "ruff check (lint + imports)"
uv run ruff check . || fail "ruff check failed."

step "ruff format --check"
uv run ruff format --check . || fail "ruff format check failed."

step "mypy (strict)"
uv run mypy src tests || fail "mypy failed."

step "import-linter (architecture contracts)"
uv run lint-imports || fail "import-linter contracts broken."

step "PowerShell encoding guard (ASCII + BOM + CRLF)"
uv run python ../scripts/check_powershell_encoding.py ../scripts || fail "PowerShell encoding guard failed."

step "validation parity guard (validate.sh and validate.ps1 must match)"
uv run python ../scripts/check_validation_parity.py ../scripts || fail "Validation scripts have drifted."

step "RoutingDecision construction guard (only AgentRuntime may build one)"
uv run python ../scripts/check_routing_decision_construction.py src/gateway || fail "RoutingDecision construction guard failed (ADR-0016 invariant 3)."

step "Registry construction guard (only the composition root may build one)"
uv run python ../scripts/check_registry_construction.py src/gateway || fail "Registry construction guard failed (ADR-0016 invariant 2)."

step "MCP construction guard (only the composition root may build one)"
uv run python ../scripts/check_mcp_construction.py src/gateway || fail "MCP construction guard failed (ADR-0016 invariant 2)."

step "Resolver construction guard (only the composition root may build one)"
uv run python ../scripts/check_resolver_construction.py src/gateway || fail "Resolver construction guard failed (ADR-0016 invariant 2)."

step "Routing engine guard (construction + sole AgentRuntime caller)"
uv run python ../scripts/check_routing_engine.py src/gateway || fail "Routing engine guard failed (ADR-0016 invariants 2-3)."

step "Provider construction guard (only the composition root may build one)"
uv run python ../scripts/check_provider_construction.py src/gateway || fail "Provider construction guard failed (ADR-0016 Slice 7)."

step "Accounting construction guard (only the composition root may build one)"
uv run python ../scripts/check_accounting_construction.py src/gateway || fail "Accounting construction guard failed (ADR-0016 Slice 8)."

step "Execution construction guard (cache/dedup/coordinator only in the composition root)"
uv run python ../scripts/check_execution_construction.py src/gateway || fail "Execution construction guard failed (ADR-0016 Slice 10)."

step "migration guardrail (tenant tables must ENABLE+FORCE RLS + policy)"
uv run python ../scripts/check_migration_guardrails.py migrations/sql || fail "Tenant-table RLS guardrail failed (ADR-0002/0014)."

postgres_configured=0
if [[ "${GATEWAY_DATABASE__URL:-}" == postgresql* ]]; then
  postgres_configured=1
  # Runtime/DDL split (ADR-0014): migrations run as the OWNER/migrator; the app + tests run
  # as the least-privilege app_rw role (GATEWAY_DATABASE__URL) so RLS is actually enforced.
  OWNER_URL="${GATEWAY_MIGRATION_DATABASE__URL:-${GATEWAY_DATABASE__URL}}"
  if [[ "${OWNER_URL}" == "${GATEWAY_DATABASE__URL}" ]]; then
    echo "   WARNING: GATEWAY_MIGRATION_DATABASE__URL not set; running migrations as the"
    echo "            runtime role. If that is app_rw this fails (no DDL privilege)."
    echo "            Set it to the owner URL - see backend/.env.example."
  fi

  step "alembic upgrade head (as owner/migrator)"
  GATEWAY_DATABASE__URL="${OWNER_URL}" uv run alembic upgrade head || fail "alembic upgrade failed."
  GATEWAY_DATABASE__URL="${OWNER_URL}" uv run alembic current

  step "Gate: runtime role must be NOSUPERUSER + NOBYPASSRLS (ADR-0014)"
  uv run python ../scripts/check_runtime_role.py || fail "Bypass-containment gate failed (ADR-0014)."
else
  step "No Postgres configured; repo layer validated against SQLite in tests"
fi

step "pytest + coverage"
pytest_output=$(uv run pytest --cov=src/gateway --cov-report=term-missing 2>&1)
pytest_exit=$?
echo "${pytest_output}"
if [[ ${pytest_exit} -ne 0 ]]; then fail "pytest FAILED - validation did NOT pass."; fi

# Three terminal states, because PASS/FAIL alone cannot express "the gate never ran".
# A run that skips every integration test is not a pass - it is an unexecuted gate, and
# reporting that as green is how an unverified change ships believing it was validated.
skipped=0
if [[ "${pytest_output}" =~ ([0-9]+)\ skipped ]]; then skipped="${BASH_REMATCH[1]}"; fi

echo ""
if [[ ${postgres_configured} -eq 0 ]]; then
  echo "INCOMPLETE - Gate 2 did NOT run"
  echo "  Postgres was not configured, so migrations, the runtime-role check and the"
  echo "  integration tests never executed (${skipped} skipped)."
  echo "  Gate 1 passed. Runtime validation is NOT verified."
  echo "  Set GATEWAY_DATABASE__URL and GATEWAY_MIGRATION_DATABASE__URL, then re-run."
  exit 2
fi
if [[ ${skipped} -ne 0 ]]; then
  echo "FAIL - Postgres is configured but ${skipped} test(s) were skipped"
  echo "  With Gate 2 available every test must execute. Investigate the skips."
  exit 1
fi
echo "PASS - ALL LOCAL VALIDATION PASSED (Gate 1 + Gate 2, 0 skipped)"
