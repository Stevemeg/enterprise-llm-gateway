#!/usr/bin/env python3
"""Guard (Slice 16) - metric labels must stay bounded and non-sensitive (NFR-SEC03).

``observability/metrics.py`` has stated since the authentication milestone that "label values
must be low-cardinality and never sensitive - drawn from a fixed vocabulary, never from exception
text, user input, tokens, or secrets". Until this slice that was a **comment**. Slice 16 put the
whole request path behind those labels, which is exactly when a written-down rule stops being
sufficient: a tenant id used as a label is a cardinality explosion *and* a data leak, and neither
fails a test that only asserts a counter incremented.

Three checks, each enforcing a different half of the property:

1. **Declared label names** - every ``labelnames=(...)`` in ``metrics.py`` must be drawn from
   ``ALLOWED_LABEL_NAMES``. A new label is therefore a deliberate edit to this guard, reviewed on
   purpose, rather than something that appears because it was convenient at a call site.
2. **No direct ``.labels()`` on a request-path metric outside the metrics module** - recording
   goes through the ``record_*`` functions, which bound their values at runtime. A direct
   ``.labels()`` call elsewhere bypasses that bounding entirely.

   The check is bound to the **named request-path metrics** (``GUARDED_METRICS``) rather than to
   every ``.labels()`` call anywhere, and rather than to an exempt-file list. Two reasons. First,
   the three auth-era metrics predate the recorder pattern and label themselves from module-level
   ``REASON_*`` constants - an adequate discipline for a fixed three-value vocabulary, and
   rewriting approved prior-slice code to satisfy a newer convention is churn, not enforcement.
   Second, Slice 15 established the hazard of *file*-scoped exemptions: exempting a file exempts
   it from everything, including checks it should still fail. Naming the protected objects keeps
   the exemption at the granularity of the thing actually being protected.
3. **No forbidden identifier flows into a recorder** - a ``record_*`` call may not be passed
   ``organization_id``, ``principal_id``, ``correlation_id``, prompt/completion content, or an
   exception, by name or by attribute.

## What this guard does NOT prove (stated rather than implied)

Check 3 is **name-based and therefore partially heuristic**. It catches the realistic mistakes -
passing an identifier that is called what it is - but it cannot see through an alias
(``x = organization_id; record_provider_call(provider=x, ...)``) or a computed string. The
guarantee that actually holds at runtime comes from the code, not from this script: every
``record_*`` function validates its value against a frozen allowlist and substitutes ``unknown``,
so an unbounded value cannot mint a new time series even if it reaches the recorder.

Three labels are **configuration-bounded rather than enum-bounded** - ``stage``, ``evaluator`` and
``provider``. None is request-supplied, but their bound is the deployment's composition root and
provider catalog, not a Python enum. That distinction is recorded here and in the evidence log
instead of being papered over.

Usage: python scripts/check_metric_cardinality.py [src_dir]
Exit 0 = labels bounded and non-sensitive; exit 1 = any violation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

METRICS_MODULE = "gateway/observability/metrics.py"

#: The complete set of label names any metric may declare. Extending this is a deliberate act.
ALLOWED_LABEL_NAMES = frozenset(
    {
        "reason",  # auth-era: fixed failure vocabulary
        "method",  # auth-era: AuthenticationMethod
        "result",  # auth-era: AuthenticationDecision; Slice 16: cache hit/miss
        "stage",  # Slice 16: composition-root-bounded stage chain
        "action",  # Slice 16: StageAction
        "outcome",  # Slice 16: several closed outcome enums
        "provider",  # Slice 16: catalog-bounded provider name
        "verdict",  # Slice 16: RetryVerdict
        "evaluator",  # Slice 16: wired evaluator chain
        "control",  # Phase 5 M3: which ingress control decided; two values fixed in metrics.py
    }
)

#: Substrings that must never appear in a label NAME. Tenant/principal/request identity and
#: free text are the four ways a metric turns into a leak or an unbounded series.
FORBIDDEN_LABEL_SUBSTRINGS = (
    "organization",
    "org_id",
    "tenant",
    "principal",
    "user",
    "correlation",
    "request_id",
    "prompt",
    "completion",
    "content",
    "message",
    "error_text",
    "token",
    "secret",
    "key",
    "email",
    "ip",
    "path",
    "url",
)

#: Identifiers that must never be passed to a ``record_*`` function, by name or attribute.
FORBIDDEN_ARGUMENT_NAMES = frozenset(
    {
        "organization_id",
        "principal_id",
        "correlation_id",
        "request_id",
        "tenant_id",
        "user_id",
        "prompt",
        "completion",
        "content",
        "payload",
        "error",
        "detail",
        "message",
        "exc",
        "exception",
        "token",
        "secret",
        "api_key",
        "email",
    }
)

_METRIC_FACTORIES = frozenset({"Counter", "Histogram", "Gauge", "Summary", "Info", "Enum"})

#: The Slice-16 request-path metrics. These must only ever be labelled from inside
#: ``metrics.py``'s ``record_*`` functions, which bound every value at runtime.
GUARDED_METRICS = frozenset(
    {
        "admission_stage_decisions",
        "served_requests",
        "served_request_duration_seconds",
        "inference_attempts",
        "cache_lookups",
        "provider_calls",
        "provider_call_duration_seconds",
        "reflection_attempts",
        "routing_decisions",
        "evaluations",
        "budget_reservations",
        "provider_circuit_transitions",  # Slice 20
        "ingress_decisions",  # Phase 5 M3
    }
)


def _factory_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _declared_labels(tree: ast.AST) -> list[tuple[int, str]]:
    """Every label name declared by a metric constructor, with its line number."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _factory_name(node) not in _METRIC_FACTORIES:
            continue
        for keyword in node.keywords:
            if keyword.arg != "labelnames":
                continue
            if isinstance(keyword.value, (ast.Tuple, ast.List)):
                for element in keyword.value.elts:
                    if isinstance(element, ast.Constant) and isinstance(element.value, str):
                        found.append((node.lineno, element.value))
    return found


def _guarded_labels_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """Lines labelling a request-path metric directly - the runtime-bounding bypass."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "labels":
            continue
        receiver = node.func.value
        name = (
            receiver.id
            if isinstance(receiver, ast.Name)
            else receiver.attr
            if isinstance(receiver, ast.Attribute)
            else None
        )
        if name in GUARDED_METRICS:
            found.append((node.lineno, str(name)))
    return found


def _forbidden_recorder_arguments(tree: ast.AST) -> list[tuple[int, str]]:
    """Forbidden identifiers passed into a ``record_*`` call, by name or attribute."""
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _factory_name(node)
        if name is None or not name.startswith("record_"):
            continue
        for value in [*node.args, *(kw.value for kw in node.keywords)]:
            for inner in ast.walk(value):
                if isinstance(inner, ast.Name) and inner.id in FORBIDDEN_ARGUMENT_NAMES:
                    offenders.append((node.lineno, inner.id))
                elif isinstance(inner, ast.Attribute) and inner.attr in FORBIDDEN_ARGUMENT_NAMES:
                    offenders.append((node.lineno, inner.attr))
    return offenders


def audit(src: Path) -> list[str]:
    offenders: list[str] = []
    metrics_path: Path | None = None

    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src.parent).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        if rel.endswith(METRICS_MODULE):
            metrics_path = path
            for line, label in _declared_labels(tree):
                if label not in ALLOWED_LABEL_NAMES:
                    offenders.append(
                        f"{rel}:{line}: label {label!r} is not in ALLOWED_LABEL_NAMES"
                    )
                lowered = label.lower()
                for banned in FORBIDDEN_LABEL_SUBSTRINGS:
                    if banned in lowered:
                        offenders.append(
                            f"{rel}:{line}: label {label!r} contains forbidden substring "
                            f"{banned!r} (NFR-SEC03)"
                        )
        else:
            for line, metric in _guarded_labels_calls(tree):
                offenders.append(
                    f"{rel}:{line}: labels {metric!r} directly; use its record_* function so the "
                    "value is bounded at runtime"
                )

        for line, argument in _forbidden_recorder_arguments(tree):
            offenders.append(
                f"{rel}:{line}: passes {argument!r} into a record_* call (NFR-SEC03)"
            )

    if metrics_path is None:
        offenders.append(f"FAIL: {METRICS_MODULE} not found under {src}")
    return offenders


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else Path("src/gateway")
    if not src.is_dir():
        print(f"FAIL: source dir not found: {src}", file=sys.stderr)
        return 1
    offenders = audit(src)
    if offenders:
        print("FAIL: metric cardinality/sensitivity violation:", file=sys.stderr)
        for offender in offenders:
            print(f"  - {offender}", file=sys.stderr)
        print(
            "\nMetric labels must be bounded and non-sensitive: declare label names in "
            "ALLOWED_LABEL_NAMES, record through record_* functions, and never label with tenant, "
            "principal, request identity or free text (NFR-SEC03).",
            file=sys.stderr,
        )
        return 1
    print("PASS: metric labels are bounded and carry no sensitive identifiers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
