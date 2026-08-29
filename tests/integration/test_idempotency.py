"""Server idempotency and optimistic concurrency — PLAN §28.

Both exist so a network hiccup does not become a duplicate command or a silent overwrite. Both
are exercised against the database, because the behaviour lives in SQL — an advisory lock and a
version predicate — not in Python.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core import idempotency
from uboss.core.concurrency import VersionConflict, apply_guarded_update
from uboss.core.errors import IdempotencyKeyReused, OperationInProgress, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.identity.models import Membership


async def _bind(session: AsyncSession, tenant_id: Any) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )


async def test_a_repeated_command_replays_instead_of_running_again(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _right = two_workspaces
    key = f"test-{uuid.uuid4().hex}"
    payload = {"target": "abc"}

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)

        async with idempotency.execute(
            session,
            tenant_id=left.tenant_id,
            key=key,
            operation="test.command",
            payload=payload,
        ) as first:
            assert not first.is_replay
            first.complete_json(status_code=200, body={"result": "done"})
        await session.flush()

        async with idempotency.execute(
            session,
            tenant_id=left.tenant_id,
            key=key,
            operation="test.command",
            payload=payload,
        ) as second:
            assert second.is_replay, "the second call ran the command again"
            assert second.replay_body == {"result": "done"}
            assert second.replay_status == 200

        await session.rollback()


async def test_the_same_key_with_different_data_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Not a retry — a bug or an attack. Answering with the earlier result would hide it."""
    left, _right = two_workspaces
    key = f"test-{uuid.uuid4().hex}"

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)

        async with idempotency.execute(
            session,
            tenant_id=left.tenant_id,
            key=key,
            operation="test.command",
            payload={"target": "abc"},
        ) as first:
            first.complete_json(status_code=200, body={"result": "done"})
        await session.flush()

        with pytest.raises(IdempotencyKeyReused):
            async with idempotency.execute(
                session,
                tenant_id=left.tenant_id,
                key=key,
                operation="test.command",
                payload={"target": "SOMETHING ELSE"},
            ):
                pass

        await session.rollback()


async def test_a_concurrent_duplicate_cannot_enter_the_command(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The advisory lock is what stops two copies running at once.

    Without it, two retries arriving together would both find no record, both reserve one, and
    both do the work.
    """
    left, _right = two_workspaces
    key = f"test-{uuid.uuid4().hex}"

    factory = build_sessionmaker(app_engine)
    async with factory() as first_session, factory() as second_session:
        await _bind(first_session, left.tenant_id)
        await _bind(second_session, left.tenant_id)

        async with idempotency.execute(
            first_session,
            tenant_id=left.tenant_id,
            key=key,
            operation="test.command",
            payload={"n": 1},
        ) as running:
            #  The first is still inside the command, holding the lock.
            with pytest.raises(OperationInProgress):
                async with idempotency.execute(
                    second_session,
                    tenant_id=left.tenant_id,
                    key=key,
                    operation="test.command",
                    payload={"n": 1},
                ):
                    pass
            running.complete_json(status_code=200, body={"result": "done"})

        await first_session.rollback()
        await second_session.rollback()


async def test_the_same_key_in_another_tenant_is_a_different_command(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Keys are scoped by tenant. One organisation cannot block or read another's command."""
    left, right = two_workspaces
    key = f"test-{uuid.uuid4().hex}"

    factory = build_sessionmaker(app_engine)
    try:
        async with factory() as session:
            await _bind(session, left.tenant_id)
            async with idempotency.execute(
                session,
                tenant_id=left.tenant_id,
                key=key,
                operation="test.command",
                payload={"n": 1},
            ) as run:
                run.complete_json(status_code=200, body={"result": "left"})
            await session.commit()

        async with factory() as session:
            await _bind(session, right.tenant_id)
            async with idempotency.execute(
                session,
                tenant_id=right.tenant_id,
                key=key,
                operation="test.command",
                payload={"n": 1},
            ) as run:
                assert not run.is_replay, "one tenant replayed another tenant's response"
                run.complete_json(status_code=200, body={"result": "right"})
            await session.rollback()
    finally:
        async with factory() as session:
            await _bind(session, left.tenant_id)
            await session.execute(
                text("DELETE FROM idempotency_records WHERE tenant_id = :t"),
                {"t": left.tenant_id},
            )
            await session.commit()


async def test_a_credential_shaped_response_is_never_stored(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A replay table is not a credential store, and it refuses rather than redacting.

    Redacting would make the replay differ from the first response, breaking the contract the
    whole mechanism exists to keep.
    """
    left, _right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        with pytest.raises(Exception) as raised:
            async with idempotency.execute(
                session,
                tenant_id=left.tenant_id,
                key=f"test-{uuid.uuid4().hex}",
                operation="test.command",
                payload={"n": 1},
            ) as run:
                run.complete_json(status_code=200, body={"token": "a-real-token"})
        assert "replay" in str(raised.value).lower()
        await session.rollback()


async def test_an_unusable_key_is_refused_before_anything_runs() -> None:
    for bad in ("", "   ", "short", "has spaces in it", "x" * 300):
        with pytest.raises(ValidationFailed):
            idempotency.require_idempotency_key(bad)


async def test_expired_records_are_removed(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        async with idempotency.execute(
            session,
            tenant_id=left.tenant_id,
            key=f"test-{uuid.uuid4().hex}",
            operation="test.command",
            payload={"n": 1},
            retention=timedelta(seconds=1),
        ) as run:
            run.complete_json(status_code=200, body={"result": "done"})
        await session.flush()

        assert (
            await session.execute(text("SELECT count(*) FROM idempotency_records"))
        ).scalar_one() == 1

        await idempotency.delete_expired_for_tenant(
            session,
            tenant_id=left.tenant_id,
            now=datetime.now(UTC) + timedelta(hours=1),
        )
        assert (
            await session.execute(text("SELECT count(*) FROM idempotency_records"))
        ).scalar_one() == 0
        await session.rollback()


async def test_two_saves_from_one_stale_read_produce_one_success(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """1.4.3's exit check. The silent overwrite is the failure with no error message."""
    left, _right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        membership = await session.get(Membership, left.membership_id)
        assert membership is not None
        stale = membership.version

        await apply_guarded_update(
            session,
            Membership,
            row_id=left.membership_id,
            tenant_id=left.tenant_id,
            expected_version=stale,
            values={"display_name": "First person"},
        )

        with pytest.raises(VersionConflict):
            await apply_guarded_update(
                session,
                Membership,
                row_id=left.membership_id,
                tenant_id=left.tenant_id,
                expected_version=stale,
                values={"display_name": "Second person"},
            )

        current = (
            await session.execute(
                text("SELECT display_name, version FROM memberships WHERE id = :m"),
                {"m": left.membership_id},
            )
        ).one()
        assert current.display_name == "First person", "the first edit was overwritten"
        assert current.version == stale + 1

        #  After re-reading, the second person can save.
        await apply_guarded_update(
            session,
            Membership,
            row_id=left.membership_id,
            tenant_id=left.tenant_id,
            expected_version=current.version,
            values={"display_name": "Second person, after reloading"},
        )
        await session.rollback()


async def test_a_guarded_update_cannot_reach_another_tenant(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Even with the right id and the right version, from the wrong organisation."""
    left, right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, right.tenant_id)
        with pytest.raises(VersionConflict):
            await apply_guarded_update(
                session,
                Membership,
                row_id=left.membership_id,
                tenant_id=left.tenant_id,
                expected_version=1,
                values={"display_name": "Reached across the boundary"},
            )
        await session.rollback()
