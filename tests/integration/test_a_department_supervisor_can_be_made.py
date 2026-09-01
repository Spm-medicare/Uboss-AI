"""The other half of §10, which the product had and could not reach.

*"Department Supervisor Agent: supervises selected users/Agents in a department."* Every layer
supported it: `SupervisorCreate` takes a kind and an `org_node_id`, `service.create` refuses each
wrong combination in words, migration 0023's constraint refuses them again at the table, and
`test_supervisor_scopes.py` proves the constraint. The one thing missing was a way for a person to
say so — the create control sent `kind: "personal"` as a literal, so Gate 6's headline deliverable
was half unreachable.

These tests are about the path a screen takes: create with a department, read it back, see it in the
list. The refusals already had a test each; what had none was the case that works, which is the one
a screen depends on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy.models import OrgUnit, UnitType
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.supervisors import service
from uboss.modules.supervisors.models import SupervisorKind
from uboss.modules.supervisors.schemas import SupervisorCreate

pytestmark = pytest.mark.anyio


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, workspace.membership_id)
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


async def _department(session: AsyncSession, workspace: Workspace, name: str) -> uuid.UUID:
    """A department under this workspace's single root.

    `uq_org_units_single_root` allows one parentless node per workspace — a company has one top —
    so a second department has to hang off the first node rather than being another root. The first
    version of this helper made every department a root and the second test found out.
    """
    root = (
        await session.execute(
            select(OrgUnit.id).where(
                OrgUnit.tenant_id == workspace.tenant_id, OrgUnit.parent_id.is_(None)
            )
        )
    ).scalars().first()
    if root is None:
        company = OrgUnit(
            tenant_id=workspace.tenant_id, name="The company", unit_type=UnitType.COMPANY
        )
        session.add(company)
        await session.flush()
        root = company.id

    unit = OrgUnit(
        tenant_id=workspace.tenant_id,
        name=name,
        unit_type=UnitType.DEPARTMENT,
        parent_id=root,
    )
    session.add(unit)
    await session.flush()
    return unit.id


async def test_a_department_supervisor_is_created_with_its_department(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The case that had no test: the one that works.

    Both refusals were covered — a department Supervisor with no department, and a personal one
    with a department — and between them nothing asserted that the accepted combination is
    actually accepted. Two refusals and no acceptance is also what a permanently broken create
    route looks like.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        node = await _department(session, left, "Quality Assurance")

        supervisor = await service.create(
            session,
            context,
            SupervisorCreate(
                name="QA watch", kind=SupervisorKind.DEPARTMENT, org_node_id=node
            ),
        )

        assert supervisor.kind == SupervisorKind.DEPARTMENT
        assert supervisor.org_node_id == node
        #  The creator is the owner, so they can go on and finish it — the same rule as personal.
        assert supervisor.owner_membership_id == left.membership_id
        await session.rollback()


async def test_the_read_names_the_department_it_watches(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§10's first form group is *"Identity, owner, department and linked Objective scope"*.

    `org_node_name` was already on the read schema and was displayed nowhere, which is how a field
    stays right in the API and wrong on the screen for a whole gate.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        node = await _department(session, left, "Dispatch")
        supervisor = await service.create(
            session,
            context,
            SupervisorCreate(
                name="Dispatch watch", kind=SupervisorKind.DEPARTMENT, org_node_id=node
            ),
        )

        found = await service.read(session, context, supervisor.id)

        assert found.kind == SupervisorKind.DEPARTMENT
        assert found.org_node_id == node
        assert found.org_node_name == "Dispatch"
        await session.rollback()


async def test_the_list_says_which_department_each_one_watches(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two department Supervisors are otherwise told apart only by what their names happen to say.

    A personal one carries no department, and the join has to be an outer one for that to be true
    rather than making personal Supervisors disappear from the list.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        sales = await _department(session, left, "Sales")
        finance = await _department(session, left, "Finance")

        await service.create(
            session,
            context,
            SupervisorCreate(name="One", kind=SupervisorKind.DEPARTMENT, org_node_id=sales),
        )
        await service.create(
            session,
            context,
            SupervisorCreate(name="Two", kind=SupervisorKind.DEPARTMENT, org_node_id=finance),
        )
        await service.create(session, context, SupervisorCreate(name="Mine"))

        listed = await service.list_supervisors(session, context)
        by_name = {card.name: card for card in listed.supervisors}

        assert by_name["One"].department_name == "Sales"
        assert by_name["Two"].department_name == "Finance"
        #  A personal Supervisor has no department, and still appears.
        assert by_name["Mine"].department_name is None
        assert by_name["Mine"].kind == SupervisorKind.PERSONAL
        await session.rollback()


async def test_a_personal_supervisor_cannot_name_a_department(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The refusal the screen relies on when somebody switches the kind back.

    The dialog clears the department when personal is chosen; this is what happens if it ever
    stops doing that. A personal Supervisor with a department would be a row nobody could
    classify — it watches its owner's agents, so a department on it means nothing.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        node = await _department(session, left, "Stores")

        with pytest.raises(ValidationFailed):
            await service.create(
                session,
                context,
                SupervisorCreate(
                    name="Confused", kind=SupervisorKind.PERSONAL, org_node_id=node
                ),
            )
        await session.rollback()


async def test_a_department_from_another_workspace_cannot_be_named(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The id comes from a request body, so it is the one thing here that is not trustworthy.

    Refused by the composite foreign key `(tenant_id, org_node_id)`: there is no row in *this*
    tenant with that id, so the insert fails. That is the boundary doing its job rather than a
    check somebody remembered to write — which is why the constraint is composite in the first
    place.
    """
    from sqlalchemy.exc import DatabaseError

    left, right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(right.tenant_id)}
        )
        theirs = await _department(session, right, "Their department")
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        with pytest.raises(DatabaseError):
            await service.create(
                session,
                context,
                SupervisorCreate(
                    name="Reaching over", kind=SupervisorKind.DEPARTMENT, org_node_id=theirs
                ),
            )
        await session.rollback()

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(right.tenant_id)}
        )
        row = await session.get(OrgUnit, theirs)
        if row is not None:
            await session.delete(row)
            await session.commit()
