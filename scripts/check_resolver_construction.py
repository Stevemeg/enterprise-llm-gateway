#!/usr/bin/env python3
"""Guard I - PermissionResolver implementations may only be constructed in the composition root
(ADR-0016 invariant 2, Slice 5).

Fourth occurrence of a construction constraint import-linter cannot express. For RBAC the stakes
are higher than for the earlier seams: a component that constructs its own resolver chooses its
own authorization source, which is indistinguishable from choosing its own answer. Slice 18 raised
them again - ``SqlPermissionResolver`` holds a database handle, so a component that built its own
would also choose its own tenant scoping.

## Slice 18: the exemption is per CLASS, not per FILE

``IMPLEMENTATIONS`` used to be a tuple of filenames, which exempted each of those files from
*every* target rather than from its own class - so ``null_resolver.py`` could have constructed an
``InMemoryPermissionResolver`` and this guard would have said nothing. That is the identical defect
Slice 15 found and fixed in ``check_pipeline_construction.py``; adding a third resolver here is
what made it worth fixing rather than merely noting. A file is now exempt only for the class it
defines.

Usage: python scripts/check_resolver_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset(
    {"InMemoryPermissionResolver", "NullPermissionResolver", "SqlPermissionResolver"}
)
ALLOWED = ("gateway/config/container.py",)
#: path suffix -> the ONE class that file is allowed to name. Never a bare filename list.
IMPLEMENTATIONS = {
    "authorization/in_memory_resolver.py": "InMemoryPermissionResolver",
    "authorization/null_resolver.py": "NullPermissionResolver",
    "authorization/sql_resolver.py": "SqlPermissionResolver",
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
        # Per-class exemption: a resolver module may name ITS OWN class and no other.
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
        print(
            "FAIL: permission resolvers constructed outside the composition root:", file=sys.stderr
        )
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may construct a resolver. A component that picks its own "
            "authorization source has picked its own answer (ADR-0016 invariant 2).",
            file=sys.stderr,
        )
        return 1
    print("PASS: permission resolvers are constructed only in the composition root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
