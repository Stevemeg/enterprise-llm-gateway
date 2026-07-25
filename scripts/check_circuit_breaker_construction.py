#!/usr/bin/env python3
"""Circuit-breaker construction guard (ADR-0016 Slice 20).

A circuit breaker holds shared mutable state that two components must agree on: the HealthAgent
reads it at routing time, and the execution coordinator writes call outcomes to it at settlement
time. If any component constructed its OWN breaker, the read and the write would land on different
state and circuit breaking would silently stop working - a healthy-looking system whose breakers
never see the failures they exist to catch. This is the same stakes as the permission resolver (a
component that builds its own resolver picks its own answer), so it gets the same enforcement:
import-linter proves consumers depend only on the port; this AST guard proves only the composition
root calls the constructor.

Per-CLASS exemption, never per-file (the Slice-15 defect): a breaker module may name its own class
and no other, so a second in-memory breaker could not be constructed inside the first's module
undetected.

Usage: python scripts/check_circuit_breaker_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset({"InMemoryCircuitBreaker"})
ALLOWED = ("gateway/config/container.py",)
#: path suffix -> the ONE class that file is allowed to name.
IMPLEMENTATIONS = {
    "health/in_memory_circuit_breaker.py": "InMemoryCircuitBreaker",
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
        print("FAIL: circuit breakers constructed outside the composition root:", file=sys.stderr)
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may construct a circuit breaker. A component that builds its own "
            "splits the routing-time read from the execution-time write (ADR-0016 Slice 20).",
            file=sys.stderr,
        )
        return 1
    print("PASS: circuit breakers are constructed only in the composition root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
