#!/usr/bin/env python3
"""Tenant-table merge guardrail (ADR-0002 / ADR-0014).

Fails the build if any migration introduces a **tenant-scoped table** (one with an
``organization_id`` column) that is not protected by Row-Level Security. For every such table
the guardrail requires, somewhere in the migration set:

    * ``ENABLE ROW LEVEL SECURITY``
    * ``FORCE ROW LEVEL SECURITY``   (owner is not exempt)
    * a tenant-isolation ``CREATE POLICY`` on the table

app_rw grants on new tables are guaranteed structurally by ``ALTER DEFAULT PRIVILEGES``
(migration 0003) and proven by ``test_default_privileges.py``, so they are not re-checked here.

Both the explicit form (``ALTER TABLE t ENABLE/FORCE ...``; ``CREATE POLICY ... ON t``) and the
bulk ``DO $$ ... FOREACH t IN ARRAY[...] ...`` loop used by the initial schema are recognized.

Intentionally-global tables that carry a *nullable* ``organization_id`` (NULL = global/system
reference data, RLS_Strategy.md §3/§10) are exempt via EXEMPT_TENANT_TABLES.

Usage:  python scripts/check_migration_guardrails.py [migrations_sql_dir]
Exit 0 = all good; exit 1 = a violation (printed).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# NULL-org global/system reference tables (documented non-tenant rows). See RLS_Strategy §3/§10.
EXEMPT_TENANT_TABLES: frozenset[str] = frozenset(
    {"role", "feature_flag", "background_job"}
)

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(?P<name>\w+)\"?\s*\((?P<body>.*?)\n\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_ENABLE = re.compile(
    r"ALTER\s+TABLE\s+\"?(\w+)\"?\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", re.IGNORECASE
)
_FORCE = re.compile(
    r"ALTER\s+TABLE\s+\"?(\w+)\"?\s+FORCE\s+ROW\s+LEVEL\s+SECURITY", re.IGNORECASE
)
_POLICY_ON = re.compile(r"CREATE\s+POLICY\s+\w+\s+ON\s+\"?(\w+)\"?", re.IGNORECASE)
_ARRAY_BLOCK = re.compile(r"ARRAY\s*\[(?P<items>.*?)\]", re.IGNORECASE | re.DOTALL)


def _loop_tables(sql: str) -> set[str]:
    """Tables covered by a `FOREACH t IN ARRAY[...]` RLS loop (bulk enable+force+policy)."""
    covered: set[str] = set()
    if not re.search(r"ENABLE\s+ROW\s+LEVEL\s+SECURITY", sql, re.IGNORECASE):
        return covered
    for block in _ARRAY_BLOCK.finditer(sql):
        # Only treat an array as an RLS loop if the file applies ENABLE/FORCE via format(%I).
        if re.search(r"FORCE\s+ROW\s+LEVEL\s+SECURITY", sql, re.IGNORECASE):
            covered |= {
                t.strip().strip("'\" ")
                for t in block.group("items").split(",")
                if t.strip()
            }
    return covered


MAX_REVISION_ID = 32  # alembic_version.version_num is varchar(32)


def audit_revision_ids(versions_dir: Path) -> list[str]:
    """Revision IDs longer than 32 chars fail at the version stamp AFTER the DDL has run,
    rolling the whole migration back with a confusing StringDataRightTruncation error."""
    problems: list[str] = []
    for path in sorted(versions_dir.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("revision: str"):
                rev = line.split("=", 1)[1].strip().strip('"\'')
                if len(rev) > MAX_REVISION_ID:
                    problems.append(
                        f"{path.name}: revision id {rev!r} is {len(rev)} chars "
                        f"(max {MAX_REVISION_ID}) - alembic_version.version_num is varchar(32)"
                    )
    return problems


def audit(sql_dir: Path) -> list[str]:
    files = sorted(sql_dir.glob("*.sql"))
    corpus = "\n".join(f.read_text(encoding="utf-8") for f in files)

    enabled = set(_ENABLE.findall(corpus)) | _loop_tables(corpus)
    forced = set(_FORCE.findall(corpus)) | _loop_tables(corpus)
    policied = set(_POLICY_ON.findall(corpus)) | _loop_tables(corpus)

    violations: list[str] = []
    for f in files:
        for m in _CREATE_TABLE.finditer(f.read_text(encoding="utf-8")):
            name, body = m.group("name"), m.group("body")
            if not re.search(r"\borganization_id\b", body):
                continue  # not tenant-scoped
            if name in EXEMPT_TENANT_TABLES:
                continue
            missing = [
                label
                for label, s in (
                    ("ENABLE RLS", enabled),
                    ("FORCE RLS", forced),
                    ("POLICY", policied),
                )
                if name not in s
            ]
            if missing:
                violations.append(
                    f"{f.name}: tenant table '{name}' is missing: {', '.join(missing)}"
                )
    return violations


def main(argv: list[str]) -> int:
    sql_dir = Path(argv[1]) if len(argv) > 1 else Path("backend/migrations/sql")
    if not sql_dir.is_dir():
        print(f"FAIL: migrations dir not found: {sql_dir}", file=sys.stderr)
        return 1
    violations = audit(sql_dir)
    violations += audit_revision_ids(sql_dir.parent / "versions")
    if violations:
        print("FAIL: tenant-table RLS guardrail (ADR-0002/0014):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "\nEvery tenant-scoped table (has organization_id) must ENABLE + FORCE RLS and have a "
            "tenant-isolation policy. See RLS_Strategy.md and CONTRIBUTING §6.",
            file=sys.stderr,
        )
        return 1
    print("PASS: all tenant-scoped tables have ENABLE + FORCE RLS + policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
