"""Delivering what the outbox recorded.

The outbox pattern exists because two systems cannot be updated atomically. A business change and
the message announcing it are written in one transaction, so the message exists exactly when the
change does. This module is the other half: it reads those rows and delivers them.

**Delivery is at least once.** A worker that publishes and then dies before marking the row will
publish it again when the lease expires. That is the honest guarantee of this design, and every
consumer has to tolerate a duplicate. Nothing here provides exactly-once, and nothing in this
repository says it does.

**Three short transactions, not one long one.** Claim, publish, mark. Holding a database
transaction open across a network call is how a connection pool runs out during an outage at
somebody else's service.

**An event with no publisher is dead-lettered, not dropped.** Registering a publisher is what
makes an event type deliverable; until then the row lands in the dead-letter view saying so. A
silently discarded notification is one nobody knows was never sent.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uboss.core.logging import correlation_id, get_logger

log = get_logger(__name__)

#: How long a claim lasts. Long enough for a slow provider, short enough that a worker killed
#: mid-publish does not strand its events for the rest of the afternoon.
LEASE = timedelta(minutes=5)

#: Attempts before an event is given up on. Each retry waits longer, so this is roughly an hour
#: of trying — past that, the failure is not transient and a person needs to look.
MAX_ATTEMPTS = 6

#: How many events one pass claims. Small: a batch is held under one lease, so a large batch
#: means a crash strands more of them for longer.
BATCH = 20

#: The longest wait between attempts. An hour, so a provider that recovers is not waited out.
MAX_BACKOFF_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class Event:
    """One thing that must reach the outside world."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    event_type: str
    subject_type: str
    subject_id: uuid.UUID | None
    payload: dict[str, Any]
    attempts: int
    correlation_id: str


#: A publisher takes an event and either returns, meaning delivered, or raises. It must not
#: swallow a failure: a publisher that returns quietly on error turns the whole outbox into a
#: table of events that were never sent and are marked as sent.
Publisher = Callable[[Event], Awaitable[None]]


class PublisherMissing(RuntimeError):
    """No publisher is registered for this event type.

    Not retryable and not transient — no amount of waiting registers a publisher. The event is
    dead-lettered immediately, where an operator can see the event type nothing is listening for.
    """


class Registry:
    """Which publisher handles which event type.

    Deliberately explicit. Discovering publishers by scanning would eventually pick up a
    half-finished one, and the failure mode of that is a message delivered by code nobody meant
    to run yet.
    """

    def __init__(self) -> None:
        self._publishers: dict[str, Publisher] = {}

    def register(self, event_type: str, publisher: Publisher) -> None:
        if event_type in self._publishers:
            raise ValueError(f"A publisher is already registered for {event_type!r}.")
        self._publishers[event_type] = publisher

    def publisher_for(self, event_type: str) -> Publisher:
        try:
            return self._publishers[event_type]
        except KeyError:
            raise PublisherMissing(
                f"No publisher is registered for {event_type!r}. The event is recorded and "
                "undelivered."
            ) from None

    @property
    def registered(self) -> list[str]:
        return sorted(self._publishers)


def backoff_for(attempts: int) -> timedelta:
    """How long to wait before trying again.

    Exponential, and capped at an hour. Uncapped backoff on a provider that is down for a day
    means the first event after recovery waits another day.

    The exponent is capped too, but *above* where the seconds cap bites — at 2**12, comfortably
    past 3600. An earlier version capped it at 2**10, which is 1024: the exponent cap bound
    first and the stated hour was unreachable. The test caught it.
    """
    seconds = min(2 ** min(attempts, 12), MAX_BACKOFF_SECONDS)
    return timedelta(seconds=seconds)


async def claim(
    session: AsyncSession, *, worker: str, batch: int = BATCH, lease: timedelta = LEASE
) -> list[Event]:
    """Take a lease on up to `batch` due events.

    `FOR UPDATE SKIP LOCKED` inside the sub-select is what lets several workers run at once
    without any of them waiting: each takes rows the others have not, and none of them blocks.

    `attempts` is incremented **here, when the event is claimed**, not after a failure. A worker
    that dies mid-publish never reaches the failure path, so counting there would let a poisonous
    event be retried for ever by a series of workers it kept killing.

    **Every time is the database's.** `next_attempt_at` and `leased_until` are written by
    `now()` in SQL, so they are compared against `now()` in SQL too. Passing a Python timestamp
    means the answer depends on the clock of whichever machine happens to run the worker — and
    when that clock is a moment behind the database's, a freshly queued event is "not due yet"
    and sits there. It cost an afternoon to find, because it only appears when the two clocks
    disagree.
    """
    rows = (
        await session.execute(
            text(
                """
                UPDATE outbox_events
                SET leased_until = now() + make_interval(secs => :lease_seconds),
                    leased_by = :worker,
                    attempts = attempts + 1
                WHERE id IN (
                    SELECT id FROM outbox_events
                    WHERE status = 'pending'
                      AND next_attempt_at <= now()
                      AND (leased_until IS NULL OR leased_until < now())
                    ORDER BY next_attempt_at
                    LIMIT :batch
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, tenant_id, event_type, subject_type, subject_id,
                          payload, attempts, correlation_id
                """
            ),
            {
                "lease_seconds": lease.total_seconds(),
                "worker": worker[:100],
                "batch": batch,
            },
        )
    ).all()

    return [
        Event(
            id=row.id,
            tenant_id=row.tenant_id,
            event_type=row.event_type,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            payload=row.payload,
            attempts=row.attempts,
            correlation_id=row.correlation_id,
        )
        for row in rows
    ]


async def mark_published(session: AsyncSession, event_id: uuid.UUID) -> None:
    await session.execute(
        text(
            """
            UPDATE outbox_events
            SET status = 'published',
                published_at = now(),
                leased_until = NULL,
                leased_by = NULL,
                last_error = NULL
            WHERE id = :id
            """
        ),
        {"id": event_id},
    )


async def mark_failed(
    session: AsyncSession, event: Event, error: str, *, permanent: bool = False
) -> None:
    """Schedule a retry, or give up and dead-letter.

    A dead event keeps its row and its last error. Deleting it would make a notification that was
    never sent indistinguishable from one that was never asked for.
    """
    exhausted = permanent or event.attempts >= MAX_ATTEMPTS
    await session.execute(
        text(
            """
            UPDATE outbox_events
            SET status = :status,
                next_attempt_at = now() + make_interval(secs => :backoff_seconds),
                leased_until = NULL,
                leased_by = NULL,
                last_error = :error
            WHERE id = :id
            """
        ),
        {
            "id": event.id,
            "status": "dead" if exhausted else "pending",
            "backoff_seconds": backoff_for(event.attempts).total_seconds(),
            #  Truncated: a provider that returns an HTML error page would otherwise put a
            #  kilobyte of markup in a column an operator has to read.
            "error": error[:2000],
        },
    )
    if exhausted:
        log.warning(
            "outbox_event_dead",
            event_id=str(event.id),
            event_type=event.event_type,
            attempts=event.attempts,
            error=error[:200],
        )


async def run_once(
    factory: async_sessionmaker[AsyncSession],
    registry: Registry,
    *,
    worker: str,
    batch: int = BATCH,
) -> int:
    """One pass: claim, publish each, mark. Returns how many were claimed.

    Each event is marked in its **own** transaction. One shared transaction would mean a single
    failure rolling back the successful deliveries' marks — and those would then be delivered
    again, turning one provider hiccup into a burst of duplicates.
    """
    async with factory() as session:
        events = await claim(session, worker=worker, batch=batch)
        await session.commit()

    if not events:
        return 0

    for event in events:
        #  The correlation id travels with the event, so a delivery can be traced back to the
        #  request that caused it — possibly hours later, in a different process.
        token = correlation_id.set(event.correlation_id)
        try:
            publisher = registry.publisher_for(event.event_type)
        except PublisherMissing as missing:
            async with factory() as session:
                await mark_failed(session, event, str(missing), permanent=True)
                await session.commit()
            correlation_id.reset(token)
            continue

        try:
            await publisher(event)
        except Exception as exc:
            async with factory() as session:
                await mark_failed(session, event, f"{type(exc).__name__}: {exc}")
                await session.commit()
            log.info(
                "outbox_event_retry",
                event_id=str(event.id),
                event_type=event.event_type,
                attempts=event.attempts,
            )
        else:
            async with factory() as session:
                await mark_published(session, event.id)
                await session.commit()
            log.info(
                "outbox_event_published",
                event_id=str(event.id),
                event_type=event.event_type,
            )
        finally:
            correlation_id.reset(token)

    return len(events)
