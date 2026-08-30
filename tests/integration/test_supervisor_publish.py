"""Publishing a Supervisor — §10 group 10, and the gate `PLAN.md` names for Gate 6.

> Exit: failure simulation and forbidden-action tests pass.

The first half is here: a Supervisor with no scenario, or with one that has not passed, cannot be
submitted or published. The second half is `test_supervisor_forbidden_actions.py`, because a claim
about what the system *cannot* do belongs in a file named for it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.supervisors import publish
from uboss.modules.supervisors.models import (
    HandlerRole,
    SimulationStatus,
    Supervisor,
    SupervisorHandler,
    SupervisorKind,
    SupervisorSimulation,
    SupervisorStatus,
    SupervisorSupervised,
    SupervisorVersion,
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


def _scenarios(status: SimulationStatus = SimulationStatus.PASS) -> list[dict[str, object]]:
    """Two scenarios, each with an observation where the status needs one."""
    observed = None if status == SimulationStatus.NOT_RUN else "It did what was expected"
    return [
        {
            "name": name,
            "what_fails": f"{name} stops responding",
            "expected_response": "Pause the run and page the on-call",
            "status": status,
            "observed": observed,
        }
        for name in ("The ERP connection", "The approval queue")
    ]


async def _ready(
    session: AsyncSession,
    workspace: Workspace,
    context: SecurityContext,
    *,
    approver: uuid.UUID,
) -> Supervisor:
    """A draft that would pass the gate, minus whatever the caller wants to break."""
    supervisor = Supervisor(
        tenant_id=workspace.tenant_id,
        name="Finance supervisor",
        kind=SupervisorKind.PERSONAL,
        owner_membership_id=context.membership_id,
        approver_membership_id=approver,
    )
    session.add(supervisor)
    await session.flush()
    session.add(
        SupervisorSupervised(
            tenant_id=workspace.tenant_id,
            supervisor_id=supervisor.id,
            membership_id=context.membership_id,
            position=1,
        )
    )
    await session.flush()
    return supervisor


# ------------------------------------------------------------------ the gate


async def test_a_supervisor_with_no_failure_scenario_cannot_be_submitted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """`PLAN.md`: *"Exit: failure simulation … tests pass."*

    A Supervisor whose behaviour when things go wrong nobody has described has not been tested,
    and "at least one" is where that starts.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await _ready(session, left, context, approver=colleague)

        with pytest.raises(ValidationFailed) as refused:
            await publish.submit(session, context, supervisor.id, supervisor.version)
        assert "No failure scenario" in str(refused.value)
        await session.rollback()


async def test_a_scenario_that_has_not_passed_stops_the_publish(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A scenario recorded as failing is a known problem somebody would be publishing anyway."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await _ready(session, left, context, approver=colleague)

        entries = _scenarios()
        entries[1]["status"] = SimulationStatus.FAIL
        entries[1]["observed"] = "It kept going and nobody was told"
        await publish.record_simulations(
            session, context, supervisor.id, entries, expected_version=supervisor.version
        )

        with pytest.raises(ValidationFailed) as refused:
            await publish.submit(session, context, supervisor.id, supervisor.version)
        assert "The approval queue is fail" in str(refused.value)
        await session.rollback()


async def test_a_result_must_say_what_actually_happened(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A `Pass` with no observation is a claim nobody can check. Held by the schema."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await _ready(session, left, context, approver=colleague)

        entries = _scenarios()
        entries[0]["observed"] = None
        with pytest.raises(IntegrityError):
            await publish.record_simulations(
                session, context, supervisor.id, entries, expected_version=supervisor.version
            )
        await session.rollback()


async def test_who_ran_a_scenario_and_when_is_stamped_by_the_server(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A result somebody could backdate or attribute elsewhere is not evidence."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await _ready(session, left, context, approver=colleague)
        written = await publish.record_simulations(
            session, context, supervisor.id, _scenarios(), expected_version=supervisor.version
        )
        assert all(row.run_by_membership_id == context.membership_id for row in written)
        assert all(row.run_at is not None for row in written)
        await session.rollback()


def test_clearing_results_keeps_the_scenario_and_drops_only_the_observation() -> None:
    """What a scenario tries and what should happen are part of the design; what was seen is not.

    A pure function, so it is tested as one. Its caller is the design-edit service, which lands
    with the Supervisor screen in 6.5 — and until then nothing in the codebase can change a
    Supervisor's design, so there is no path that could leave a stale pass behind.
    """
    rows = [
        SupervisorSimulation(
            name="The ERP connection",
            what_fails="It stops responding",
            expected_response="Pause and page",
            status=SimulationStatus.PASS,
            observed="It paused",
            run_by_membership_id=uuid.uuid4(),
            run_at=datetime.now(UTC),
            position=1,
        ),
        SupervisorSimulation(
            name="Untouched",
            what_fails="x",
            expected_response="y",
            status=SimulationStatus.NOT_RUN,
            position=2,
        ),
    ]
    assert publish.clear_results(rows) == 1
    assert rows[0].status == SimulationStatus.NOT_RUN
    assert rows[0].observed is None and rows[0].run_at is None
    #  The scenario itself survives.
    assert rows[0].what_fails == "It stops responding"
    assert rows[0].expected_response == "Pause and page"


async def test_a_supervisor_supervising_nothing_cannot_be_submitted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Structural rather than a gate — the plan names one gate, and this is the same class of
    check as a Job needing a step before it can be published."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = Supervisor(
            tenant_id=left.tenant_id,
            name="Watches nothing",
            kind=SupervisorKind.PERSONAL,
            owner_membership_id=context.membership_id,
            approver_membership_id=colleague,
        )
        session.add(supervisor)
        await session.flush()
        await publish.record_simulations(
            session, context, supervisor.id, _scenarios(), expected_version=supervisor.version
        )

        with pytest.raises(ValidationFailed) as refused:
            await publish.submit(session, context, supervisor.id, supervisor.version)
        assert "Nothing is supervised" in str(refused.value)
        await session.rollback()


# ------------------------------------------------------------------ approval and the version


async def test_publishing_freezes_both_scopes(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Approving a Supervisor is approving **who may control it**, so the handler list is in the
    snapshot. A record of half the decision would not be a record of the decision."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        supervisor = await _ready(session, left, author, approver=colleague)
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                role=HandlerRole.APPROVER,
            )
        )
        await publish.record_simulations(
            session, author, supervisor.id, _scenarios(), expected_version=supervisor.version
        )
        await publish.submit(session, author, supervisor.id, supervisor.version)

        await _grant(session, left, "publish")
        #  The approver is a handler with the Owner role only if they own it — here they do not,
        #  so they are given Owner explicitly. Publishing needs a role that confers `publish`.
        handler = (
            await session.execute(
                select(SupervisorHandler).where(
                    SupervisorHandler.membership_id == colleague,
                    SupervisorHandler.supervisor_id == supervisor.id,
                )
            )
        ).scalar_one()
        handler.role = HandlerRole.OWNER
        await session.flush()

        approver = await _context(session, left, membership_id=colleague)
        version = await publish.publish(
            session, approver, supervisor.id, supervisor.version
        )

        assert version.version_no == 1
        assert version.approved_by_membership_id == colleague
        assert supervisor.status == SupervisorStatus.PUBLISHED
        assert supervisor.published_version_id == version.id

        #  Both scopes, and the simulation results as they stood.
        assert len(version.snapshot["supervised"]) == 1
        assert len(version.snapshot["handlers"]) == 1
        assert version.snapshot["handlers"][0]["role"] == "owner"
        assert len(version.snapshot["simulations"]) == 2
        assert all(row["status"] == "pass" for row in version.snapshot["simulations"])
        await session.rollback()


async def test_nobody_approves_their_own_supervisor(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """*"No Skill or Agent can approve/promote itself."* Nor may the person who submitted it."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "publish")
        context = await _context(session, left)

        supervisor = await _ready(
            session, left, context, approver=context.membership_id
        )
        await publish.record_simulations(
            session, context, supervisor.id, _scenarios(), expected_version=supervisor.version
        )
        await publish.submit(session, context, supervisor.id, supervisor.version)

        with pytest.raises(PermissionDenied):
            await publish.publish(session, context, supervisor.id, supervisor.version)
        await session.rollback()


async def test_the_approver_must_have_read_the_version_they_approve(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        supervisor = await _ready(session, left, author, approver=colleague)
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                role=HandlerRole.OWNER,
            )
        )
        await publish.record_simulations(
            session, author, supervisor.id, _scenarios(), expected_version=supervisor.version
        )
        await publish.submit(session, author, supervisor.id, supervisor.version)
        await _grant(session, left, "publish")

        approver = await _context(session, left, membership_id=colleague)
        with pytest.raises(Conflict):
            await publish.publish(
                session, approver, supervisor.id, supervisor.version - 1
            )
        await session.rollback()


async def test_a_published_version_cannot_be_edited_or_deleted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Immutable twice over: a trigger refuses the change, and the privilege was never granted."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        supervisor = await _ready(session, left, author, approver=colleague)
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                role=HandlerRole.OWNER,
            )
        )
        await publish.record_simulations(
            session, author, supervisor.id, _scenarios(), expected_version=supervisor.version
        )
        await publish.submit(session, author, supervisor.id, supervisor.version)
        await _grant(session, left, "publish")
        approver = await _context(session, left, membership_id=colleague)
        version = await publish.publish(
            session, approver, supervisor.id, supervisor.version
        )
        await session.commit()
        version_id = version.id

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        for statement in (
            "UPDATE supervisor_versions SET name = 'rewritten' WHERE id = :i",
            "DELETE FROM supervisor_versions WHERE id = :i",
        ):
            with pytest.raises((DBAPIError, ProgrammingError)):
                await session.execute(text(statement), {"i": version_id})
            await session.rollback()
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(left.tenant_id)},
            )
        await session.rollback()


async def test_the_summary_counts_both_scopes_and_invents_no_score(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """*"1 of 2 scenarios pass"* is more use than a readiness percentage.

    A percentage needs a definition of "ready" nobody has agreed, and it would be read as one by
    the person who has to fix it.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await _ready(session, left, context, approver=colleague)
        entries = _scenarios()
        entries[1]["status"] = SimulationStatus.NOT_RUN
        entries[1]["observed"] = None
        await publish.record_simulations(
            session, context, supervisor.id, entries, expected_version=supervisor.version
        )

        found = await publish.summary(session, context, supervisor.id)
        assert (found.simulations_passed, found.simulations_total) == (1, 2)
        assert found.supervised_count == 1
        assert found.handler_count == 0
        assert not found.gates[0].passed
        assert found.next_action
        assert not found.can_approve
        await session.rollback()


async def test_a_version_is_invisible_to_another_workspace(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        supervisor = await _ready(session, left, author, approver=colleague)
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                role=HandlerRole.OWNER,
            )
        )
        await publish.record_simulations(
            session, author, supervisor.id, _scenarios(), expected_version=supervisor.version
        )
        await publish.submit(session, author, supervisor.id, supervisor.version)
        await _grant(session, left, "publish")
        approver = await _context(session, left, membership_id=colleague)
        await publish.publish(session, approver, supervisor.id, supervisor.version)
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(right.tenant_id)}
        )
        assert (await session.execute(select(SupervisorVersion))).scalars().all() == []
        await session.rollback()
