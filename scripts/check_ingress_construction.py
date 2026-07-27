#!/usr/bin/env python3
"""Ingress-protection construction guard (Phase 5 M3).

A rate limiter is shared mutable state whose entire guarantee depends on there being exactly one of
it. A component that constructed its own would count only the traffic that happens to pass through
that component and let the rest through - and, uniquely among this codebase's failure modes, it
would do so *silently and successfully*: every test would pass, every request would be served, and
the only symptom would be a limit that is not a limit. That is the same stakes as the circuit
breaker (a private breaker splits the read from the write) and the deduplicator (a private
coalescer defeats coalescing), so it gets the same two-part enforcement: import-linter proves the
middleware depends only on ``RateLimiterPort``, and this AST guard proves only the composition root
calls the constructor.

## Why a new script rather than extending an existing guard

Checked before writing, against this project's own stated test (see
``check_execution_construction.py``): a guard is *extended* when the new classes are more of what
it already fences (Slice 9 adding ledger classes to the accounting guard), and a new guard is
*added* when the milestone opens a new capability boundary (Slices 7, 8 and 10 each did). Ingress
protection is a new boundary by every available measure - new port, new adapter package
(``adapters/ratelimit``), new middleware, and a position in the request path *above* the router
rather than inside it.

Extending ``check_circuit_breaker_construction.py`` was the closest alternative and was rejected on
a specific ground rather than taste: its subject is provider-health feedback, so a reader asking
"who may build the rate limiter" would have no reason to open it, and its failure message would
have had to describe two unrelated invariants. Broadening it to "shared runtime state" would have
made the message vaguer for both.

Per-CLASS exemption, never per-file (the Slice-15 defect): a limiter module may name its own class
and no other, so a second limiter could not be constructed inside the first's module undetected.

Usage: python scripts/check_ingress_construction.py [src_dir]
Exit 0 = construction confined to the composition root; exit 1 = any other site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGETS = frozenset(
    {
        "InMemoryTokenBucketRateLimiter",
        "RateLimitPolicy",
        # Phase 5 M4 (ADR-0021). Extended rather than given a parallel script: these are more
        # rate limiters, which is exactly the "more of what this guard already fences" test that
        # made Slice 9 correctly extend the accounting guard. The stakes rise rather than change -
        # a component that built its own Redis limiter would also open its own connection pool,
        # invisible to Container.dispose, and would still count only its own traffic.
        "RedisTokenBucketRateLimiter",
        "DegradedRateLimiter",
        "create_redis_client",
    }
)
ALLOWED = ("gateway/config/container.py",)
#: path suffix -> the ONE class that file is allowed to name.
IMPLEMENTATIONS = {
    "ratelimit/in_memory_token_bucket.py": "InMemoryTokenBucketRateLimiter",
    "ratelimit/redis_token_bucket.py": "RedisTokenBucketRateLimiter",
    "ratelimit/degraded.py": "DegradedRateLimiter",
    "ratelimit/client.py": "create_redis_client",
    "ports/rate_limit.py": "RateLimitPolicy",
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
        print(
            "FAIL: ingress rate limiting constructed outside the composition root:",
            file=sys.stderr,
        )
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            f"\nOnly {ALLOWED[0]} may construct a rate limiter, its policy, or the Redis client. "
            "A component that builds its own counts a fraction of the traffic and lets the rest "
            "through, with no error and no test able to see the difference (Phase 5 M3) - and a "
            "privately-built Redis client also leaks a connection pool that Container.dispose "
            "cannot close (Phase 5 M4, ADR-0021).",
            file=sys.stderr,
        )
        return 1
    print("PASS: ingress rate limiting is constructed only in the composition root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
