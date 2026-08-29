"""Delete expired idempotency records.

    uv run python -m scripts.cleanup_idempotency

An idempotency record exists so a retry within the retry window replays instead of repeating.
After that window it is dead weight, and the table is written to by every mutating command — so
without this it grows without bound and eventually the index that makes lookups fast stops
fitting anywhere useful.

**Run this on a schedule.** Hourly is ample: the default retention is 24 hours, so nothing here
is time-critical, and a run that is missed for a day costs a slightly larger table and nothing
else.

Temporal takes this over in Gate 7, when there is a scheduler. Until then it is cron, or a
person. Saying so is better than leaving the table to grow while assuming someone noticed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from uboss.core.idempotency import delete_expired_for_tenant
from uboss.core.runtime import run as run_async
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.audit.models import IdempotencyRecord
from uboss.modules.tenancy.models import Tenant


def _owner_url() -> str:
    url = os.environ.get("UBOSS_MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit(
            "Set UBOSS_MIGRATION_DATABASE_URL. This runs across tenants, which an ordinary "
            "request never does."
        )
    return url


async def main_async() -> None:
    engine = create_async_engine(_owner_url())
    now = datetime.now(UTC)
    removed_total = 0

    try:
        async with build_sessionmaker(engine)() as session:
            tenants = (await session.execute(select(Tenant))).scalars().all()

            for tenant in tenants:
                #  Bound and flushed per tenant. The delete is tenant-scoped anyway, but running
                #  it inside the boundary means this script obeys the same rules as the API
                #  rather than relying on being the owner.
                async with tenant_scope(session, tenant.id):
                    before = (
                        await session.execute(
                            select(func.count())
                            .select_from(IdempotencyRecord)
                            .where(IdempotencyRecord.tenant_id == tenant.id)
                        )
                    ).scalar_one()

                    await delete_expired_for_tenant(session, tenant_id=tenant.id, now=now)

                    after = (
                        await session.execute(
                            select(func.count())
                            .select_from(IdempotencyRecord)
                            .where(IdempotencyRecord.tenant_id == tenant.id)
                        )
                    ).scalar_one()

                removed = before - after
                removed_total += removed
                if removed:
                    print(f"  {tenant.slug}: {removed} expired record(s) removed")

            await session.commit()

        print(f"Removed {removed_total} expired idempotency record(s).")
    finally:
        await engine.dispose()


def main() -> None:
    run_async(main_async())


if __name__ == "__main__":
    main()
