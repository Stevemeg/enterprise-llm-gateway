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

## Slice 18: PARTITIONS were invisible to this guard, and that was not theoretical

``_CREATE_TABLE`` requires a parenthesised column body, so ``CREATE TABLE child PARTITION OF
parent`` never matched and partitions were never checked. Verified against real PostgreSQL: a
partition does **not** inherit its parent's RLS policies when named directly, and migration 0003's
append-only ``REVOKE`` was applied to the parents only. As ``app_rw`` with tenant B bound, a row
belonging to tenant A was readable *and* updatable via ``audit_event_2026_07`` while the same
statements against ``audit_event`` were correctly refused.

So a partition of a tenant-scoped parent must carry ENABLE + FORCE + a tenant policy of its own,
and a partition of an append-only parent must additionally have UPDATE/DELETE revoked. Both are
recognized either literally or via a ``DO $$ ... pg_inherits ...`` loop naming the parent.

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

#: Immutable logs: the request path may INSERT but never UPDATE/DELETE (FR-113/114, NFR-SEC09).
#: Their partitions must be revoked too - the parent's REVOKE does not reach them.
APPEND_ONLY_PARENTS: frozenset[str] = frozenset({"audit_event", "usage_ledger"})

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
_REVOKE_WRITES = re.compile(
    r"REVOKE\s+UPDATE\s*,\s*DELETE\s+ON\s+\"?(\w+)\"?", re.IGNORECASE
)
_PARTITION_OF = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(?P<child>\w+)\"?\s+PARTITION\s+OF\s+"
    r"\"?(?P<parent>\w+)\"?",
    re.IGNORECASE,
)
_DO_BLOCK = re.compile(r"DO\s*\$\$(?P<body>.*?)END\s*\$\$\s*;", re.IGNORECASE | re.DOTALL)
_INHERITS_PARENTS = re.compile(
    r"pg_inherits.*?relname\s+IN\s*\((?P<parents>[^)]*)\)", re.IGNORECASE | re.DOTALL
)


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


def _inherits_loop_parents(sql: str, *, require_revoke: bool) -> set[str]:
    """Parents whose partitions a ``DO $$ ... pg_inherits ...`` loop hardens in bulk.

    A loop only counts if its own body actually applies the protections - finding ``pg_inherits``
    somewhere in the corpus proves nothing, so the ENABLE/FORCE/POLICY (and optionally REVOKE)
    checks are scoped to the block that names the parents.
    """
    parents: set[str] = set()
    for block in _DO_BLOCK.finditer(sql):
        body = block.group("body")
        if "pg_inherits" not in body.lower():
            continue
        required = [
            r"ENABLE\s+ROW\s+LEVEL\s+SECURITY",
            r"FORCE\s+ROW\s+LEVEL\s+SECURITY",
            r"CREATE\s+POLICY",
        ]
        if require_revoke:
            required.append(r"REVOKE\s+UPDATE\s*,\s*DELETE")
        if not all(re.search(pattern, body, re.IGNORECASE) for pattern in required):
            continue
        match = _INHERITS_PARENTS.search(body)
        if match:
            parents |= {
                p.strip().strip("'\" ") for p in match.group("parents").split(",") if p.strip()
            }
    return parents


def audit_partitions(sql_dir: Path) -> list[str]:
    """Partitions of a tenant-scoped parent need their OWN RLS; partitions of an append-only
    parent need their own REVOKE. Neither is inherited (verified against real PostgreSQL)."""
    files = sorted(sql_dir.glob("*.sql"))
    corpus = "\n".join(f.read_text(encoding="utf-8") for f in files)

    tenant_parents = {
        m.group("name")
        for m in _CREATE_TABLE.finditer(corpus)
        if re.search(r"\borganization_id\b", m.group("body"))
        and m.group("name") not in EXEMPT_TENANT_TABLES
    }
    enabled = set(_ENABLE.findall(corpus))
    forced = set(_FORCE.findall(corpus))
    policied = set(_POLICY_ON.findall(corpus))
    revoked = set(_REVOKE_WRITES.findall(corpus))
    rls_loop_parents = _inherits_loop_parents(corpus, require_revoke=False)
    revoke_loop_parents = _inherits_loop_parents(corpus, require_revoke=True)

    violations: list[str] = []
    for f in files:
        for m in _PARTITION_OF.finditer(f.read_text(encoding="utf-8")):
            child, parent = m.group("child"), m.group("parent")
            if parent not in tenant_parents:
                continue
            if parent not in rls_loop_parents:
                missing = [
                    label
                    for label, seen in (
                        ("ENABLE RLS", enabled),
                        ("FORCE RLS", forced),
                        ("POLICY", policied),
                    )
                    if child not in seen
                ]
                if missing:
                    violations.append(
                        f"{f.name}: partition '{child}' of tenant table '{parent}' is missing: "
                        f"{', '.join(missing)} (a parent's RLS does NOT cover a partition named "
                        f"directly)"
                    )
            if (
                parent in APPEND_ONLY_PARENTS
                and child not in revoked
                and parent not in revoke_loop_parents
            ):
                violations.append(
                    f"{f.name}: partition '{child}' of append-only table '{parent}' is missing: "
                    f"REVOKE UPDATE, DELETE (the parent's revoke does NOT cover it)"
                )
    return violations


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
    violations += audit_partitions(sql_dir)
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
    print("PASS: all tenant-scoped tables and their partitions have ENABLE + FORCE RLS + policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
