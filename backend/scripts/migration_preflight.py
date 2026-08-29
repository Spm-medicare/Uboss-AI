"""What is about to happen to the database, before it happens.

    uv run python -m scripts.migration_preflight

Reports the current revision, what is pending, whether each pending migration can be reversed,
and which statements in them will take a lock that blocks reads or writes. Exits non-zero when
something needs a human decision, so it can gate a deployment.

It never changes anything. Reading the plan is the whole job.

Why this exists rather than "just run alembic": a migration that cannot be reversed and a
migration that rewrites a table under an exclusive lock are both perfectly ordinary-looking
until they are running in production at the wrong moment. Both facts are in the file; nobody
reads six files before a deploy.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from uboss.core.runtime import run as run_async

BACKEND = Path(__file__).resolve().parent.parent
VERSIONS = BACKEND / "migrations" / "versions"

#: Statements that take a lock blocking reads *and* writes for their duration. On a large table
#: that is an outage, so they belong in a stated maintenance window rather than a routine deploy.
BLOCKING_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"ALTER COLUMN .* SET NOT NULL", "scans the whole table under an ACCESS EXCLUSIVE lock"),
    (r"ALTER COLUMN .* TYPE ", "rewrites the table under an ACCESS EXCLUSIVE lock"),
    (r"\bADD COLUMN\b.*\bNOT NULL\b(?!.*DEFAULT)", "rewrites rows unless a default is supplied"),
    (r"CREATE INDEX(?! CONCURRENTLY)", "blocks writes for the build; CONCURRENTLY does not"),
    (r"CREATE UNIQUE INDEX(?! CONCURRENTLY)", "blocks writes for the build"),
    (r"\bDROP TABLE\b", "destroys data"),
    (r"\bDROP COLUMN\b", "destroys data"),
    (r"\bTRUNCATE\b", "destroys data"),
)


def _url() -> str:
    url = os.environ.get("UBOSS_MIGRATION_DATABASE_URL") or os.environ.get(
        "UBOSS_DATABASE_URL"
    )
    if not url:
        raise SystemExit("Set UBOSS_MIGRATION_DATABASE_URL before running preflight.")
    return url


async def current_revision() -> str | None:
    engine = create_async_engine(_url())
    try:
        async with engine.connect() as connection:
            exists = (
                await connection.execute(
                    text("SELECT to_regclass('public.alembic_version')")
                )
            ).scalar_one()
            if exists is None:
                return None
            return (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
    finally:
        await engine.dispose()


def reversible(path: Path) -> tuple[bool, str]:
    """Whether `downgrade()` actually reverses this migration.

    Three states worth telling apart: it reverses, it deliberately refuses (and says why), or it
    is an empty `pass` — which claims to reverse and does not, and is the dangerous one.
    """
    source = path.read_text(encoding="utf-8")
    body = source.split("def downgrade(", 1)
    if len(body) < 2:
        return False, "no downgrade() at all"
    after = body[1]
    if "raise " in after:
        return False, "refuses on purpose — restore from a backup instead"
    stripped = re.sub(r'""".*?"""', "", after, flags=re.DOTALL)
    statements = [
        line.strip()
        for line in stripped.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    meaningful = [s for s in statements if s not in ("pass", ")", "-> None:")]
    if not meaningful:
        return False, "empty downgrade — claims to reverse but does nothing"
    return True, "reverses"


def blocking_statements(path: Path) -> list[tuple[str, str]]:
    source = path.read_text(encoding="utf-8")
    #  Comments and docstrings mention these operations while explaining them; matching those
    #  would produce a warning on every well-documented migration.
    code = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    code = "\n".join(
        line for line in code.splitlines() if not line.strip().startswith("#")
    )
    found: list[tuple[str, str]] = []
    for pattern, why in BLOCKING_PATTERNS:
        match = re.search(pattern, code, flags=re.IGNORECASE)
        if match:
            found.append((match.group(0).strip()[:70], why))
    return found


def main() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    applied = run_async(current_revision())
    head = scripts.get_current_head()

    print("Migration preflight")
    print(f"  database at : {applied or 'nothing applied yet'}")
    print(f"  head        : {head}")

    #  `iterate_revisions(upper, lower)` walks head-down and stops *before* what is already
    #  applied, which is exactly the pending set. Reversed so they are listed in the order they
    #  will run. With nothing applied yet, "base" means every migration.
    pending = list(
        reversed(list(scripts.iterate_revisions(head, applied or "base")))
    )

    if not pending:
        print("\nNothing pending. The database is at head.")
        return

    print(f"\n{len(pending)} migration(s) will run:\n")

    needs_decision = False
    for revision in pending:
        path = Path(revision.path)
        can_reverse, why = reversible(path)
        blocks = blocking_statements(path)

        print(f"  {revision.revision}  {path.stem}")
        print(f"    reverse : {'yes' if can_reverse else 'NO'} — {why}")
        if not can_reverse:
            needs_decision = True
        for statement, reason in blocks:
            print(f"    lock    : {statement}")
            print(f"              {reason}")
            needs_decision = True
        print()

    if needs_decision:
        print("This needs a decision before it runs:")
        print("  - Take a backup and confirm it restores. An irreversible migration is only")
        print("    reversible through that backup.")
        print("  - A locking statement on a large table is an outage. Schedule it, or split it")
        print("    into an expand step and a contract step deployed separately.")
        print("  - Check the running application version works with BOTH schemas — old")
        print("    instances keep serving while the new one rolls out.")
        sys.exit(1)

    print("Reversible, no blocking statements found. Safe for a routine deploy.")


if __name__ == "__main__":
    main()
