"""The Objective draft — PLAN §7's form, and what it refuses.

The field set comes from two places and `docs/architecture/OBJECTIVE_FIELDS.md` records why. What
matters here is that neither source is quietly dropped: the workbook's fourteen step columns
round-trip, and §7's governance fields save alongside them.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy import service as hierarchy
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.objectives import service
from uboss.modules.objectives.models import ObjectiveStatus, ObjectiveVersion
from uboss.modules.objectives.schemas import (
    CurrentStepInput,
    ObjectiveCreate,
    ObjectiveUpdate,
)

pytestmark = pytest.mark.anyio


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = hierarchy._now()
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
        step_up_at=now,
        step_up_expires_at=now + timedelta(minutes=10),
    )


async def test_an_empty_workspace_reads_as_empty_not_as_a_failure(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`is_empty` separates "none yet" from "none matching" — different words on screen."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        listing = await service.list_objectives(session, context)

    assert listing.is_empty
    assert listing.objectives == []


async def test_a_draft_starts_from_a_title_alone(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §6's journey begins at "Create/Open Draft".

    A form that demanded eight groups before it would save anything is a form people fill in
    somewhere else first and then paste.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        objective = await service.create(
            session, context, ObjectiveCreate(title="Cut quotation turnaround")
        )
        await session.flush()

        assert objective.status == ObjectiveStatus.DRAFT
        #  Owned by whoever started it. An unowned objective is one nobody is answerable for.
        assert objective.owner_membership_id == left.membership_id
        assert objective.is_editable
        await session.rollback()


async def test_the_workbooks_fourteen_step_columns_round_trip(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Every column of the approved sheet, saved and read back.

    PLAN §6: *"New UI reorganizes fields; it does not silently remove business requirements."*
    This is the test that would fail if a column were quietly dropped in a refactor.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective = await service.create(
            session, context, ObjectiveCreate(title="Quotations")
        )
        await session.flush()

        step = CurrentStepInput(
            who_person="Priya",
            who_role="Sales coordinator",
            when_trigger="New email",
            when_frequency="Every transaction",
            what_exact_work="Read the enquiry and copy the line items into the quote sheet",
            input_used="Customer email",
            input_received_from="Customer",
            where_done="Excel",
            output_produced="Draft quotation",
            output_sent_to="Sales manager",
            time_taken="25 minutes",
            current_problem="Manual data entry",
            approval="Team Lead",
        )
        await service.update(
            session,
            context,
            objective.id,
            ObjectiveUpdate(current_steps=[step], expected_version=objective.version),
        )
        await session.flush()

        saved = await service.read(session, context, objective.id)
        assert len(saved.current_steps) == 1
        stored = saved.current_steps[0]
        assert stored.position == 1
        for field, expected in step.model_dump().items():
            assert getattr(stored, field) == expected, field
        await session.rollback()


async def test_a_value_outside_the_workbooks_list_is_accepted(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Every one of the workbook's lists ends in "Other".

    Refusing a value outside the list would refuse something the approved sheet explicitly
    allows — and would tell a team their own process is invalid.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective = await service.create(session, context, ObjectiveCreate(title="Quotes"))
        await session.flush()

        await service.update(
            session,
            context,
            objective.id,
            ObjectiveUpdate(
                current_steps=[
                    CurrentStepInput(
                        where_done="Our own quoting tool",
                        current_problem="The tool times out on Fridays",
                    )
                ],
                expected_version=objective.version,
            ),
        )
        await session.flush()

        saved = await service.read(session, context, objective.id)
        assert saved.current_steps[0].where_done == "Our own quoting tool"
        await session.rollback()


async def test_saving_the_steps_again_replaces_them_without_a_position_clash(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The grid is replaced wholesale, and reordering reuses positions.

    Without the flush between the delete and the inserts, a reorder collides with rows that are
    about to disappear — and the person who dragged a row sees a constraint error.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective = await service.create(session, context, ObjectiveCreate(title="Quotes"))
        await session.flush()

        await service.update(
            session,
            context,
            objective.id,
            ObjectiveUpdate(
                current_steps=[
                    CurrentStepInput(what_exact_work="first"),
                    CurrentStepInput(what_exact_work="second"),
                ],
                expected_version=objective.version,
            ),
        )
        await session.flush()

        #  Swapped, which reuses both positions.
        await service.update(
            session,
            context,
            objective.id,
            ObjectiveUpdate(
                current_steps=[
                    CurrentStepInput(what_exact_work="second"),
                    CurrentStepInput(what_exact_work="first"),
                ],
                expected_version=objective.version,
            ),
        )
        await session.flush()

        saved = await service.read(session, context, objective.id)
        assert [step.what_exact_work for step in saved.current_steps] == ["second", "first"]
        await session.rollback()


async def test_a_stale_version_is_a_conflict(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two tabs open on one draft is ordinary. Losing one of them is not.

    This matters more here than anywhere else in the product: the form autosaves, so a stale
    version is not a rare race — it is what a second tab produces within seconds.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective = await service.create(session, context, ObjectiveCreate(title="Quotes"))
        await session.flush()
        stale = objective.version

        await service.update(
            session,
            context,
            objective.id,
            ObjectiveUpdate(expected_result="Quotes out same day", expected_version=stale),
        )
        await session.flush()

        with pytest.raises(Conflict):
            await service.update(
                session,
                context,
                objective.id,
                ObjectiveUpdate(expected_result="Something else", expected_version=stale),
            )
        await session.rollback()


async def test_editing_needs_edit_draft(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`right` holds `view` alone. Reading is allowed; writing is not."""
    _, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, right)

        await service.list_objectives(session, context)

        with pytest.raises(PermissionDenied):
            await service.create(session, context, ObjectiveCreate(title="Not allowed"))
        await session.rollback()


async def test_an_archived_objective_is_kept(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §30 — archived, never deleted. Every run recorded against it needs it to exist."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective = await service.create(session, context, ObjectiveCreate(title="Old work"))
        await session.flush()

        await service.archive(session, context, objective.id, objective.version)
        await session.flush()

        listing = await service.list_objectives(session, context)
        assert listing.objectives == []
        #  Still there, and still readable by id.
        with_archived = await service.list_objectives(
            session, context, include_archived=True
        )
        assert [card.id for card in with_archived.objectives] == [objective.id]
        await session.rollback()


async def test_a_published_version_cannot_be_rewritten(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §30: *"Published versions are immutable."*

    Written as the **owner**, which is the strongest case: if the trigger holds against the role
    that owns the schema, it holds against the application role — which additionally does not
    have the privilege at all.
    """
    left, _ = two_workspaces
    await owner_session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
    )

    objective_id = (
        await owner_session.execute(
            text(
                "INSERT INTO objectives (tenant_id, title) VALUES (:t, 'Quotes') RETURNING id"
            ),
            {"t": left.tenant_id},
        )
    ).scalar_one()
    owner_session.add(
        ObjectiveVersion(
            tenant_id=left.tenant_id,
            objective_id=objective_id,
            snapshot={"title": "Quotes"},
            title="Quotes",
        )
    )
    await owner_session.flush()

    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        await owner_session.execute(
            text("UPDATE objective_versions SET title = 'Changed' WHERE tenant_id = :t"),
            {"t": left.tenant_id},
        )
    await owner_session.rollback()


async def test_too_many_steps_is_refused_with_a_reason(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The answer is to split the objective, and the message says so."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective = await service.create(session, context, ObjectiveCreate(title="Everything"))
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await service.update(
                session,
                context,
                objective.id,
                ObjectiveUpdate(
                    current_steps=[
                        CurrentStepInput(what_exact_work=f"step {index}")
                        for index in range(service.MAX_STEPS + 1)
                    ],
                    expected_version=objective.version,
                ),
            )
        assert "Split it" in str(refused.value)
        await session.rollback()
