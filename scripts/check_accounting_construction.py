#!/usr/bin/env python3
"""Guard 1 - concrete pricing/budget/ledger adapters and the accounting orchestrators may only be
constructed in the composition root (ADR-0016 Slice 8, extended Slice 9/ADR-0017).

Same pattern as the provider-execution construction guard (Slice 7) and every construction guard
before it: import-linter answers *dependency* questions, but the composition root must import
these legitimately, so the remaining question is *who calls the constructor* - an AST question.
A component that builds its own pricing table, budget store, or budget ledger has chosen its own
money, which is exactly what these seams exist to prevent. Reused unchanged as-a-pattern for
Slice 9's ledger classes rather than writing a new guard script (nothing about "who may construct
this" differs from Slice 8's shape).

Usage: python scripts/check_accounting_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset(
    {
        "StaticPriceTable",
        "SqlPriceTable",
        "CostAccountant",
        "SqlBudgetLedger",
        "InMemoryBudgetLedger",
        "ReservationService",
        "ReservationReconciler",
    }
)
ALLOWED = ("gateway/config/container.py",)
#: path suffix -> the ONE class that file is allowed to name. Per-class, never a bare filename
#: list: Slice 19 added SqlPriceTable, and a per-file exemption would have let static_price_table.py
#: construct it undetected - the defect Slices 15/18 fixed in the pipeline and resolver guards.
IMPLEMENTATIONS = {
    "pricing/static_price_table.py": "StaticPriceTable",
    "pricing/sql_price_table.py": "SqlPriceTable",
    "accounting/cost_accountant.py": "CostAccountant",
    "ledger/sql_budget_ledger.py": "SqlBudgetLedger",
    "ledger/in_memory_budget_ledger.py": "InMemoryBudgetLedger",
    "accounting/reservation_service.py": "ReservationService",
    "accounting/reservation_reconciler.py": "ReservationReconciler",
}


def _constructions(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in TARGETS:
            found.add(func.id)
        elif isinstance(func, ast.Attribute) and func.attr in TARGETS:
            found.add(func.attr)
    return found


def audit(src: Path) -> list[str]:
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src.parent).as_posix()
        if any(rel.endswith(allowed) for allowed in ALLOWED):
            continue
        constructed = _constructions(path)
        # Per-class exemption: a module may name ITS OWN class and no other.
        for suffix, own_class in IMPLEMENTATIONS.items():
            if rel.endswith(suffix):
                constructed.discard(own_class)
        if constructed:
            offenders.append(f"{rel}: constructs {', '.join(sorted(constructed))}")
    return offenders


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else Path("src/gateway")
    if not src.is_dir():
        print(f"FAIL: source dir not found: {src}", file=sys.stderr)
        return 1
    offenders = audit(src)
    if offenders:
        print("FAIL: accounting constructed outside the composition root:", file=sys.stderr)
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may construct a pricing/budget adapter or an accounting "
            "orchestrator. Consumers must receive one by injection (ADR-0016 Slice 8).",
            file=sys.stderr,
        )
        return 1
    print("PASS: accounting is constructed only in the composition root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
