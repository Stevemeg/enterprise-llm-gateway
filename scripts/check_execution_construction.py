#!/usr/bin/env python3
"""Guard 1 (Slice 10, extended Slice 11) - the execution-orchestration capability may only be
constructed in the composition root: concrete cache adapters, the deduplicator, the inference
coordinator, and the reflective executor with its retry policy (ADR-0016 Slice 10/11).

Same pattern as every construction guard before it (Guards 1/K/L, Slices 6-9): import-linter
answers *dependency* questions, but the composition root must import these legitimately, so the
remaining question is *who calls the constructor* - an AST question. This was classified NEW in
Slice 10, not a reuse of ``check_accounting_construction.py`` or ``check_provider_construction.py``:
caching is a new capability boundary (new port, new adapter package, new application package), not
more classes inside an existing one - the same distinction that made Slice 9 correctly *extend*
``check_accounting_construction.py`` (ledger classes are more accounting) while Slice 7 and 8 each
added their own new file (provider execution and accounting are not one another).

Slice 11 *extends* this script rather than adding a parallel one, applying that same test in the
other direction: reflection orchestrates execution attempts through the coordinator, so it sits
inside this capability's construction boundary, and the invariant ("only the composition root may
build one") is identical in shape. A second script would have duplicated this one's logic under a
different name and inflated the guard count without enforcing anything new.

A second, narrower reason ``RequestDeduplicator`` specifically needs this: it holds process-local
in-flight state that only provides its coalescing guarantee if every caller shares the *same*
instance. A component that constructed its own would silently defeat the guarantee for whatever
requests happen to route through it, with no error and no test able to see the difference from
outside that one component. ``ReflectiveExecutor`` needs it for a related reason: a component that
built its own would also choose its own ``RetryPolicy``, so the deployment-wide attempt bound would
silently stop being deployment-wide.

Usage: python scripts/check_execution_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset(
    {
        "InMemoryResponseCache",
        "SqlResponseCache",
        "RequestDeduplicator",
        "InferenceCoordinator",
        "ReflectiveExecutor",
        "RetryPolicy",
    }
)
ALLOWED = ("gateway/config/container.py",)
IMPLEMENTATIONS = (
    "in_memory_response_cache.py",
    "sql_response_cache.py",
    "deduplicator.py",
    "inference_coordinator.py",
    "reflective_executor.py",
    "retry_policy.py",
)


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
        if rel.endswith(IMPLEMENTATIONS):
            continue
        constructed = _constructions(path)
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
        print(
            "FAIL: cache/dedup/coordination constructed outside the composition root:",
            file=sys.stderr,
        )
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may construct a cache adapter, the deduplicator, or the "
            "inference coordinator. Consumers must receive one by injection (ADR-0016 Slice 10).",
            file=sys.stderr,
        )
        return 1
    print("PASS: cache/dedup/coordination is constructed only in the composition root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
