#!/usr/bin/env python3
"""Guard 1 - concrete ProviderClient implementations and ProviderExecutor may only be
constructed in the composition root (ADR-0016 Slice 7).

Same pattern as Guards C, F and I: import-linter answers *dependency* questions, but the
composition root must import these legitimately, so the remaining question is *who calls the
constructor* - an AST question. A component that builds its own executor has chosen its own
provider client, which is exactly what the seam exists to prevent.

Usage: python scripts/check_provider_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset({"InMemoryProviderClient", "FakeProviderClient", "ProviderExecutor"})
ALLOWED = ("gateway/config/container.py",)
IMPLEMENTATIONS = ("in_memory_client.py", "fake_client.py", "provider_executor.py")


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
