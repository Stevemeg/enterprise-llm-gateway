#!/usr/bin/env python3
"""Guard 1 (Slice 14, extended Slice 15) - the request path's composition may only be assembled in
the composition root: the ``RequestPipeline`` itself and the ``InferenceService`` that runs it
(ADR-0016 invariant 5).

A new file rather than an extension of ``check_execution_construction.py``, applying that script's
own stated test: it extends when a slice adds more classes inside a boundary it already fences
(Slice 11's reflection, Slice 12's evaluation - both sit on the execution path), and a new file
when a slice opens a new boundary (Slice 7 provider execution, Slice 8 accounting, Slice 10
caching). Request **admission** is not request **execution**: different package
(``application/pipeline``), different question, and it runs before anything the execution guard
fences even starts.

## Why this one matters more than the construction guards before it

Every earlier guard confines a component that chooses *how* something is done. This one confines
the component that chooses **which controls run at all, and in what order**. A component that
built its own ``RequestPipeline`` would select its own stage chain - one missing the authorization
stage, or with routing ahead of policy - and every request through it would be admitted by a
different set of rules than the deployment believes it enforces. Nothing else would fail: it would
return an ``AdmissionOutcome`` that looks exactly as authoritative as the real one.

Slice 15 *extends* this script rather than adding a parallel one, applying the same test in the
other direction: ``InferenceService`` chooses **which pipeline guards a request** and which
executor and evaluator chain follow it, so it holds the identical authority one step further out.
A component that built its own would run a request through a pipeline of its own choosing - the
exact failure this guard exists to prevent, arrived at by a different route. A second script would
have duplicated this one's logic under a different name.

## What is deliberately NOT confined, and why

The stages themselves (``AuthorizationStage``, ``PolicyStage``, ``AgentRoutingStage``). A stage
holds no authority over whether it is consulted - constructing one decides nothing, because only
membership in the pipeline makes a control run. Confining them too would inflate the guard count
without enforcing anything the pipeline constraint does not already cover, and the resolver a
stage depends on is separately confined by Guard I. Recorded as NOT APPLICABLE in the evidence log
rather than guarded for symmetry.

Usage: python scripts/check_pipeline_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset({"RequestPipeline", "InferenceService"})
ALLOWED = ("gateway/config/container.py",)

#: A defining module is exempt for **its own class only**, never for the whole target set.
#:
#: Every other construction guard in this repo uses a flat list of exempt filenames, which exempts
#: each implementation file from *all* targets at once. That is harmless while a guard has one
#: target, and stops being harmless the moment it has two: extending this guard with
#: ``InferenceService`` in Slice 15 silently gave ``inference_service.py`` permission to construct a
#: ``RequestPipeline`` as well - it could have assembled its own admission chain with the guard
#: still reporting PASS. The deliberate-violation proof caught it (the extension's re-proof of the
#: Slice-14 target came back exit 0), which is the entire reason every guard is re-proven rather
#: than assumed to still work. The flat-list weakness is recorded against the other four guards in
#: the evidence log; each is single-purpose today, so none is currently exposed.
IMPLEMENTATIONS = {
    "application/pipeline/runner.py": "RequestPipeline",
    "application/serving/inference_service.py": "InferenceService",
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
        print("FAIL: request path composed outside the composition root:", file=sys.stderr)
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may assemble the admission chain or the service that runs it. "
            "A component that builds its own chooses which controls guard a request, and in what "
            "order (ADR-0016 invariant 5).",
            file=sys.stderr,
        )
        return 1
    print("PASS: the request path is composed only in the composition root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
