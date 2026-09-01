"""The process that makes schedules fire.

    uv run python -m uboss.scheduler_worker

Separate from the API and from the runtime worker, for the same reasons the outbox is: firing is
periodic background work that must keep going while the API deploys, and the API must not wait on
it. One process serves every workspace.

## Two connections, on purpose

**Discovery** runs over the relay connection — `uboss_relay`, the one cross-tenant credential —
and asks a single question: which tenants have a schedule switched on. Migration 0035 grants it
exactly that and nothing else.

**Work** runs over the ordinary application connection with the tenant bound, one workspace at a
time, so every row the scheduler writes goes through the same row-level policies as a request. A
scheduler that did its writes on a cross-tenant credential would be a scheduler whose bug can
write into somebody else's workspace.

## The order inside one tenant

`tick()` writes the firing ledger and the run rows; this worker **commits**, and only then starts
the Temporal workflows. The same order `POST /runs` keeps, for the same reason: a crash between
commit and workflow leaves a `pending` run somebody can find, where the other order leaves a
workflow no row points at. A workflow that fails to start is logged and retried by the runtime's
own reconciliation rather than by rewriting the firing.

## Why a poll and not Temporal's own schedules

Temporal has native schedules, and they were considered. The recurrence rules here — §8's DST
policies, ambiguous-hour policy, skip calendars, weekday-only, missed-run policy — are the
product's own, already implemented and tested in `recurrence.py`, and Temporal's schedule spec
cannot express all of them. Mapping half the rules onto Temporal and keeping half here would be
two schedulers to keep agreeing; a thirty-second poll over an indexed query is nothing, and the
firing ledger makes it safe to run more than one of these.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uboss.core.logging import configure_logging, get_logger
from uboss.core.runtime import configure_event_loop, loop_factory
from uboss.core.settings import Settings, get_settings
from uboss.db.base import (
    build_engine,
    build_relay_engine,
    build_sessionmaker,
    tenant_scope,
)
from uboss.db.registry import import_all
from uboss.modules.runtime import temporal
from uboss.modules.schedules import service

log = get_logger(__name__)

#: How often to look. A schedule's finest grain is a minute, so half of one keeps worst-case
#: lateness well under it without hammering the database.
IDLE_SECONDS = 30.0

#: After a failure at the database itself. Longer, because retrying a broken connection twice a
#: second helps nobody and fills the log.
ERROR_SECONDS = 15.0


async def run(*, once: bool = False) -> int:
    """Fire until stopped. Returns how many runs were started in total."""
    #  Everything, before any query: a worker that imports half the registry meets
    #  NoReferencedTableError on the first join — the lesson the runtime worker learnt.
    import_all()

    settings = get_settings()
    relay_engine = build_relay_engine(settings)
    app_engine = build_engine(settings)
    relay_factory = build_sessionmaker(relay_engine)
    app_factory = build_sessionmaker(app_engine)

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stopping.set)

    log.info("scheduler_worker_started", idle_seconds=IDLE_SECONDS)
    total = 0
    try:
        while not stopping.is_set():
            try:
                started = await _pass(settings, relay_factory, app_factory)
            except Exception as exc:
                log.error(
                    "scheduler_pass_failed", error=f"{type(exc).__name__}: {exc}"
                )
                started = 0
                delay = ERROR_SECONDS
            else:
                total += started
                delay = IDLE_SECONDS

            if once:
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stopping.wait(), timeout=delay)
    finally:
        await relay_engine.dispose()
        await app_engine.dispose()
        log.info("scheduler_worker_stopped", started=total)
    return total


async def _pass(
    settings: Settings,
    relay_factory: async_sessionmaker[AsyncSession],
    app_factory: async_sessionmaker[AsyncSession],
) -> int:
    """One sweep over every workspace with a live schedule."""
    async with relay_factory() as session:
        tenant_ids = [
            row[0]
            for row in (
                await session.execute(
                    #  The discovery question, and the only cross-tenant one: who has a schedule
                    #  switched on. Everything else happens under that tenant's own binding.
                    text(
                        "SELECT DISTINCT tenant_id FROM job_schedules WHERE auto_run"
                    )
                )
            ).all()
        ]

    started = 0
    for tenant_id in tenant_ids:
        started += await _one_tenant(settings, app_factory, tenant_id)
    return started


async def _one_tenant(
    settings: Settings,
    app_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
) -> int:
    """Tick one workspace: ledger and runs in a transaction, workflows after it.

    Failures are per-tenant on purpose — one workspace's broken schedule must not stop every
    other workspace's nightly work.
    """
    async with app_factory() as session:
        try:
            async with tenant_scope(session, tenant_id):
                result = await service.tick(session, tenant_id=tenant_id)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            log.error(
                "scheduler_tenant_failed",
                tenant_id=str(tenant_id),
                error=f"{type(exc).__name__}: {exc}",
            )
            return 0

    if not result.started:
        return 0

    #  After the commit, exactly as `POST /runs` orders it. A workflow that cannot start leaves a
    #  `pending` run with a `started` firing pointing at it — visible, and resolvable — and is
    #  retried by the next person or reconciler rather than by rewriting history here.
    client = await temporal.connect(settings)
    launched = 0
    for firing in result.started:
        try:
            await temporal.start_run(
                client,
                tenant_id=firing.tenant_id,
                run_id=firing.run_id,
                workflow_id=firing.workflow_id,
            )
            launched += 1
        except Exception as exc:
            log.error(
                "scheduled_workflow_start_failed",
                run_id=str(firing.run_id),
                error=f"{type(exc).__name__}: {exc}",
            )
    return launched


def main() -> None:
    parser = argparse.ArgumentParser(description="Fire UBOSS schedules.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Do a single pass and exit. Used by tests and by a manual sweep.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(
        level=settings.log_level, json_output=settings.environment != "local"
    )
    configure_event_loop()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(once=args.once), loop_factory=loop_factory())


if __name__ == "__main__":
    main()
