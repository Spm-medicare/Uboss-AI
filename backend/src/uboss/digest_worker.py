"""The process that sends §12's digests.

    uv run python -m uboss.digest_worker

The third sweeping worker, and it follows exactly the pattern the outbox and the scheduler
established — because the pattern is the interesting part, not the feature.

**Discovery on the relay credential.** *Which people are due a digest* is the only cross-tenant
question, and `notification_settings` is the only table 0037 grants `uboss_relay` to answer it.

**Work on the application connection, one tenant at a time**, with the tenant bound, so every row
this reads and writes passes the same policies a request does.

**Nothing is sent here.** The digest is staged on the outbox and the outbox worker delivers it —
so a digest is queued if and only if `last_digest_at` moved in the same transaction, and a crash
between the two cannot produce a second copy of yesterday's summary.

## Why an empty digest is not sent

A person with nothing new gets nothing. `last_digest_at` still moves, so tomorrow's covers only
tomorrow. A mail that says "nothing happened" is the one people write a filter for, and once they
have written the filter they stop seeing the ones that matter.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
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
from uboss.modules.audit import service as audit
from uboss.modules.notifications import policy, service
from uboss.modules.notifications.models import Notification, NotificationSettings

log = get_logger(__name__)

#: How often to look. A digest hour is an hour, so checking four times within it is ample and
#: `digest_is_due` makes the extra checks harmless.
IDLE_SECONDS = 900.0

ERROR_SECONDS = 60.0

#: The most lines one digest carries. Beyond this the mail stops being readable, so it says how
#: many more there are rather than listing them — a truncation that announces itself.
MAX_LINES = 40


async def run(*, once: bool = False) -> int:
    """Send digests until stopped. Returns how many were staged in total."""
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

    log.info("digest_worker_started", idle_seconds=IDLE_SECONDS)
    total = 0
    try:
        while not stopping.is_set():
            try:
                staged = await _pass(relay_factory, app_factory)
            except Exception as exc:
                log.error("digest_pass_failed", error=f"{type(exc).__name__}: {exc}")
                staged = 0
                delay = ERROR_SECONDS
            else:
                total += staged
                delay = IDLE_SECONDS

            if once:
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stopping.wait(), timeout=delay)
    finally:
        await relay_engine.dispose()
        await app_engine.dispose()
        log.info("digest_worker_stopped", staged=total)
    return total


async def _pass(
    relay_factory: async_sessionmaker[AsyncSession],
    app_factory: async_sessionmaker[AsyncSession],
) -> int:
    """One sweep: find the workspaces with digest settings, then do each one."""
    async with relay_factory() as session:
        tenant_ids = [
            row[0]
            for row in (
                await session.execute(
                    text("SELECT DISTINCT tenant_id FROM notification_settings")
                )
            ).all()
        ]

    staged = 0
    for tenant_id in tenant_ids:
        staged += await _one_tenant(app_factory, tenant_id)
    return staged


async def _one_tenant(
    app_factory: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID
) -> int:
    """Everybody in one workspace whose digest hour has arrived.

    Per-tenant failure handling, as the scheduler does: one workspace's bad timezone must not
    stop every other workspace's digests.
    """
    now = datetime.now(UTC)
    async with app_factory() as session:
        try:
            async with tenant_scope(session, tenant_id):
                staged = await send_due(session, tenant_id=tenant_id, now=now)
            await session.commit()
            return staged
        except Exception as exc:
            await session.rollback()
            log.error(
                "digest_tenant_failed",
                tenant_id=str(tenant_id),
                error=f"{type(exc).__name__}: {exc}",
            )
            return 0


async def send_due(
    session: AsyncSession, *, tenant_id: uuid.UUID, now: datetime
) -> int:
    """Stage a digest for everyone in this workspace who is due one.

    Takes `now` so the whole rule is testable by calling a function — the same reason the
    scheduler does. Returns how many digests were staged.
    """
    people = list(
        (await session.execute(select(NotificationSettings))).scalars().all()
    )
    staged = 0
    for person in people:
        if not policy.digest_is_due(
            now,
            digest_hour=person.digest_hour,
            timezone=person.timezone,
            last_digest_at=person.last_digest_at,
        ):
            continue

        lines = await _since(session, person.membership_id, person.last_digest_at)
        #  `last_digest_at` moves whether or not anything is sent. A person with nothing new
        #  gets nothing, and tomorrow's digest covers only tomorrow rather than re-reporting
        #  a quiet day.
        person.last_digest_at = now

        if not lines:
            continue

        address = await service.email_of(session, person.membership_id)
        if address is None:
            continue

        await audit.publish(
            session,
            tenant_id=tenant_id,
            event_type=service.DIGEST_EVENT,
            subject_type="membership",
            subject_id=person.membership_id,
            payload={
                "email": address,
                "lines": lines[:MAX_LINES],
                #: Said plainly rather than silently cut. A digest that hid what it dropped
                #: would be a digest somebody trusted to be complete.
                "more": max(0, len(lines) - MAX_LINES),
            },
        )
        staged += 1
        log.info(
            "digest_staged",
            membership_id=str(person.membership_id),
            lines=len(lines),
        )
    return staged


async def _since(
    session: AsyncSession,
    membership_id: uuid.UUID,
    last_digest_at: datetime | None,
) -> list[dict[str, str]]:
    """What this person has been told since their last digest, oldest first.

    Read from `notifications` rather than from a second queue: the bell is already the record of
    what somebody was told, and a parallel list would be a list that could disagree with it.

    Read ones are included. A digest is a summary of the day, and silently omitting whatever
    somebody happened to glance at would make it an unreliable one.
    """
    query = (
        select(Notification)
        .where(Notification.membership_id == membership_id)
        .order_by(Notification.last_at)
    )
    if last_digest_at is not None:
        query = query.where(Notification.last_at > last_digest_at)

    rows = list((await session.execute(query)).scalars().all())
    return [
        {
            "title": (
                f"{row.title} ({row.occurrences} times)"
                if row.occurrences > 1
                else row.title
            ),
            "body": row.body or "",
            "deep_link": row.deep_link,
        }
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Send UBOSS notification digests.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Do a single pass and exit. Used by tests and by a manual sweep.",
    )
    args = parser.parse_args()

    settings: Settings = get_settings()
    configure_logging(
        level=settings.log_level, json_output=settings.environment != "local"
    )
    configure_event_loop()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(once=args.once), loop_factory=loop_factory())


if __name__ == "__main__":
    main()
