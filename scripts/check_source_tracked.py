#!/usr/bin/env python3
"""Guard - every production Python source file must actually be IN the repository.

## The defect this exists to prevent

`.gitignore` carried a bare ``secrets/`` rule, intended for a repository-root secrets folder.
Git applies such a pattern at **every** directory depth, so it also matched
``backend/src/gateway/adapters/secrets/`` - a real adapter package that ``config/container.py``
imports on every application start. Those two files were never committed. A fresh clone of the
published repository raised ``ModuleNotFoundError: No module named 'gateway.adapters.secrets'``
and could not construct the application at all.

Nothing caught it, and nothing could have: ruff, mypy, pytest, import-linter and all sixteen
existing guards analyse the **working tree**, where the files were present. The suite was
answering "is the code correct?" when the unanswered question was "is the code *in the
repository*?" - the one failure mode a working copy structurally cannot reveal.

## Why this check and not a dependency analyzer

The failure mode is narrow and Git-shaped: a file exists locally, is imported by tracked code, and
is invisible to `git`. That is answerable with two `git` queries and no import graph, no AST walk
and no packaging heuristics. A general "resolve every import to a file" analyzer would be far
larger, would need to model namespace packages, conditional imports and third-party distributions,
and would still not detect anything this does not. Smaller check, same coverage, far less to get
wrong.

Two rules, both cheap:

1. **No untracked-and-ignored source.** Any ``.py`` under a guarded source root that Git ignores is
   a failure. This is the general form and it would have caught the original defect.
2. **Pinned regression case.** ``gateway/adapters/secrets/env_resolver.py`` must be present in
   tracked content by name. Rule 1 already covers it, but naming it means a future change that
   deletes the file *and* the guard's general reach still fails loudly rather than silently.

Deliberately NOT flagged: files that are merely untracked (a new file mid-development is normal and
`git status` already shows it). Only files Git is configured to **ignore** are failures, because
those never appear in `git status` and so are invisible until someone clones.

Usage: python scripts/check_source_tracked.py [repo_root]
Exit 0 = all production source is in the repository; exit 1 = something is silently excluded.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: Directories whose ``.py`` files are production or test source and must be in the repository.
GUARDED_ROOTS = (
    "backend/src",
    "backend/tests",
    "backend/migrations",
    "scripts",
)

#: Modules whose absence broke the application once. Pinned by path so the regression is named.
PINNED = (
    "backend/src/gateway/adapters/secrets/__init__.py",
    "backend/src/gateway/adapters/secrets/env_resolver.py",
)

#: Caches and virtualenvs live under the guarded roots and are ignored on purpose.
EXEMPT_PARTS = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".uv-cache",
        ".import_linter_cache",
    }
)


def _git(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode not in (0, 1):  # 1 = "nothing matched", normal for check-ignore
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


def _is_exempt(path: Path) -> bool:
    return any(part in EXEMPT_PARTS for part in path.parts)


def audit(root: Path) -> list[str]:
    problems: list[str] = []

    tracked = set(_git(root, "ls-files"))

    # Rule 1 - production source that Git is configured to ignore.
    for guarded in GUARDED_ROOTS:
        base = root / guarded
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if _is_exempt(path.relative_to(root)):
                continue
            rel = path.relative_to(root).as_posix()
            if rel in tracked:
                continue
            ignored = _git(root, "check-ignore", "--", rel)
            if ignored:
                problems.append(
                    f"{rel}: present locally but IGNORED by .gitignore - it will be missing "
                    f"from every clone"
                )

    # Rule 2 - the named regression case.
    for rel in PINNED:
        if rel not in tracked:
            problems.append(f"{rel}: required production module is NOT tracked by Git")

    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():
        print(f"FAIL: not a git repository: {root}", file=sys.stderr)
        return 1

    try:
        problems = audit(root)
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if problems:
        print("FAIL: production source is missing from the repository:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nA working copy is not the repository. Code that only exists locally is absent from "
            "every clone, so the application cannot be built from what was published. Narrow the "
            "offending .gitignore rule (anchor it with a leading '/') and commit the file.",
            file=sys.stderr,
        )
        return 1

    print("PASS: all production source is tracked; nothing is silently excluded by .gitignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
