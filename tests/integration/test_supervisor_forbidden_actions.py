"""The four things §10 says Claude cannot do, one test each.

> Claude cannot bypass policy, grant permission, perform uncontrolled retries or approve
> high-risk actions.

`PLAN.md` makes these a delivery gate rather than a nicety — *"Exit: failure simulation and
forbidden-action tests pass."* So this file exists to be the thing that passes, and each test is
named for the prohibition it covers rather than for the mechanism it happens to use.

**What "Claude" means here.** There is no model call in Gate 6; the AI Gateway arrives with the
runtime. So these test the *system* the model will act through: a prohibition enforced by a prompt
is a request, and a prohibition enforced by a guard, a constraint or a missing field is a rule.
Every one below is the second kind, and that is the point — when a model is finally wired in, it
inherits these because it has no other route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import PermissionDenied, ValidationFailed
from uboss.core.permissions import Action
from uboss.db.base import build_sessionmaker
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.supervisors import guard, handlers, publish, roles
from uboss.modules.supervisors.models import (
    HandlerRole,
    SimulationStatus,
    Supervisor,
    SupervisorHandler,
    SupervisorKind,
    SupervisorSupervised,
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
    granted_roles, granted, ceiling = await access_for(session, membership)
    now = datetime.now(UTC)
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        email="person@test",
        display_name=membership.display_name,
        roles=granted_roles,
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


async def _supervisor(
    session: AsyncSession, workspace: Workspace, *, owner: uuid.UUID, **fields: object
) -> Supervisor:
    supervisor = Supervisor(
        tenant_id=workspace.tenant_id,
        name="Finance supervisor",
        kind=SupervisorKind.PERSONAL,
        owner_membership_id=owner,
        **fields,  # type: ignore[arg-type]
    )
    session.add(supervisor)
    await session.flush()
    return supervisor


# ------------------------------------------------------- 1. cannot bypass policy


async def test_it_cannot_bypass_policy(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The workspace guard runs **first**, and a handler role cannot get past it.

    The person here is the Supervisor's Owner — the highest handler role there is — and the
    workspace does not grant `publish`. Every route into a Supervisor action goes through
    `authorise_handler`, which asks the workspace before it asks the role, so there is no order of
    operations in which the role answers first.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await _supervisor(session, left, owner=context.membership_id)

        await session.execute(
            text(
                "DELETE FROM role_permissions WHERE tenant_id = :t AND role_id = :r "
                "AND action = 'publish'"
            ),
            {"t": left.tenant_id, "r": left.role_id},
        )
        await session.flush()
        context = await _context(session, left)

        assert roles.permits(HandlerRole.OWNER, Action.PUBLISH)
        with pytest.raises(PermissionDenied):
            await guard.authorise_handler(session, context, supervisor, Action.PUBLISH)
        await session.rollback()


async def test_a_supervisor_confers_no_workspace_wide_authority(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The other half of "bypass policy": no role reaches `administer`, `audit`, `export` or
    `integrate`, so owning a Supervisor is never a route to running the workspace."""
    for action in (Action.ADMINISTER, Action.AUDIT, Action.EXPORT, Action.INTEGRATE):
        assert action not in roles.GOVERNED
        assert not roles.permits(HandlerRole.OWNER, action)


# ------------------------------------------------------- 2. cannot grant permission


async def test_it_cannot_grant_a_permission_above_its_own(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
    third_person: uuid.UUID,
) -> None:
    """A Manager cannot make somebody Owner — an escalation with two extra steps."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner_context = await _context(session, left)
        await _grant(session, left, "manage_access")
        supervisor = await _supervisor(
            session, left, owner=owner_context.membership_id
        )
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                role=HandlerRole.MANAGER,
            )
        )
        await session.flush()

        manager = await _context(session, left, membership_id=colleague)
        with pytest.raises(PermissionDenied):
            await handlers.set_handler(
                session,
                manager,
                supervisor.id,
                third_person,
                HandlerRole.OWNER,
                expected_version=supervisor.version,
            )
        await session.rollback()


async def test_it_cannot_grant_a_permission_to_itself(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The person who benefits is not the person who decides."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner_context = await _context(session, left)
        await _grant(session, left, "manage_access")
        supervisor = await _supervisor(
            session, left, owner=owner_context.membership_id
        )
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                role=HandlerRole.VIEWER,
            )
        )
        await session.flush()

        viewer = await _context(session, left, membership_id=colleague)
        with pytest.raises(PermissionDenied):
            await handlers.set_handler(
                session,
                viewer,
                supervisor.id,
                colleague,
                HandlerRole.OWNER,
                expected_version=supervisor.version,
            )
        await session.rollback()


# ------------------------------------------------------- 3. no uncontrolled retries


async def test_a_retry_ceiling_is_a_ceiling(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """*"Uncontrolled"* is the word §10 uses, so the schema refuses the two shapes of it.

    A negative retry count is meaningless, and a negative backoff would mean retrying before the
    previous attempt. Zero retries is a real answer — try once and stop.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        for field, value in (("max_retries", -1), ("retry_backoff_seconds", -1)):
            with pytest.raises((IntegrityError, DBAPIError)):
                await _supervisor(
                    session, left, owner=context.membership_id, **{field: value}
                )
            await session.rollback()
            context = await _context(session, left)


async def test_the_retry_ceiling_that_was_approved_is_frozen_in_the_version(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A limit somebody could raise after approval is not a limit.

    The published version holds the retry settings as they stood, so what a run is bound by is
    what was approved rather than whatever the draft has become since.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        supervisor = await _supervisor(
            session,
            left,
            owner=author.membership_id,
            approver_membership_id=colleague,
            max_retries=2,
            retry_backoff_seconds=30,
        )
        session.add(
            SupervisorSupervised(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=author.membership_id,
                position=1,
            )
        )
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                role=HandlerRole.OWNER,
            )
        )
        await session.flush()

        await publish.record_simulations(
            session,
            author,
            supervisor.id,
            [
                {
                    "name": "The ERP connection",
                    "what_fails": "It stops responding",
                    "expected_response": "Retry twice, then page",
                    "status": SimulationStatus.PASS,
                    "observed": "It retried twice and paged",
                }
            ],
            expected_version=supervisor.version,
        )
        await publish.submit(session, author, supervisor.id, supervisor.version)
        await _grant(session, left, "publish")
        approver = await _context(session, left, membership_id=colleague)
        version = await publish.publish(
            session, approver, supervisor.id, supervisor.version
        )

        assert version.snapshot["supervisor"]["max_retries"] == 2
        assert version.snapshot["supervisor"]["retry_backoff_seconds"] == 30

        #  The draft can move on; the approved version cannot.
        supervisor.max_retries = 99
        await session.flush()
        assert version.snapshot["supervisor"]["max_retries"] == 2
        await session.rollback()


# ------------------------------------------------------- 4. cannot approve high-risk actions


async def test_it_cannot_approve_its_own_publication(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Publishing is the high-risk action a Supervisor has, and nobody approves their own."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "publish")
        context = await _context(session, left)

        supervisor = await _supervisor(
            session,
            left,
            owner=context.membership_id,
            approver_membership_id=context.membership_id,
        )
        session.add(
            SupervisorSupervised(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=context.membership_id,
                position=1,
            )
        )
        await session.flush()
        await publish.record_simulations(
            session,
            context,
            supervisor.id,
            [
                {
                    "name": "Anything",
                    "what_fails": "Something",
                    "expected_response": "Something else",
                    "status": SimulationStatus.PASS,
                    "observed": "It did it",
                }
            ],
            expected_version=supervisor.version,
        )
        await publish.submit(session, context, supervisor.id, supervisor.version)

        with pytest.raises(PermissionDenied):
            await publish.publish(session, context, supervisor.id, supervisor.version)
        await session.rollback()


async def test_only_the_named_approver_can_approve(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
    third_person: uuid.UUID,
) -> None:
    """Holding `publish` and an Owner role is not enough — you have to be the person named.

    Otherwise approval would be a permission rather than a responsibility somebody accepted.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        supervisor = await _supervisor(
            session,
            left,
            owner=author.membership_id,
            approver_membership_id=colleague,
        )
        session.add(
            SupervisorSupervised(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=author.membership_id,
                position=1,
            )
        )
        #  A third person with the highest handler role there is.
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=third_person,
                role=HandlerRole.OWNER,
            )
        )
        await session.flush()
        await publish.record_simulations(
            session,
            author,
            supervisor.id,
            [
                {
                    "name": "Anything",
                    "what_fails": "Something",
                    "expected_response": "Something else",
                    "status": SimulationStatus.PASS,
                    "observed": "It did it",
                }
            ],
            expected_version=supervisor.version,
        )
        await publish.submit(session, author, supervisor.id, supervisor.version)
        await _grant(session, left, "publish")

        interloper = await _context(session, left, membership_id=third_person)
        with pytest.raises(ValidationFailed) as refused:
            await publish.publish(
                session, interloper, supervisor.id, supervisor.version
            )
        assert "not the named approver" in str(refused.value)
        await session.rollback()
