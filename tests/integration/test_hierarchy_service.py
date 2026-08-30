"""What the hierarchy service does, and refuses.

The schema tests next door prove the database holds the line. These prove the service in front of
it does the four things every mutation must do — authorise, match the version, write a revision,
write an audit event — and that PLAN §5's undo actually reverses a change rather than appearing
to.

They run against the **application** role, so row-level security is in force exactly as it is in
production. A suite that tested this as the owner would pass with the boundary switched off.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy import service
from uboss.modules.hierarchy.models import UnitType
from uboss.modules.hierarchy.schemas import (
    AssignmentCreate,
    OrgUnitCreate,
    OrgUnitMove,
    OrgUnitUpdate,
    PositionCreate,
)
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for

pytestmark = pytest.mark.anyio

TODAY = date(2026, 8, 30)


async def _context(
    session: AsyncSession, workspace: Workspace, *, stepped_up: bool = True
) -> SecurityContext:
    """A security context for this person, as `/auth/me` would build it.

    `stepped_up` defaults to True because `administer` is high-risk: without a recent password
    proof every structural change is refused, which is correct behaviour and useless as a fixture
    default.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=workspace.membership_id,
        session_id=uuid.uuid4(),
        email="person@test",
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        org_node_id=membership.org_node_id,
        policy_grants=ceiling,
        step_up_at=service._now() if stepped_up else None,
        #  Both halves are needed: `has_stepped_up` asks whether the proof has expired, and a
        #  proof with no expiry has, as far as it is concerned, already lapsed.
        step_up_expires_at=(
            service._now() + timedelta(minutes=10) if stepped_up else None
        ),
    )


async def _grant(session: AsyncSession, workspace: Workspace, *actions: str) -> None:
    """Add permissions to the fixture's role.

    Binds the tenant first: an unbound session sees no rows and can write none, which is the
    boundary working rather than a fixture problem.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    for action in actions:
        await session.execute(
            text(
                "INSERT INTO role_permissions (tenant_id, role_id, action) "
                "VALUES (:t, :r, :a) ON CONFLICT DO NOTHING"
            ),
            {"t": workspace.tenant_id, "r": workspace.role_id, "a": action},
        )
    await session.flush()


async def test_a_new_tree_reads_as_empty_not_as_a_failure(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`is_empty` exists so the interface can tell "nothing yet" from "the request failed".

    On screen those look identical and mean opposite things — the second one loses somebody's
    afternoon.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        tree = await service.read_tree(session, context, as_at=TODAY)

    assert tree.is_empty
    assert tree.units == []
    assert tree.as_at == TODAY


async def test_creating_a_department_records_who_did_it(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A revision and an audit event, both in the same transaction as the change."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer")
        context = await _context(session, left)

        unit = await service.create_unit(
            session,
            context,
            OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY, external_ref="ROOT"),
        )
        await session.flush()

        page = await service.revisions(session, context)
        assert page.revisions[0].change_type == "unit.created"
        assert page.revisions[0].entity_id == unit.id
        assert page.revisions[0].actor_membership_id == left.membership_id
        assert page.revisions[0].can_undo

        events = (
            await session.execute(
                text(
                    "SELECT action FROM audit_events WHERE tenant_id = :t "
                    "AND resource_id = :r"
                ),
                {"t": left.tenant_id, "r": unit.id},
            )
        ).scalars()
        assert "unit.created" in list(events)
        await session.rollback()


async def test_a_structural_change_needs_administer(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The fixture's role holds view, comment, edit_draft and publish — not administer.

    Reading is allowed and changing the shape is not, which is the whole point of separating
    them.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        await service.read_tree(session, context, as_at=TODAY)

        with pytest.raises(PermissionDenied):
            await service.create_unit(
                session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
            )
        await session.rollback()


async def test_administer_without_a_recent_password_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`administer` is high-risk (PLAN line 366). Holding it is not the same as holding it now."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer")
        context = await _context(session, left, stepped_up=False)

        with pytest.raises(PermissionDenied):
            await service.create_unit(
                session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
            )
        await session.rollback()


async def test_a_stale_version_is_a_conflict_not_a_silent_overwrite(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §28. Two people editing one department is ordinary; losing one edit is not."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer")
        context = await _context(session, left)

        unit = await service.create_unit(
            session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
        )
        await service.update_unit(
            session, context, unit.id, OrgUnitUpdate(name="Acme Group", expected_version=1)
        )

        #  The second person still holds version 1, which they read before the first save.
        with pytest.raises(Conflict):
            await service.update_unit(
                session, context, unit.id, OrgUnitUpdate(name="Acme Ltd", expected_version=1)
            )
        await session.rollback()


async def test_a_vacant_seat_is_shown_as_vacant(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §5: "Preserve vacant positions."

    An org chart that hides its empty seats hides the hiring plan. `holder` is null and the
    position is still there.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer", "assign")
        context = await _context(session, left)

        root = await service.create_unit(
            session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
        )
        await service.create_position(
            session,
            context,
            PositionCreate(org_unit_id=root.id, title="Regional Manager"),
        )
        await session.flush()

        tree = await service.read_tree(session, context, as_at=TODAY)
        seat = tree.units[0].positions[0]
        assert seat.title == "Regional Manager"
        assert seat.holder is None

        issues = await service.validate(session, context, as_at=TODAY)
        assert any(issue.kind == "vacant_position" for issue in issues)
        await session.rollback()


async def test_the_tree_answers_for_the_date_it_was_asked_about(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """An assignment that starts next month is not in effect today.

    This is why assignments are dated rather than overwritten: both facts have to be true at
    once, and "who runs this on the first" has to be answerable before the first.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer", "assign")
        context = await _context(session, left)

        root = await service.create_unit(
            session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
        )
        seat = await service.create_position(
            session, context, PositionCreate(org_unit_id=root.id, title="Manager")
        )
        starts = TODAY + timedelta(days=30)
        await service.assign(
            session,
            context,
            seat.id,
            AssignmentCreate(membership_id=left.membership_id, effective_from=starts),
        )
        await session.flush()

        today = await service.read_tree(session, context, as_at=TODAY)
        assert today.units[0].positions[0].holder is None

        later = await service.read_tree(session, context, as_at=starts)
        holder = later.units[0].positions[0].holder
        assert holder is not None
        assert holder.membership_id == left.membership_id
        await session.rollback()


async def test_a_department_with_people_in_it_cannot_be_archived(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Archiving it would leave its positions parented to something no longer there.

    That is the orphan PLAN §5 asks the product to detect, so the product declines to create one.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer")
        context = await _context(session, left)

        root = await service.create_unit(
            session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
        )
        await service.create_position(
            session, context, PositionCreate(org_unit_id=root.id, title="Manager")
        )
        await session.flush()

        with pytest.raises(ValidationFailed):
            await service.archive_unit(session, context, root.id, root.version)
        await session.rollback()


async def test_undo_reverses_a_change_and_says_so_in_the_history(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Undo is a new change, not an erasure.

    The history shows that somebody undid something rather than pretending it never happened —
    and that is also what gives redo for free: undoing the undo is an ordinary undo.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer")
        context = await _context(session, left)

        unit = await service.create_unit(
            session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
        )
        await service.update_unit(
            session, context, unit.id, OrgUnitUpdate(name="Acme Group", expected_version=1)
        )
        await session.flush()

        page = await service.revisions(session, context, entity_id=unit.id)
        rename = page.revisions[0]
        assert rename.change_type == "unit.updated"

        await service.undo(session, context, rename.id)
        await session.flush()

        refreshed = await service.read_tree(session, context, as_at=TODAY)
        assert refreshed.units[0].name == "Acme"

        after = await service.revisions(session, context, entity_id=unit.id)
        assert after.revisions[0].change_type == "org_unit.undone"
        #  The undo itself is not offered for undo — redo goes through the revision it reverted.
        assert after.revisions[0].can_undo is False
        await session.rollback()


async def test_only_the_most_recent_change_can_be_undone(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Reversing an older change would silently discard everything since.

    There is no honest way to warn somebody about a change they cannot see, so the service
    declines and names the reason.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer")
        context = await _context(session, left)

        unit = await service.create_unit(
            session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
        )
        await service.update_unit(
            session, context, unit.id, OrgUnitUpdate(name="Acme Group", expected_version=1)
        )
        await service.update_unit(
            session, context, unit.id, OrgUnitUpdate(name="Acme Ltd", expected_version=2)
        )
        await session.flush()

        page = await service.revisions(session, context, entity_id=unit.id)
        older = page.revisions[1]

        with pytest.raises(ValidationFailed):
            await service.undo(session, context, older.id)
        await session.rollback()


async def test_a_move_that_would_close_a_loop_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The refusal comes from the database, and the service surfaces it at the point of the move.

    Flushing inside `move_unit` is what makes that true — without it the trigger would fire at
    the end of some later request, and the person who caused it would be somewhere else.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _grant(session, left, "administer")
        context = await _context(session, left)

        root = await service.create_unit(
            session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
        )
        middle = await service.create_unit(
            session,
            context,
            OrgUnitCreate(name="Operations", unit_type=UnitType.DIVISION, parent_id=root.id),
        )
        await session.flush()

        with pytest.raises(Exception) as refused:
            await service.move_unit(
                session,
                context,
                root.id,
                OrgUnitMove(new_parent_id=middle.id, expected_version=root.version),
            )
        assert "descendant" in str(refused.value)
        await session.rollback()
