"""The test that must never be allowed to fail.

Every tenant-owned table, three questions:

1. With no tenant bound, does it return nothing?
2. Bound to one organisation, does it return only that organisation's rows?
3. Can a write be aimed at another organisation?

These run as `uboss_app`, the role every API request uses. Running them as the owner would prove
nothing — FORCE is off (DECISIONS 22), so the owner sees everything by design.

The table list is derived from the database, not hand-written. A hand-written list is a list that
stops mentioning the table somebody added last week, and the first anyone knows is a breach.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.db.base import build_sessionmaker


async def _tenant_owned_tables(session: AsyncSession) -> list[str]:
    """Every table with a `tenant_id`, straight from the catalogue."""
    rows = (
        await session.execute(
            text(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE c.relnamespace = 'public'::regnamespace
                  AND c.relkind = 'r'
                  AND a.attname = 'tenant_id'
                  AND NOT a.attisdropped
                ORDER BY c.relname
                """
            )
        )
    ).scalars().all()
    return list(rows)


async def test_every_tenant_owned_table_has_row_level_security(
    owner_session: AsyncSession,
) -> None:
    """A tenant-owned table without RLS is a hole nobody notices until it is used."""
    unprotected = (
        await owner_session.execute(
            text(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE c.relnamespace = 'public'::regnamespace
                  AND c.relkind = 'r'
                  AND a.attname = 'tenant_id'
                  AND NOT a.attisdropped
                  AND NOT c.relrowsecurity
                """
            )
        )
    ).scalars().all()
    assert list(unprotected) == [], (
        f"These tables carry a tenant_id but have no row-level security: {list(unprotected)}"
    )


async def test_nothing_is_visible_without_a_bound_tenant(
    app_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Fail closed. A connection that forgot to bind its tenant sees nothing, not everything."""
    tables = await _tenant_owned_tables(app_session)
    assert tables, "no tenant-owned tables found — the query is wrong"

    for table in tables:
        count = (
            await app_session.execute(text(f"SELECT count(*) FROM {table}"))
        ).scalar_one()
        assert count == 0, f"{table} returned {count} rows with no tenant bound"


async def test_a_bound_tenant_sees_only_its_own_rows(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        visible = (
            await session.execute(text("SELECT tenant_id FROM memberships"))
        ).scalars().all()

        assert left.tenant_id in visible
        assert right.tenant_id not in visible, (
            "a membership from another organisation was visible"
        )
        assert set(visible) == {left.tenant_id}, (
            f"more than one organisation was visible: {set(visible)}"
        )


async def test_a_write_aimed_at_another_tenant_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`WITH CHECK` is what stops this, and it is separate from `USING`.

    Without it a caller could insert a row belonging to another organisation and simply not be
    able to read it back — which is worse than a read, because it plants data.
    """
    left, right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        with pytest.raises(ProgrammingError) as raised:
            await session.execute(
                text(
                    "INSERT INTO audit_events (tenant_id, action, resource_type, outcome) "
                    "VALUES (:t, 'test.write', 'test', 'succeeded')"
                ),
                {"t": right.tenant_id},
            )
        assert "row-level security" in str(raised.value).lower()
        await session.rollback()


async def test_the_application_role_cannot_create_an_organisation(
    app_session: AsyncSession,
) -> None:
    """DECISIONS 17: provisioning is an operator action, not an API capability.

    There is no privilege-escalation path to "create a tenant" because the capability does not
    exist in the API at any role.
    """
    with pytest.raises(ProgrammingError) as raised:
        await app_session.execute(
            text("INSERT INTO tenants (slug, name) VALUES ('escalation', 'Escalation')")
        )
    assert "row-level security" in str(raised.value).lower()
    await app_session.rollback()


async def test_the_application_role_cannot_read_credentials(
    app_session: AsyncSession,
) -> None:
    """DECISIONS 23: `users` holds every Argon2 hash and is reachable only through functions."""
    with pytest.raises(ProgrammingError) as raised:
        await app_session.execute(text("SELECT password_hash FROM users"))
    assert "permission denied" in str(raised.value).lower()
    await app_session.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action = 'tampered'",
        "DELETE FROM audit_events",
    ],
)
async def test_the_audit_trail_cannot_be_rewritten(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    statement: str,
) -> None:
    """PLAN §30: audit events are append-only. Enforced by a trigger, not by a promise.

    Each statement gets its own transaction. A refused statement aborts the one it ran in, so
    trying both in sequence would run the second inside a transaction PostgreSQL has already
    given up on — and the row it was supposed to act on would no longer be visible, making the
    test pass by finding nothing rather than by being refused.
    """
    left, _right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        await session.execute(
            text(
                "INSERT INTO audit_events (tenant_id, action, resource_type, outcome) "
                "VALUES (:t, 'test.event', 'test', 'succeeded')"
            ),
            {"t": left.tenant_id},
        )
        await session.flush()

        #  Proves the row is there and visible, so a refusal below is a refusal and not an empty
        #  match. Without this the test would pass against a trigger that had been dropped.
        present = (
            await session.execute(
                text("SELECT count(*) FROM audit_events WHERE action = 'test.event'")
            )
        ).scalar_one()
        assert present == 1, "the row to be tampered with is not visible"

        with pytest.raises(DatabaseError) as raised:
            await session.execute(text(statement))
        assert "append-only" in str(raised.value).lower()
        await session.rollback()


async def test_a_membership_cannot_hold_another_tenants_role(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The composite foreign key from migration 0002, on the shape 0004 introduced.

    Row-level security forces the *row's* `tenant_id` to match. Without the composite key that
    row could still point at a role belonging to somebody else.
    """
    left, right = two_workspaces

    async with build_sessionmaker(owner_engine)() as session:
        with pytest.raises(DatabaseError) as raised:
            await session.execute(
                text(
                    "INSERT INTO membership_roles (tenant_id, membership_id, role_id) "
                    "VALUES (:t, :m, :r)"
                ),
                {"t": left.tenant_id, "m": left.membership_id, "r": right.role_id},
            )
        assert "foreign key" in str(raised.value).lower()
        await session.rollback()


async def test_the_isolation_checks_would_actually_catch_a_broken_policy(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """Prove the checks above have teeth.

    A suite that passes because it is asking the wrong question is worse than no suite: it
    reports safety it never measured. So this deliberately turns row-level security off on one
    table, confirms the isolation check then *fails*, and turns it back on.

    Without this, every assertion above would still pass if someone dropped a policy — because
    they would all be reading zero rows for the wrong reason.

    The restore is in a `finally`. A test that leaves security disabled after an unrelated
    failure would make every later test pass for the wrong reason too.
    """
    left, _right = two_workspaces

    async def rows_visible_with_no_tenant_bound() -> int:
        async with build_sessionmaker(app_engine)() as session:
            return int(
                (
                    await session.execute(text("SELECT count(*) FROM memberships"))
                ).scalar_one()
            )

    assert await rows_visible_with_no_tenant_bound() == 0, (
        "the boundary is already broken before this test touched anything"
    )

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(text("COMMIT"))
        try:
            await session.execute(
                text("ALTER TABLE memberships DISABLE ROW LEVEL SECURITY")
            )
            await session.commit()

            leaked = await rows_visible_with_no_tenant_bound()
            assert leaked > 0, (
                "row-level security was disabled and the unbound session still saw nothing — "
                "which means the isolation checks are not measuring the policy at all"
            )
        finally:
            await session.execute(
                text("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
            )
            await session.commit()

    assert await rows_visible_with_no_tenant_bound() == 0, (
        "row-level security was not restored — every later test would now pass for free"
    )
