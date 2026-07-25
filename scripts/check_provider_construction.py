#!/usr/bin/env python3
"""Guard 1 - concrete ProviderClient implementations, ProviderExecutor and ProviderCatalog
implementations may only be constructed in the composition root (Slice 7, extended Slice 19).

Same pattern as Guards C, F and I: import-linter answers *dependency* questions, but the
composition root must import these legitimately, so the remaining question is *who calls the
constructor* - an AST question. A component that builds its own executor has chosen its own
provider client, which is exactly what the seam exists to prevent.

## Slice 19 raised the stakes twice over

``OpenAiCompatibleProviderClient`` holds real endpoints and real credentials, so a component that
built its own would also choose its own provider account. And the **catalog** joined the guard for
the first time: a component that builds its own ``ProviderCatalog`` chooses its own set of routable
providers, which is choosing the routing outcome by another route.

## Slice 19: the exemption is per CLASS, not per FILE

``IMPLEMENTATIONS`` used to be a tuple of filenames, which exempted each of those files from
*every* target rather than from its own class - so ``in_memory_client.py`` could have constructed a
``FakeProviderClient`` and this guard would have said nothing. That is the identical defect Slice 15
found in ``check_pipeline_construction.py`` and Slice 18 fixed in the resolver guard. A file is now
exempt only for the class it defines.

Usage: python scripts/check_provider_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset(
    {
        "InMemoryProviderClient",
        "FakeProviderClient",
        "OpenAiCompatibleProviderClient",
        "ProviderExecutor",
        "InMemoryProviderCatalog",
        "SqlProviderCatalog",
    }
)
ALLOWED = ("gateway/config/container.py",)
#: path suffix -> the ONE class that file is allowed to name. Never a bare filename list.
IMPLEMENTATIONS = {
    "providers/in_memory_client.py": "InMemoryProviderClient",
    "providers/fake_client.py": "FakeProviderClient",
    "providers/openai_compatible_client.py": "OpenAiCompatibleProviderClient",
    "providers/provider_executor.py": "ProviderExecutor",
    "routing/catalog.py": "InMemoryProviderCatalog",
    "catalog/sql_provider_catalog.py": "SqlProviderCatalog",
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
        print("FAIL: provider execution constructed outside the composition root:", file=sys.stderr)
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may construct a ProviderClient or ProviderExecutor. Consumers "
            "must receive one by injection (ADR-0016 Slice 7).",
            file=sys.stderr,
        )
        return 1
    print("PASS: provider execution is constructed only in the composition root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
