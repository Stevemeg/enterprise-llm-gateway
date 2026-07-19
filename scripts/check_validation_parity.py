#!/usr/bin/env python3
"""Guard - validate.sh and validate.ps1 must enforce an identical set of checks.

They drifted once. Every Phase-4 guard was wired into the .ps1 and none into the .sh, so the same
commit passed validation with three architectural invariants unenforced, depending only on which
shell the developer used. Nothing detected it because both scripts still printed success.

Porting the guards fixes today. This fixes tomorrow: parity is now a checked property, so adding
a guard to one script and forgetting the other fails the gate that would otherwise have hidden it.

Two things are compared:

* **guard scripts** - every ``check_*.py`` either script invokes.
* **pipeline steps** - the core commands, matched by signature rather than by exact text, because
  the two shells legitimately differ in quoting, path separators and variable syntax. Only the
  *presence* of a step is comparable across shells; its spelling is not.

Deliberately NOT compared: wording, ordering, and the three-state terminal logic, which cannot be
expressed identically in PowerShell and bash. Those remain review's responsibility, and this
guard's limits are worth stating plainly - it proves both scripts run the same checks, not that
they behave identically when those checks fail.

Usage: python scripts/check_validation_parity.py [scripts_dir]
Exit 0 = parity; exit 1 = drift.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

GUARD_RE = re.compile(r"check_[a-z0-9_]+\.py")

# name -> regex that must match somewhere in each script.
PIPELINE_STEPS: dict[str, re.Pattern[str]] = {
    "uv sync": re.compile(r"\buv sync\b"),
    "ruff check": re.compile(r"ruff check\b"),
    "ruff format --check": re.compile(r"ruff format --check\b"),
    "mypy (strict)": re.compile(r"\bmypy src tests\b"),
    "import-linter": re.compile(r"\blint-imports\b"),
    "alembic upgrade head": re.compile(r"alembic upgrade head\b"),
    "pytest + coverage": re.compile(r"pytest --cov=src/gateway\b"),
    "INCOMPLETE terminal state": re.compile(r"INCOMPLETE - Gate 2 did NOT run"),
    "skipped-count check": re.compile(r"test\(s\) were skipped"),
}


def _read(path: Path) -> str:
    # The .ps1 carries a UTF-8 BOM by design (see check_powershell_encoding.py).
    return path.read_text(encoding="utf-8-sig")


def audit(scripts_dir: Path) -> list[str]:
    sh, ps1 = scripts_dir / "validate.sh", scripts_dir / "validate.ps1"
    problems: list[str] = []
    for path in (sh, ps1):
        if not path.is_file():
            problems.append(f"missing validation script: {path.name}")
    if problems:
        return problems

    sh_text, ps1_text = _read(sh), _read(ps1)

    sh_guards = set(GUARD_RE.findall(sh_text))
    ps1_guards = set(GUARD_RE.findall(ps1_text))
    for guard in sorted(ps1_guards - sh_guards):
        problems.append(f"{guard}: in validate.ps1 but NOT validate.sh")
    for guard in sorted(sh_guards - ps1_guards):
        problems.append(f"{guard}: in validate.sh but NOT validate.ps1")

    for name, pattern in PIPELINE_STEPS.items():
        in_sh, in_ps1 = bool(pattern.search(sh_text)), bool(pattern.search(ps1_text))
        if in_sh and not in_ps1:
            problems.append(f"step '{name}': in validate.sh but NOT validate.ps1")
        elif in_ps1 and not in_sh:
            problems.append(f"step '{name}': in validate.ps1 but NOT validate.sh")
        elif not in_sh and not in_ps1:
            problems.append(f"step '{name}': missing from BOTH scripts")

    return problems


def main(argv: list[str]) -> int:
    scripts_dir = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent
    problems = audit(scripts_dir)
    if problems:
        print("FAIL: validate.sh and validate.ps1 have drifted:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nBoth entry points must enforce the same checks. A guard present in one and absent "
            "from the other is half-enforced, and the passing script hides it.",
            file=sys.stderr,
        )
        return 1
    print("PASS: validate.sh and validate.ps1 enforce identical checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
