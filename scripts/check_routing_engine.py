#!/usr/bin/env python3
"""Guards K and L - routing orchestration boundaries (ADR-0016 Slice 6).

Two construction/usage questions import-linter cannot answer, because the modules involved may
legitimately import each other and the constraint is about *who calls what*:

* **Guard K** - ``RoutingEngine`` implementations may only be constructed in the composition root.
  A component that builds its own engine has chosen its own routing policy.
* **Guard L** - ``AgentRuntime`` may only be reached from the routing engine (plus the composition
  root, which wires it). Two application callers of the runtime means two orchestrators, and the
  second one inevitably grows its own rules. This is the guard that keeps Slice 6's refactor from
  silently reverting.

Usage: python scripts/check_routing_engine.py [src_dir]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ENGINES = frozenset({"AgentOrchestratedRoutingEngine"})
ENGINE_ALLOWED = ("gateway/config/container.py",)
ENGINE_IMPL = ("application/routing/engine.py",)

RUNTIME = "AgentRuntime"
RUNTIME_ALLOWED = (
    "gateway/application/routing/engine.py",
    "gateway/config/container.py",
    "gateway/application/agents/runtime.py",
)


def _names(path: Path) -> set[str]:
    """Every identifier referenced by name in the module (calls, annotations, imports)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names)
    return found


def _constructions(path: Path, targets: frozenset[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in targets:
            found.add(func.id)
        elif isinstance(func, ast.Attribute) and func.attr in targets:
            found.add(func.attr)
    return found


def audit(src: Path) -> list[str]:
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src.parent).as_posix()

        if not any(rel.endswith(a) for a in ENGINE_ALLOWED + ENGINE_IMPL):
            built = _constructions(path, ENGINES)
            if built:
                offenders.append(
                    f"[K] {rel}: constructs {', '.join(sorted(built))} outside the composition root"
                )

        if not any(rel.endswith(a) for a in RUNTIME_ALLOWED) and RUNTIME in _names(path):
            offenders.append(f"[L] {rel}: references {RUNTIME}; only the routing engine may")
    return offenders


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else Path("src/gateway")
    if not src.is_dir():
        print(f"FAIL: source dir not found: {src}", file=sys.stderr)
        return 1
    offenders = audit(src)
    if offenders:
        print("FAIL: routing orchestration boundary violated:", file=sys.stderr)
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            "\nRoutingEngine is constructed only by the composition root, and is the only "
            "application caller of AgentRuntime (ADR-0016 invariants 2-3).",
            file=sys.stderr,
        )
        return 1
    print("PASS: routing engine construction and AgentRuntime access are confined.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
