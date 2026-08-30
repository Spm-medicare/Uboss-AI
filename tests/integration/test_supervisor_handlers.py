"""Handler roles as a ceiling — `PLAN.md` §10's six roles, and what each one refuses.

The rule under test is one sentence: **a handler role narrows what the workspace already allows;
it never widens it.** So every test here comes in the same shape — somebody who holds a verb in
the workspace is still refused because their role does not go that far, and somebody whose role
would allow it is still refused because the workspace does not.

§10 also states four things Claude may not do: *"bypass policy, grant permission, perform
uncontrolled retries or approve high-risk actions."* The second is what most of this file is
about, because "grant permission" is exactly what a handler list is one bad rule away from being.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.core.permissions import Action
from uboss.db.base import build_sessionmaker
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.supervisors import guard, handlers, roles
from uboss.modules.supervisors.models import (
    HandlerRole,
    Supervisor,
    SupervisorHandler,
    SupervisorKind,
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
    session: AsyncSession, workspace: Workspace, *, owner: uuid.UUID
) -> Supervisor:
    supervisor = Supervisor(
        tenant_id=workspace.tenant_id,
        name="Finance supervisor",
        kind=SupervisorKind.PERSONAL,
        owner_membership_id=owner,
    )
    session.add(supervisor)
    await session.flush()
    return supervisor


# ------------------------------------------------------------------ the roles themselves


def test_the_roles_are_cumulative_along_the_order_section_10_lists() -> None:
    """§10 lists six in increasing authority and ends with Owner.

    The reading taken is that the list is cumulative — an Approver may do what a Reviewer may. The
    alternative, six unrelated sets, would mean an Approver who cannot read what they approve.
    """
    for lower, higher in zip(roles.ORDER, roles.ORDER[1:], strict=False):
        assert roles.PERMITS[lower] < roles.PERMITS[higher], f"{higher} must include {lower}"


def test_each_role_permits_exactly_what_section_10_describes() -> None:
    """The mapping onto §14's verbs, checked against the plan's own words rather than a guess."""
    assert roles.PERMITS[HandlerRole.VIEWER] == {Action.VIEW}
    #  "pause/resume and safe retry"
    assert Action.RUN in roles.PERMITS[HandlerRole.OPERATOR]
    #  "review output/request changes"
    assert Action.COMMENT in roles.PERMITS[HandlerRole.REVIEWER]
    assert Action.APPROVE in roles.PERMITS[HandlerRole.APPROVER]
    #  "manage scope/policy"
    assert Action.MANAGE_ACCESS in roles.PERMITS[HandlerRole.MANAGER]
    assert Action.PUBLISH in roles.PERMITS[HandlerRole.OWNER]

    #  A Viewer cannot pause, and an Operator cannot approve. Each is somebody's mistake waiting.
    assert Action.RUN not in roles.PERMITS[HandlerRole.VIEWER]
    assert Action.APPROVE not in roles.PERMITS[HandlerRole.OPERATOR]


def test_no_role_confers_a_workspace_wide_verb() -> None:
    """A Supervisor's Owner is not a workspace administrator.

    `administer`, `audit`, `export` and `integrate` are workspace-wide, and §10 gives a Supervisor
    authority over none of them. Refused for every role including Owner, which is what stops a
    Supervisor from becoming a route to workspace administration.
    """
    for action in (Action.ADMINISTER, Action.AUDIT, Action.EXPORT, Action.INTEGRATE):
        assert action not in roles.GOVERNED
        for role in roles.ORDER:
            assert not roles.permits(role, action)


# ------------------------------------------------------------------ the two checks


async def test_a_role_never_widens_what_the_workspace_withheld(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Owner of a Supervisor, and still refused because the workspace does not grant `publish`.

    This is the sentence the whole gate rests on: a handler role narrows, it never grants.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await _supervisor(session, left, owner=context.membership_id)

        #  The fixture's role holds view, comment, edit_draft and publish — so take publish away
        #  to make the point directly.
        await session.execute(
            text(
                "DELETE FROM role_permissions WHERE tenant_id = :t AND role_id = :r "
                "AND action = 'publish'"
            ),
            {"t": left.tenant_id, "r": left.role_id},
        )
        await session.flush()
        context = await _context(session, left)

        assert await guard.role_for(session, supervisor, context.membership_id) is (
            HandlerRole.OWNER
        )
        assert roles.permits(HandlerRole.OWNER, Action.PUBLISH)
        with pytest.raises(PermissionDenied):
            await guard.authorise_handler(session, context, supervisor, Action.PUBLISH)
        await session.rollback()


async def test_the_workspace_grant_alone_is_not_enough(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Holds `view` in the workspace, and is not a handler at all."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner_context = await _context(session, left)
        supervisor = await _supervisor(session, left, owner=owner_context.membership_id)

        outsider = await _context(session, left, membership_id=colleague)
        assert Action.VIEW in outsider.granted_actions
        with pytest.raises(PermissionDenied):
            await guard.authorise_handler(session, outsider, supervisor, Action.VIEW)
        await session.rollback()


async def test_a_viewer_holding_run_in_the_workspace_still_cannot_pause(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The narrowing direction, proved with both halves present.

    The person holds `run` across the workspace. Their role on this Supervisor is Viewer. §10 gives
    pause/resume to the Operator, so this is refused — and the reason is recorded.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner_context = await _context(session, left)
        await _grant(session, left, "run")
        supervisor = await _supervisor(session, left, owner=owner_context.membership_id)
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
        assert Action.RUN in viewer.granted_actions

        with pytest.raises(PermissionDenied):
            await guard.authorise_handler(session, viewer, supervisor, Action.RUN)

        #  The refusal was staged, not written. `_refuse` raises before anything flushes it.
        await session.flush()
        reason = (
            await session.execute(
                text(
                    "SELECT denial_reason FROM audit_events WHERE tenant_id = :t "
                    "AND action = 'supervisor.run.denied' ORDER BY occurred_at DESC LIMIT 1"
                ),
                {"t": left.tenant_id},
            )
        ).scalar_one()
        assert "viewer" in reason and "run" in reason
        await session.rollback()


async def test_an_operator_holding_run_may_pause(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Both halves present, so it is allowed.

    Without one of these the suite would prove only that things fail, which is a different and
    much weaker claim.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner_context = await _context(session, left)
        await _grant(session, left, "run")
        supervisor = await _supervisor(session, left, owner=owner_context.membership_id)
        session.add(
            SupervisorHandler(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                membership_id=colleague,
                role=HandlerRole.OPERATOR,
            )
        )
        await session.flush()

        operator = await _context(session, left, membership_id=colleague)
        role = await guard.authorise_handler(session, operator, supervisor, Action.RUN)
        assert role is HandlerRole.OPERATOR
        await session.rollback()


async def test_the_owner_is_a_handler_without_a_row(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Requiring the owner to appear in their own list would mean a Supervisor could be locked out
    of by deleting one row."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        supervisor = await _supervisor(session, left, owner=context.membership_id)

        rows = (
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
        assert rows == []
        assert (
            await guard.role_for(session, supervisor, context.membership_id)
            is HandlerRole.OWNER
        )
        await session.rollback()


# ------------------------------------------------------------------ no self-grant


async def test_nobody_grants_a_role_above_their_own(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
    third_person: uuid.UUID,
) -> None:
    """Otherwise a Manager makes somebody Owner and is then removed by them — an escalation with
    two extra steps."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner_context = await _context(session, left)
        await _grant(session, left, "manage_access")
        supervisor = await _supervisor(session, left, owner=owner_context.membership_id)
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

        #  The same person granting a role at or below their own is fine.
        await handlers.set_handler(
            session,
            manager,
            supervisor.id,
            third_person,
            HandlerRole.APPROVER,
            expected_version=supervisor.version,
        )
        await session.rollback()


async def test_nobody_changes_their_own_role(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The person who benefits is not the person who decides — the same rule the publish routes
    apply."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner_context = await _context(session, left)
        await _grant(session, left, "manage_access")
        supervisor = await _supervisor(session, left, owner=owner_context.membership_id)
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
                colleague,
                HandlerRole.MANAGER,
                expected_version=supervisor.version,
            )
        await session.rollback()


async def test_a_manager_cannot_remove_the_owner(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """There is no row to remove, and pretending otherwise would report a change that did not
    happen."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        owner_context = await _context(session, left)
        await _grant(session, left, "manage_access")
        supervisor = await _supervisor(session, left, owner=owner_context.membership_id)
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
        with pytest.raises(ValidationFailed):
            await handlers.remove_handler(
                session,
                manager,
                supervisor.id,
                owner_context.membership_id,
                expected_version=supervisor.version,
            )
        await session.rollback()


async def test_setting_a_handler_records_who_decided_and_when(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A grant somebody could attribute elsewhere is not a record of who decided."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "manage_access")
        context = await _context(session, left)
        supervisor = await _supervisor(session, left, owner=context.membership_id)

        row = await handlers.set_handler(
            session,
            context,
            supervisor.id,
            colleague,
            HandlerRole.REVIEWER,
            expected_version=supervisor.version,
        )
        assert row.granted_by_membership_id == context.membership_id
        assert row.granted_at is not None

        await session.flush()
        recorded = (
            await session.execute(
                text(
                    "SELECT detail FROM audit_events WHERE tenant_id = :t "
                    "AND action = 'supervisor.handler_set'"
                ),
                {"t": left.tenant_id},
            )
        ).scalar_one()
        assert recorded["role"] == "reviewer"
        await session.rollback()


async def test_a_stale_handler_change_is_refused(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Optimistic concurrency on the Supervisor, because a control list is exactly the thing two
    people edit at once."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "manage_access")
        context = await _context(session, left)
        supervisor = await _supervisor(session, left, owner=context.membership_id)

        with pytest.raises(Conflict):
            await handlers.set_handler(
                session,
                context,
                supervisor.id,
                colleague,
                HandlerRole.VIEWER,
                expected_version=supervisor.version + 1,
            )
        await session.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def third_person(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> AsyncIterator[uuid.UUID]:
    """A third member of the left workspace, so a grant has somebody to be aimed at.

    Created on the **owner** connection because `uboss_app` cannot write `users` — migration 0006
    took that privilege away and the reason has not changed. A test that could add a user as the
    application role would be testing a boundary that does not exist.
    """
    left, _ = two_workspaces
    suffix = uuid.uuid4().hex[:8]
    async with build_sessionmaker(owner_engine)() as session:
        user_id = (
            await session.execute(
                text(
                    "INSERT INTO users (email, password_hash, status) "
                    "VALUES (:e, 'x', 'active') RETURNING id"
                ),
                {"e": f"third-{suffix}@example.test"},
            )
        ).scalar_one()
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        membership_id = (
            await session.execute(
                text(
                    "INSERT INTO memberships (tenant_id, user_id, display_name, status) "
                    "VALUES (:t, :u, 'Third person', 'active') RETURNING id"
                ),
                {"t": left.tenant_id, "u": user_id},
            )
        ).scalar_one()
        await session.commit()

    yield membership_id

    #  Removed before `two_workspaces` tears the tenant down, or its foreign key would refuse.
    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        await session.execute(
            text("DELETE FROM supervisor_handlers WHERE membership_id = :m"),
            {"m": membership_id},
        )
        await session.execute(
            text("DELETE FROM memberships WHERE id = :m"), {"m": membership_id}
        )
        await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await session.commit()
