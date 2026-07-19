"""Tests for the RLS tenant-scope statement (ADR-0002)."""

from __future__ import annotations

from uuid import UUID

from gateway.adapters.persistence.rls import tenant_scope_statement


def test_statement_uses_transaction_local_set_config() -> None:
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    statement = tenant_scope_statement(tenant)
    rendered = str(statement)
    assert "set_config" in rendered
    params = statement.compile().params
    assert params["name"] == "app.current_org"
    assert params["org"] == "00000000-0000-0000-0000-000000000001"
