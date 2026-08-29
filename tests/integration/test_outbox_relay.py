"""The outbox relay — 1.5.2 and 1.5.3.

Two exit conditions:

* the relay role reads due rows and is refused on every other table;
* an event survives a worker killed mid-publish and is delivered **exactly one more time**, and
  a permanently failing event lands in the dead-letter view instead of disappearing.

The second is the one worth reading. It is what "at least once" actually means, and testing it
requires simulating the crash rather than trusting the design.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from tests.conftest import TEST_DATABASE, Workspace
from uboss.db.base import build_sessionmaker
from uboss.modules.audit import relay


def _relay_url() -> str:
    base = os.environ["UBOSS_MIGRATION_DATABASE_URL"]
    without_database = base.rsplit("/", 1)[0]
    credentials, host = without_database.split("://", 1)[1].split("@", 1)
    scheme = base.split("://", 1)[0]
    return f"{scheme}://uboss_relay:uboss_relay@{host}/{TEST_DATABASE}"


async def _queue(
    session: AsyncSession, tenant_id: Any, event_type: str = "test.event"
) -> uuid.UUID:
    return (
        await session.execute(
            text(
                """
                INSERT INTO outbox_events
                    (tenant_id, event_type, subject_type, payload, correlation_id)
                VALUES (:t, :e, 'test', '{"n": 1}'::jsonb, 'test-correlation')
                RETURNING id
                """
            ),
            {"t": tenant_id, "e": event_type},
        )
    ).scalar_one()


# ── 1.5.2 — the role ─────────────────────────────────────────────────────────────────────


async def test_the_relay_role_can_read_due_events(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Delivery cannot be tenant-scoped: one worker drains the queue for everybody."""
    left, right = two_workspaces

    async with build_sessionmaker(owner_engine)() as session:
        for workspace in (left, right):
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(workspace.tenant_id)},
            )
            await _queue(session, workspace.tenant_id)
        await session.commit()

    engine = create_async_engine(_relay_url())
    try:
        async with build_sessionmaker(engine)() as session:
            tenants = (
                await session.execute(
                    text("SELECT DISTINCT tenant_id FROM outbox_events")
                )
            ).scalars().all()
            assert {left.tenant_id, right.tenant_id} <= set(tenants), (
                "the relay could not see both organisations' events"
            )
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "table",
    [
        "memberships",
        "sessions",
        "audit_events",
        "roles",
        "resource_grants",
        "tenants",
        "users",
    ],
)
async def test_the_relay_role_is_refused_everywhere_else(
    two_workspaces: tuple[Workspace, Workspace], table: str
) -> None:
    """The only cross-tenant credential in the system, and its reach is one table.

    Parametrised rather than looped so a failure names the table it was refused on.
    """
    engine = create_async_engine(_relay_url())
    try:
        async with build_sessionmaker(engine)() as session:
            with pytest.raises(ProgrammingError) as raised:
                await session.execute(text(f"SELECT count(*) FROM {table}"))
            assert "permission denied" in str(raised.value).lower()
            await session.rollback()
    finally:
        await engine.dispose()


async def test_the_relay_role_cannot_create_or_delete_events(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """It delivers events; it does not invent them, and it does not erase the evidence.

    A published row is history and a dead row is evidence, so `DELETE` is withheld too.
    """
    left, _right = two_workspaces
    engine = create_async_engine(_relay_url())
    try:
        async with build_sessionmaker(engine)() as session:
            for statement in (
                "INSERT INTO outbox_events (tenant_id, event_type, subject_type) "
                "VALUES (:t, 'forged.event', 'test')",
                "DELETE FROM outbox_events",
            ):
                with pytest.raises(ProgrammingError) as raised:
                    await session.execute(text(statement), {"t": left.tenant_id})
                assert "permission denied" in str(raised.value).lower()
                await session.rollback()
    finally:
        await engine.dispose()


# ── 1.5.3 — the relay ────────────────────────────────────────────────────────────────────


async def test_an_event_is_delivered_and_marked(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _right = two_workspaces
    delivered: list[relay.Event] = []

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        event_id = await _queue(session, left.tenant_id, "test.delivered")
        await session.commit()

    registry = relay.Registry()

    async def publisher(event: relay.Event) -> None:
        delivered.append(event)

    registry.register("test.delivered", publisher)

    engine = create_async_engine(_relay_url())
    try:
        factory = build_sessionmaker(engine)
        handled = await relay.run_once(factory, registry, worker="test")
        assert handled >= 1

        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT status, published_at, leased_until, last_error "
                        "FROM outbox_events WHERE id = :id"
                    ),
                    {"id": event_id},
                )
            ).one()
        assert row.status == "published"
        assert row.published_at is not None
        assert row.leased_until is None, "the lease was not released"
        assert any(e.id == event_id for e in delivered)
    finally:
        await engine.dispose()


async def test_an_event_with_no_publisher_is_dead_lettered_not_dropped(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A silently discarded notification is one nobody knows was never sent.

    And it is dead-lettered immediately rather than retried: no amount of waiting registers a
    publisher.
    """
    left, _right = two_workspaces

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        event_id = await _queue(session, left.tenant_id, "test.nobody.listens")
        await session.commit()

    engine = create_async_engine(_relay_url())
    try:
        factory = build_sessionmaker(engine)
        await relay.run_once(factory, relay.Registry(), worker="test")

        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT status, attempts, last_error FROM outbox_events WHERE id = :id"
                    ),
                    {"id": event_id},
                )
            ).one()
        assert row.status == "dead", "an undeliverable event was not dead-lettered"
        assert row.attempts == 1, "it was retried, though retrying cannot help"
        assert "no publisher" in (row.last_error or "").lower()
    finally:
        await engine.dispose()


async def test_a_failing_event_is_retried_then_given_up_on(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Backoff, then the dead-letter view. It never disappears."""
    left, _right = two_workspaces

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        event_id = await _queue(session, left.tenant_id, "test.always.fails")
        await session.commit()

    registry = relay.Registry()

    async def failing(event: relay.Event) -> None:
        raise RuntimeError("the provider said no")

    registry.register("test.always.fails", failing)

    engine = create_async_engine(_relay_url())
    try:
        factory = build_sessionmaker(engine)

        for _ in range(relay.MAX_ATTEMPTS + 1):
            #  The backoff would otherwise make this test take an hour. Bringing the row forward
            #  is the same thing the passage of time would do.
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE outbox_events SET next_attempt_at = now() - interval '1 second' "
                        "WHERE id = :id AND status = 'pending'"
                    ),
                    {"id": event_id},
                )
                await session.commit()
            await relay.run_once(factory, registry, worker="test")

        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT status, attempts, last_error FROM outbox_events WHERE id = :id"
                    ),
                    {"id": event_id},
                )
            ).one()

        assert row.status == "dead"
        assert row.attempts >= relay.MAX_ATTEMPTS
        assert "provider said no" in (row.last_error or "")
    finally:
        await engine.dispose()


async def test_an_event_survives_a_worker_killed_mid_publish(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """1.5.3's exit check, and the reason this is at-least-once.

    A worker claims the event, publishes it, and dies before marking it. The lease expires,
    another worker picks it up, and it is delivered **again** — not lost, and not exactly once.

    Testing this is the difference between a design that says at-least-once and a system that
    behaves that way.
    """
    left, _right = two_workspaces
    deliveries: list[uuid.UUID] = []

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        event_id = await _queue(session, left.tenant_id, "test.crash")
        await session.commit()

    engine = create_async_engine(_relay_url())
    try:
        factory = build_sessionmaker(engine)

        #  First worker: claims, "publishes", then dies. Marking never happens.
        async with factory() as session:
            claimed = await relay.claim(
                session, worker="worker-that-dies", lease=timedelta(milliseconds=1)
            )
            await session.commit()
        assert [e.id for e in claimed] == [event_id]
        deliveries.append(event_id)  # the publish that did happen

        #  The lease was one millisecond, so by now it has passed. In production this is the
        #  five-minute lease expiring.
        registry = relay.Registry()

        async def publisher(event: relay.Event) -> None:
            deliveries.append(event.id)

        registry.register("test.crash", publisher)
        handled = await relay.run_once(factory, registry, worker="worker-that-survives")

        assert handled == 1, "the stranded event was not picked up after the lease expired"
        assert deliveries.count(event_id) == 2, (
            "at-least-once means exactly one more delivery, not zero and not three"
        )

        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT status, attempts FROM outbox_events WHERE id = :id"),
                    {"id": event_id},
                )
            ).one()
        assert row.status == "published"
        assert row.attempts == 2, "the crashed attempt was not counted"
    finally:
        await engine.dispose()


async def test_a_leased_event_is_not_claimed_twice(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two workers running at once must not both deliver the same event.

    `FOR UPDATE SKIP LOCKED` and the lease together are what prevent it — the first takes the
    row, the second skips it rather than waiting.
    """
    left, _right = two_workspaces

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        event_id = await _queue(session, left.tenant_id, "test.contested")
        await session.commit()

    engine = create_async_engine(_relay_url())
    try:
        factory = build_sessionmaker(engine)
        async with factory() as first, factory() as second:
            claimed_first = await relay.claim(first, worker="one")
            await first.commit()
            claimed_second = await relay.claim(second, worker="two")
            await second.commit()

        assert [e.id for e in claimed_first] == [event_id]
        assert event_id not in [e.id for e in claimed_second], (
            "two workers claimed the same event"
        )
    finally:
        await engine.dispose()


async def test_backoff_grows_and_is_capped() -> None:
    """Uncapped backoff on a provider down for a day means the first event after recovery waits
    another day."""
    assert relay.backoff_for(1) < relay.backoff_for(5)
    assert relay.backoff_for(100) == timedelta(seconds=3600)


async def test_an_event_that_is_not_due_yet_is_left_alone(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _right = two_workspaces

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        event_id = await _queue(session, left.tenant_id, "test.later")
        await session.execute(
            text("UPDATE outbox_events SET next_attempt_at = :later WHERE id = :id"),
            {"id": event_id, "later": datetime.now(UTC) + timedelta(hours=1)},
        )
        await session.commit()

    engine = create_async_engine(_relay_url())
    try:
        async with build_sessionmaker(engine)() as session:
            claimed = await relay.claim(session, worker="test")
            await session.rollback()
        assert event_id not in [e.id for e in claimed]
    finally:
        await engine.dispose()
