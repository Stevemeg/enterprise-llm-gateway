#!/usr/bin/env python3
"""Guard: PowerShell scripts must be ASCII-only with a UTF-8 BOM and CRLF endings.

Windows PowerShell 5.1 decodes BOM-less files as Windows-1252. A UTF-8 em dash (E2 80 94) then
becomes 'a EUR "' - and that trailing byte is a curly *quote*, which the parser treats as a string
delimiter. One stray em dash in a comment silently desynchronizes the whole parse, producing
misleading "missing closing '}'" errors far from the real line. This was a real Gate-2 outage.

Usage: python scripts/check_powershell_encoding.py [scripts_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path


def audit(directory: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(directory.glob("*.ps1")):
        raw = path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        body = raw[3:] if has_bom else raw
        if not has_bom:
            problems.append(f"{path.name}: missing UTF-8 BOM (PowerShell 5.1 will assume cp1252)")
        if b"\r\n" not in raw:
            problems.append(f"{path.name}: not CRLF line endings")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path.name}: not valid UTF-8")
            continue
        offenders = sorted({c for c in text if ord(c) > 127})
        if offenders:
            problems.append(f"{path.name}: non-ASCII characters {offenders} - use ASCII equivalents")
    return problems


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent
    problems = audit(directory)
    if problems:
        print("FAIL: PowerShell encoding guard", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("PASS: all .ps1 files are ASCII-only with UTF-8 BOM + CRLF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
