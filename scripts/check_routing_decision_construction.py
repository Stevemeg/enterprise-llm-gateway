#!/usr/bin/env python3
"""Guard 1 - RoutingDecision may only be instantiated by AgentRuntime (ADR-0016 invariant 3).

Centralising construction is what makes explainability structural: if any module could build a
RoutingDecision, one could be produced without a reasoning trace and the invariant would rest on
convention again.

import-linter cannot express this. It checks module *dependencies*, and legitimate consumers must
import RoutingDecision to type-annotate and read it. The forbidden thing is *instantiation*, which
is a different question needing a different tool - hence this scan.

Usage: python scripts/check_routing_decision_construction.py [src_dir]
Exit 0 = one construction site; exit 1 = any other site found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGET = "RoutingDecision"
ALLOWED = ("gateway/application/agents/runtime.py",)


def _constructs(path: Path) -> bool:
    """True if this module calls ``RoutingDecision(...)``. AST-based, so comments and strings
    mentioning the name do not produce false positives."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == TARGET:
                return True
            if isinstance(func, ast.Attribute) and func.attr == TARGET:
                return True
    return False


def audit(src: Path) -> list[str]:
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src.parent).as_posix()
        if any(rel.endswith(allowed) for allowed in ALLOWED):
            continue
        if _constructs(path):
            offenders.append(rel)
    return offenders


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else Path("src/gateway")
    if not src.is_dir():
        print(f"FAIL: source dir not found: {src}", file=sys.stderr)
        return 1
    offenders = audit(src)
    if offenders:
        print(f"FAIL: {TARGET} constructed outside AgentRuntime:", file=sys.stderr)
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may construct {TARGET}. Obtain decisions from AgentRuntime "
            "instead of building the record directly (ADR-0016 invariant 3).",
            file=sys.stderr,
        )
        return 1
    print(f"PASS: {TARGET} is constructed only by AgentRuntime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
