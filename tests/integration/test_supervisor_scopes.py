"""The two scopes `PLAN.md` §10 makes mandatory, and their independence.

> Two independent scopes are mandatory:
> 1. Supervised members/Agents: whose Agents are monitored?
> 2. Allowed handlers: who may control this Supervisor?

"Independent" is the requirement, not a description, so the first test here sets the two to
**disjoint sets** and asserts both hold. If a future change ever derives one from the other — a
convenience that adds the department's people as handlers, say — that test fails, which is the
point of writing it before anything reads either scope.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.db.base import build_sessionmaker
from uboss.modules.supervisors.models import (
    HandlerRole,
    Supervisor,
    SupervisorHandler,
    SupervisorKind,
    SupervisorSupervised,
)

pytestmark = pytest.mark.anyio


async def _bind(session: AsyncSession, workspace: Workspace) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )


async def _supervisor(
    session: AsyncSession,
    workspace: Workspace,
    *,
    kind: SupervisorKind = SupervisorKind.PERSONAL,
    owner: uuid.UUID | None = None,
    org_node_id: uuid.UUID | None = None,
) -> Supervisor:
    supervisor = Supervisor(
        tenant_id=workspace.tenant_id,
        name=f"{kind.value.title()} supervisor",
        kind=kind,
        owner_membership_id=owner or workspace.membership_id,
        org_node_id=org_node_id,
    )
    session.add(supervisor)
    await session.flush()
    return supervisor


async def _department(session: AsyncSession, workspace: Workspace) -> uuid.UUID:
    """One org unit, written directly. The hierarchy's own service is tested elsewhere."""
    return (
        await session.execute(
            text(
                "INSERT INTO org_units (tenant_id, name, unit_type) "
                "VALUES (:t, 'Finance', 'department') RETURNING id"
            ),
            {"t": workspace.tenant_id},
        )
    ).scalar_one()


# ------------------------------------------------------------------ the thing that matters


async def test_the_two_scopes_can_be_disjoint_and_both_hold(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The requirement, stated as a test.

    A department head controls a Supervisor watching somebody else's Agents. Nobody appears in
    both scopes. If a future convenience ever derives handlers from the supervised set — or the
    other way round — this fails, which is why it is written before anything reads either.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        node = await _department(session, left)

        #  Owned by the colleague, supervising the colleague, controlled by the fixture's person.
        supervisor = await _supervisor(
            session,
            left,
            kind=SupervisorKind.DEPARTMENT,
            owner=colleague,
            org_node_id=node,
        )
        session.add(
            SupervisorSupervised(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                position=1,
            )
        )
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=left.membership_id,
                role=HandlerRole.MANAGER,
                granted_by_membership_id=colleague,
            )
        )
        await session.flush()

        supervised = {
            row.membership_id
            for row in (
                await session.execute(
                    select(SupervisorSupervised).where(
                        SupervisorSupervised.supervisor_id == supervisor.id
                    )
                )
            )
            .scalars()
            .all()
        }
        handlers = {
            row.membership_id
            for row in (
                await session.execute(
                    select(SupervisorHandler).where(
                        SupervisorHandler.supervisor_id == supervisor.id
                    )
                )
            )
            .scalars()
            .all()
        }

        assert supervised == {colleague}
        assert handlers == {left.membership_id}
        #  Disjoint, and neither is empty. That is the whole assertion.
        assert supervised.isdisjoint(handlers)
        await session.rollback()


async def test_nothing_derives_a_handler_from_the_supervised_set(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Adding somebody to one scope must not add them to the other.

    The plan's decision table is explicit for department Supervisors: *"Explicit selected people;
    no automatic department-wide control."*
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        node = await _department(session, left)
        supervisor = await _supervisor(
            session, left, kind=SupervisorKind.DEPARTMENT, org_node_id=node
        )

        session.add(
            SupervisorSupervised(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                position=1,
            )
        )
        await session.flush()

        handlers = (
            (
                await session.execute(
                    select(SupervisorHandler).where(
                        SupervisorHandler.supervisor_id == supervisor.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert handlers == []
        await session.rollback()


# ------------------------------------------------------------------ personal means personal


async def test_a_personal_supervisor_refuses_somebody_elses_agents(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """§10: *"logically isolated per eligible account; supervises that user's permitted Job
    Agents."*

    Held by a trigger rather than a service, because it is what the word "personal" means and a
    second write path — an import, a fixture, a future bulk route — must not get around it.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left, kind=SupervisorKind.PERSONAL)

        session.add(
            SupervisorSupervised(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                position=1,
            )
        )
        with pytest.raises((IntegrityError, DBAPIError)) as refused:
            await session.flush()
        assert "personal supervisor" in str(refused.value)
        await session.rollback()


async def test_a_personal_supervisor_accepts_its_owners_agents(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left, kind=SupervisorKind.PERSONAL)
        session.add(
            SupervisorSupervised(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=left.membership_id,
                position=1,
            )
        )
        await session.flush()
        assert supervisor.kind == SupervisorKind.PERSONAL
        await session.rollback()


# ------------------------------------------------------------------ the shape of a supervisor


async def test_a_department_supervisor_must_name_a_department(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """And a personal one must not. Both halves, because either alone would let a row exist that
    nobody could classify."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)

        with pytest.raises(IntegrityError):
            await _supervisor(session, left, kind=SupervisorKind.DEPARTMENT)
        await session.rollback()

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        node = await _department(session, left)
        with pytest.raises(IntegrityError):
            await _supervisor(
                session, left, kind=SupervisorKind.PERSONAL, org_node_id=node
            )
        await session.rollback()


async def test_a_supervisor_must_have_an_owner(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A Supervisor with no owner is one nobody is answerable for."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        with pytest.raises((IntegrityError, DBAPIError)):
            await session.execute(
                text(
                    "INSERT INTO supervisors (tenant_id, name, kind) "
                    "VALUES (:t, 'Ownerless', 'personal')"
                ),
                {"t": left.tenant_id},
            )
        await session.rollback()


async def test_one_person_holds_one_role_on_one_supervisor(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Two rows would be two ceilings, and nothing in the design says which wins."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)

        for role in (HandlerRole.VIEWER, HandlerRole.MANAGER):
            session.add(
                SupervisorHandler(
                    tenant_id=left.tenant_id,
                    supervisor_id=supervisor.id,
                    membership_id=colleague,
                    role=role,
                )
            )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_a_pinned_version_needs_an_agent(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A version of nothing in particular is not a scope."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        session.add(
            SupervisorSupervised(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=left.membership_id,
                agent_id=None,
                agent_version_id=uuid.uuid4(),
                position=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_workspace_wide_is_not_a_kind_anybody_can_write(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§10: *"Workspace-wide Supervisor is restricted and may be added later."*

    Absent from the schema rather than present and unused — a value nobody approved is a value
    somebody eventually sets.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        with pytest.raises((IntegrityError, DBAPIError)):
            await session.execute(
                text(
                    "INSERT INTO supervisors (tenant_id, name, kind, owner_membership_id) "
                    "VALUES (:t, 'Everything', 'workspace', :m)"
                ),
                {"t": left.tenant_id, "m": left.membership_id},
            )
        await session.rollback()


async def test_a_supervisor_is_invisible_to_another_workspace(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        await _supervisor(session, left)
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, right)
        assert (await session.execute(select(Supervisor))).scalars().all() == []
        await session.rollback()
