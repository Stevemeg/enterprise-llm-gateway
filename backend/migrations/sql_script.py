"""Execute multi-statement SQL scripts under asyncpg (Migration_Strategy.md).

asyncpg sends every statement through the extended query protocol, which permits exactly one
command per prepared statement. Our migrations apply canonical DDL files containing many
statements, so ``op.execute(file_contents)`` fails with:

    asyncpg.exceptions.PostgresSyntaxError: cannot insert multiple commands into a prepared
    statement

Rather than switch migrations to a synchronous driver (a second driver to install, configure and
keep in sync), we split the script into individual statements and execute them in order, inside
the migration's existing transaction so failure still rolls back atomically.

The splitter is **dollar-quote aware**: our DDL uses ``DO $$ ... END $$;`` blocks and
``format($p$ ... $p$, t)`` bodies whose internal semicolons must NOT be treated as terminators.
It also skips semicolons inside single-quoted literals and line/block comments.
"""

from __future__ import annotations

import re

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def split_sql_statements(script: str) -> list[str]:
    """Split ``script`` into executable statements on top-level semicolons."""
    statements: list[str] = []
    buffer: list[str] = []
    i = 0
    length = len(script)
    in_single_quote = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None

    while i < length:
        char = script[i]
        pair = script[i : i + 2]

        if in_line_comment:
            buffer.append(char)
            if char == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            buffer.append(char)
            if pair == "*/":
                buffer.append(script[i + 1])
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if dollar_tag is not None:
            if script.startswith(dollar_tag, i):
                buffer.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buffer.append(char)
            i += 1
            continue

        if in_single_quote:
            buffer.append(char)
            if char == "'":
                # '' is an escaped quote, not a terminator.
                if script[i + 1 : i + 2] == "'":
                    buffer.append("'")
                    i += 2
                    continue
                in_single_quote = False
            i += 1
            continue

        # --- default state ---
        if pair == "--":
            in_line_comment = True
            buffer.append(pair)
            i += 2
            continue
        if pair == "/*":
            in_block_comment = True
            buffer.append(pair)
            i += 2
            continue
        if char == "'":
            in_single_quote = True
            buffer.append(char)
            i += 1
            continue
        match = _DOLLAR_TAG.match(script, i)
        if match:
            dollar_tag = match.group(0)
            buffer.append(dollar_tag)
            i += len(dollar_tag)
            continue
        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            i += 1
            continue

        buffer.append(char)
        i += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    # Drop comment-only fragments, which asyncpg rejects as empty queries.
    return [s for s in statements if not _is_comment_only(s)]


def _is_comment_only(statement: str) -> bool:
    stripped = re.sub(r"/\*.*?\*/", "", statement, flags=re.DOTALL)
    lines = [ln.strip() for ln in stripped.splitlines()]
    return all((not ln) or ln.startswith("--") for ln in lines)


def execute_sql_script(op: object, script: str) -> None:
    """Execute every statement in ``script`` through Alembic's bound connection."""
    from alembic import op as alembic_op  # local import keeps this module import-light

    target = op if hasattr(op, "execute") else alembic_op
    for statement in split_sql_statements(script):
        target.execute(statement)  # type: ignore[attr-defined]
