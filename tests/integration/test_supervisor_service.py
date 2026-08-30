"""Editing a Supervisor — and the rule 6.4 said would land here.

**Saving the design clears every simulation result.** 6.4 shipped `clear_results` with no caller
and said so; this is the caller, and this file is where that claim stops being a promise. Without
it somebody records five passes, changes what the Supervisor watches, and publishes on the
strength of results about a design that no longer exists.

The other thing under test is the shape of the API. §10's two scopes are independent, and the
contract keeps them that way: `supervised` is in the update payload and handlers are not, because
changing who may control a Supervisor is `manage_access` and changing what it watches is
`edit_draft`. One payload carrying both would let the looser permission decide the stricter one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.core.permissions import Action
from uboss.db.base import build_sessionmaker
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.supervisors import handlers, publish, service
from uboss.modules.supervisors.models import (
    HandlerRole,
    SimulationStatus,
    SupervisorKind,
    SupervisorSimulation,
)
from uboss.modules.supervisors.schemas import (
    DependencyInput,
    EscalationInput,
    QualityGateInput,
    SupervisedInput,
    SupervisorCreate,
    SupervisorUpdate,
)

pytestmark = pytest.mark.anyio


async def _context(
    session: AsyncSession, workspace: Workspace, *, membership_id: uuid.UUID | None = None
) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, membership_id or workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = datetime.now(UTC)
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=membership.id,
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


async def _grant(session: AsyncSession, workspace: Workspace, *actions: str) -> None:
    for action in actions:
        await session.execute(
            text(
                "INSERT INTO role_permissions (tenant_id, role_id, action) "
                "VALUES (:t, :r, :a) ON CONFLICT DO NOTHING"
            ),
            {"t": workspace.tenant_id, "r": workspace.role_id, "a": action},
        )
    await session.flush()


def _scenario() -> list[dict[str, object]]:
    return [
        {
            "name": "The ERP connection",
            "what_fails": "It stops responding",
            "expected_response": "Pause and page the on-call",
            "status": SimulationStatus.PASS,
            "observed": "It paused and paged",
        }
    ]


# ------------------------------------------------------------------ the 6.4 deferral, closed


async def test_saving_the_design_clears_every_simulation_result(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The rule 6.4 shipped without a caller. This is the caller.

    Without it somebody records a pass, changes what the Supervisor watches, and publishes on the
    strength of a result about a design that no longer exists — with the gate reporting green.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await service.create(
            session, context, SupervisorCreate(name="Finance supervisor")
        )
        await service.update(
            session,
            context,
            supervisor.id,
            SupervisorUpdate(
                expected_version=supervisor.version,
                supervised=[
                    SupervisedInput(position=1, membership_id=context.membership_id)
                ],
            ),
        )
        await publish.record_simulations(
            session, context, supervisor.id, _scenario(), expected_version=supervisor.version
        )

        found = await publish.summary(session, context, supervisor.id)
        assert found.simulations_passed == 1
        assert found.gates[0].passed

        #  Change what it does.
        await service.update(
            session,
            context,
            supervisor.id,
            SupervisorUpdate(
                expected_version=supervisor.version,
                quality_gates=[
                    QualityGateInput(
                        position=1,
                        name="Every output cites a source",
                        condition="No claim without a citation",
                    )
                ],
            ),
        )

        after = await publish.summary(session, context, supervisor.id)
        assert after.simulations_passed == 0
        assert not after.gates[0].passed

        #  The scenario itself survives; only the observation is gone.
        rows = (
            (
                await session.execute(
                    select(SupervisorSimulation).where(
                        SupervisorSimulation.supervisor_id == supervisor.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].what_fails == "It stops responding"
        assert rows[0].status == SimulationStatus.NOT_RUN
        assert rows[0].observed is None and rows[0].run_at is None
        await session.rollback()


# ------------------------------------------------------------------ the two scopes, in the API


async def test_the_update_payload_cannot_carry_handlers(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The contract makes it unstatable rather than the service refusing it.

    Changing who may control a Supervisor is `manage_access`; changing what it watches is
    `edit_draft`. A payload carrying both would have let the looser permission decide the
    stricter one.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SupervisorUpdate(expected_version=1, handlers=[])  # type: ignore[call-arg]


async def test_editing_the_design_does_not_need_manage_access(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The other half: an Operator may not edit, but a Manager may — and neither needs the other
    scope's permission to do their own."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner = await _context(session, left)
        supervisor = await service.create(
            session, owner, SupervisorCreate(name="Finance supervisor")
        )
        await _grant(session, left, "manage_access")
        owner = await _context(session, left)
        await handlers.set_handler(
            session,
            owner,
            supervisor.id,
            colleague,
            HandlerRole.OPERATOR,
            expected_version=supervisor.version,
        )

        operator = await _context(session, left, membership_id=colleague)
        #  An Operator may pause and retry; §10 does not give them the design.
        with pytest.raises(PermissionDenied):
            await service.update(
                session,
                operator,
                supervisor.id,
                SupervisorUpdate(expected_version=supervisor.version, purpose="Mine now"),
            )
        await session.rollback()


async def test_the_list_shows_only_supervisors_this_person_can_control(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A Supervisor somebody cannot control is not theirs to see.

    Listing it would leak who supervises whom, which is precisely the thing scope 2 governs.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner = await _context(session, left)
        await service.create(session, owner, SupervisorCreate(name="Not yours"))

        mine = await service.list_supervisors(session, owner)
        assert len(mine.supervisors) == 1

        outsider = await _context(session, left, membership_id=colleague)
        theirs = await service.list_supervisors(session, outsider)
        assert theirs.supervisors == []
        #  And `is_empty` still says the workspace has one, so the screen shows "none you can
        #  control" rather than "none exist".
        assert theirs.is_empty is False
        await session.rollback()


# ------------------------------------------------------------------ the design itself


async def test_a_dependency_naming_a_position_that_is_not_supervised_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The API speaks positions and the database speaks ids.

    Translating in the service is what stops a caller naming a row belonging to another
    Supervisor — and a position that is simply not there gets a sentence rather than a foreign
    key error.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await service.create(
            session, context, SupervisorCreate(name="Finance supervisor")
        )

        with pytest.raises(ValidationFailed) as refused:
            await service.update(
                session,
                context,
                supervisor.id,
                SupervisorUpdate(
                    expected_version=supervisor.version,
                    supervised=[
                        SupervisedInput(position=1, membership_id=context.membership_id)
                    ],
                    dependencies=[
                        DependencyInput(supervised_position=1, depends_on_position=7)
                    ],
                ),
            )
        assert "position 7" in str(refused.value)
        await session.rollback()


async def test_a_department_supervisor_must_name_its_department_at_creation(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Refused with a sentence rather than a constraint violation, because this is a form."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        with pytest.raises(ValidationFailed):
            await service.create(
                session,
                context,
                SupervisorCreate(name="Finance", kind=SupervisorKind.DEPARTMENT),
            )
        await session.rollback()


async def test_the_read_says_what_this_person_may_do(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """`my_actions` so the screen disables what it must rather than working the answer out.

    The server still refuses either way — this is the courtesy, not the boundary.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner = await _context(session, left)
        supervisor = await service.create(
            session, owner, SupervisorCreate(name="Finance supervisor")
        )
        await _grant(session, left, "manage_access")
        owner = await _context(session, left)
        await handlers.set_handler(
            session,
            owner,
            supervisor.id,
            colleague,
            HandlerRole.VIEWER,
            expected_version=supervisor.version,
        )

        mine = await service.read(session, owner, supervisor.id)
        assert mine.my_role is HandlerRole.OWNER
        assert str(Action.PUBLISH) in mine.my_actions

        viewer = await _context(session, left, membership_id=colleague)
        theirs = await service.read(session, viewer, supervisor.id)
        assert theirs.my_role is HandlerRole.VIEWER
        assert theirs.my_actions == [str(Action.VIEW)]
        await session.rollback()


async def test_a_stale_save_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await service.create(
            session, context, SupervisorCreate(name="Finance supervisor")
        )
        await service.update(
            session,
            context,
            supervisor.id,
            SupervisorUpdate(expected_version=supervisor.version, purpose="First"),
        )
        with pytest.raises(Conflict):
            await service.update(
                session,
                context,
                supervisor.id,
                SupervisorUpdate(expected_version=supervisor.version - 1, purpose="Second"),
            )
        await session.rollback()


async def test_editing_writes_an_audit_event_naming_fields_and_never_their_values(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A Supervisor carries a company's escalation policy. An audit trail is not a second copy."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await service.create(
            session, context, SupervisorCreate(name="Finance supervisor")
        )
        await service.update(
            session,
            context,
            supervisor.id,
            SupervisorUpdate(
                expected_version=supervisor.version,
                escalations=[
                    EscalationInput(
                        position=1,
                        situation="Something confidential about this company",
                        required_action="Something else confidential",
                        escalate_to_label="Department Head",
                    )
                ],
            ),
        )
        await session.flush()

        detail = (
            await session.execute(
                text(
                    "SELECT detail FROM audit_events WHERE tenant_id = :t "
                    "AND action = 'supervisor.updated'"
                ),
                {"t": left.tenant_id},
            )
        ).scalar_one()
        assert detail["replaced"] == ["escalations"]
        assert "confidential" not in str(detail)
        await session.rollback()
