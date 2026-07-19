#!/usr/bin/env python3
"""Guard C - concrete ToolRegistry implementations may only be constructed in the composition
root (ADR-0016 invariant 2).

A consumer that instantiates a backend has chosen an implementation, which is precisely what the
registry seam exists to prevent: tool resolution would then depend on *which* registry a module
happened to build rather than on the protocol.

import-linter cannot express this. Guard A already forbids consumers from *importing* the
implementations, but the composition root must import them legitimately - so the remaining
question is *who calls the constructor*, which is an AST question, not a dependency question.

Usage: python scripts/check_registry_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset({"InMemoryToolRegistry", "StaticManifestToolRegistry"})
ALLOWED = ("gateway/config/container.py",)


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
        # The implementations themselves are not consumers of each other.
        if rel.endswith(("in_memory_registry.py", "static_manifest_registry.py")):
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
        print("FAIL: registry implementations constructed outside the composition root:", file=sys.stderr)
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may construct a concrete registry. Consumers must receive a "
            "ToolRegistry by injection (ADR-0016 invariant 2).",
            file=sys.stderr,
        )
        return 1
    print("PASS: registry implementations are constructed only in the composition root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
