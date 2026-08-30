"""Import the approved Skill Catalogue into the registry.

    uv run python scripts/import_skill_catalogue.py <path-to-workbook.xlsx>

Runs as the **owner**, because the catalogue is shared reference data the application role can
read and cannot write — the boundary migration 0019 set up. Idempotent: re-run it whenever the
workbook is corrected.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from uboss.core.runtime import run
from uboss.db.base import build_sessionmaker
from uboss.db.registry import import_all
from uboss.modules.agents.seed import catalogue_counts, import_catalogue


def _owner_url() -> str:
    """The owner connection, the same way `migrations/env.py` resolves it.

    Read from the environment rather than from settings, because settings hold the *application*
    role — which by design cannot write the catalogue. Falling back to it would produce a
    permission error rather than a useful message.
    """
    url = os.environ.get("UBOSS_MIGRATION_DATABASE_URL") or os.environ.get(
        "UBOSS_DATABASE_URL"
    )
    if not url:
        raise SystemExit(
            "Set UBOSS_MIGRATION_DATABASE_URL (preferred) or UBOSS_DATABASE_URL first. The "
            "catalogue is written by the owner role, not the application one."
        )
    return url


async def main(path: Path) -> int:
    #  Every model registered, or SQLAlchemy cannot resolve the foreign keys between modules.
    import_all()
    engine = create_async_engine(_owner_url(), pool_pre_ping=True)
    try:
        async with build_sessionmaker(engine)() as session:
            report = await import_catalogue(session, path)
            await session.commit()

            counts = await catalogue_counts(session)

        print(f"archetypes           {report.archetypes}")
        print(f"exactness gates      {report.gates}")
        print(f"skills               {report.total_skills}"
              f"  ({report.skills_created} new, {report.skills_updated} updated)")
        print(f"rules                {report.total_rules}"
              f"  ({report.rules_created} new, {report.rules_updated} updated)")
        print(f"registry now holds   {counts}")

        if report.skipped:
            #  Printed in full rather than counted. A skipped row means the sheet and the
            #  importer disagree, and somebody has to decide which is right.
            print(f"\n{len(report.skipped)} rows were not imported:")
            for line in report.skipped:
                print(f"  - {line}")
            return 1
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(run(main(Path(sys.argv[1]))))
