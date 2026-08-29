"""The permission ceiling, PLAN §14.

Company → department → resource → action, with one rule: a lower scope can never grant more power
than the scope above it.

These exercise the resolution directly rather than through a route, because no product route
enforces a permission yet — those arrive in Gate 2. What is tested is the thing every one of them
will call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import PermissionDenied, ValidationFailed
from uboss.core.permissions import Action, effective
from uboss.db.base import build_sessionmaker
from uboss.modules.audit.models import AuditEvent
from uboss.modules.identity import guard, policies
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for


async def _context_for(engine: AsyncEngine, workspace: Workspace) -> SecurityContext:
    async with build_sessionmaker(engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(workspace.tenant_id)},
        )
        membership = (
            await session.get(Membership, workspace.membership_id)  # type: ignore[func-returns-value]
        )
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
        )


async def test_a_role_grants_exactly_what_its_permissions_say(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Role names are data (PLAN §17). What they permit comes from `role_permissions`."""
    left, right = two_workspaces

    left_context = await _context_for(app_engine, left)
    right_context = await _context_for(app_engine, right)

    assert left_context.actions == {
        Action.VIEW,
        Action.COMMENT,
        Action.EDIT_DRAFT,
        Action.PUBLISH,
    }
    assert right_context.actions == {Action.VIEW}


async def test_no_role_means_nothing_is_permitted() -> None:
    """Failing closed applies here: an empty baseline permits nothing, whatever the policies."""
    assert effective(frozenset(), []) == frozenset()


async def test_an_unconfigured_scope_narrows_nothing() -> None:
    """A company that has written no policy has not taken anything away.

    The opposite reading — absent means empty — would make a brand-new tenant indistinguishable
    from a locked-out one.
    """
    baseline = frozenset({Action.VIEW, Action.PUBLISH})
    assert effective(baseline, []) == baseline


async def test_a_company_policy_narrows_every_role_beneath_it(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """1.3.2's exit check, automated."""
    left, _right = two_workspaces

    before = await _context_for(app_engine, left)
    assert Action.PUBLISH in before.actions

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        policy_id = (
            await session.execute(
                text(
                    "INSERT INTO scope_policies (tenant_id, scope, name, reason) "
                    "VALUES (:t, 'company', 'Freeze', 'test') RETURNING id"
                ),
                {"t": left.tenant_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO scope_policy_restrictions (tenant_id, policy_id, action) "
                "VALUES (:t, :p, 'publish')"
            ),
            {"t": left.tenant_id, "p": policy_id},
        )
        await session.commit()

    try:
        after = await _context_for(app_engine, left)
        assert Action.PUBLISH not in after.actions, (
            "the company policy did not narrow the role"
        )
        assert Action.VIEW in after.actions, "it narrowed more than it withheld"
    finally:
        async with build_sessionmaker(owner_engine)() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(left.tenant_id)},
            )
            await session.execute(
                text("DELETE FROM scope_policies WHERE tenant_id = :t"),
                {"t": left.tenant_id},
            )
            await session.commit()


async def test_a_resource_grant_cannot_widen_a_role(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §14: a lower scope cannot grant more power than the parent.

    Checked twice — once when the grant is written, once when it is read. The write-time refusal
    is what makes the mistake visible; without it the grant would simply be a row that looks like
    access and behaves like nothing.
    """
    _left, right = two_workspaces
    context = await _context_for(app_engine, right)
    assert Action.PUBLISH not in context.actions

    with pytest.raises(ValidationFailed):
        policies.check_grant_is_narrowing(
            Action.PUBLISH, "user", context.granted_actions
        )

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(right.tenant_id)},
        )
        objective = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO resource_grants "
                "(tenant_id, resource_type, resource_id, principal_kind, principal_id, action) "
                "VALUES (:t, 'objective', :r, 'user', :m, 'publish')"
            ),
            {"t": right.tenant_id, "r": objective, "m": right.membership_id},
        )
        await session.flush()

        grant = await policies.grant_for_resource(
            session,
            tenant_id=right.tenant_id,
            membership_id=right.membership_id,
            resource_type="objective",
            resource_id=objective,
            role_actions=context.granted_actions,
        )
        assert grant is not None
        assert Action.PUBLISH not in grant.actions, (
            "a grant naming an action the role lacks took effect"
        )
        await session.rollback()


async def test_an_unshared_object_leaves_the_resource_layer_absent(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """None and an empty grant mean opposite things — DECISIONS 26.

    None means no resource restriction applies, so a role's `view` still works on an object
    nobody explicitly shared. An empty grant would refuse everything on every object.
    """
    left, _right = two_workspaces
    context = await _context_for(app_engine, left)

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        grant = await policies.grant_for_resource(
            session,
            tenant_id=left.tenant_id,
            membership_id=left.membership_id,
            resource_type="objective",
            resource_id=uuid.uuid4(),
            role_actions=context.granted_actions,
        )
    assert grant is None


async def test_a_high_risk_action_requires_a_live_step_up(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN line 366. Holding the permission is not enough for actions that change access."""
    left, _right = two_workspaces
    context = await _context_for(app_engine, left)
    assert Action.PUBLISH in context.actions

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )

        with pytest.raises(guard.StepUpRequired):
            await guard.authorise(session, context, Action.PUBLISH)

        stepped = SecurityContext(
            **{
                **{
                    f.name: getattr(context, f.name)
                    for f in context.__dataclass_fields__.values()
                },
                "step_up_at": datetime.now(UTC),
                "step_up_expires_at": datetime.now(UTC) + timedelta(minutes=15),
            }
        )
        await guard.authorise(session, stepped, Action.PUBLISH)

        #  And an expired proof is not a proof.
        expired = SecurityContext(
            **{
                **{
                    f.name: getattr(context, f.name)
                    for f in context.__dataclass_fields__.values()
                },
                "step_up_at": datetime.now(UTC) - timedelta(hours=2),
                "step_up_expires_at": datetime.now(UTC) - timedelta(hours=1),
            }
        )
        with pytest.raises(guard.StepUpRequired):
            await guard.authorise(session, expired, Action.PUBLISH)

        await session.rollback()


async def test_the_author_of_a_change_cannot_approve_it(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Separation of duty. The point of an approval is that a second person looked."""
    left, _right = two_workspaces
    context = await _context_for(app_engine, left)
    resource = guard.Resource(type="objective", id=uuid.uuid4())

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )

        with pytest.raises(PermissionDenied):
            await guard.refuse_self_approval(
                session,
                context,
                submitted_by_membership_id=context.membership_id,
                resource=resource,
            )

        #  Somebody else's work is fine.
        await guard.refuse_self_approval(
            session,
            context,
            submitted_by_membership_id=uuid.uuid4(),
            resource=resource,
        )
        await session.rollback()


async def test_a_refusal_is_recorded_with_its_reason(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """1.3.5. The reason reaches the audit trail; the caller gets none of it."""
    _left, right = two_workspaces
    context = await _context_for(app_engine, right)
    assert Action.PUBLISH not in context.actions

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(right.tenant_id)},
        )

        with pytest.raises(PermissionDenied) as raised:
            await guard.authorise(session, context, Action.PUBLISH)

        #  The message says nothing about why, or about the target.
        assert str(raised.value) == guard.REFUSED
        await session.flush()

        rows = (
            await session.execute(
                text(
                    "SELECT action, outcome, denial_reason FROM audit_events "
                    "WHERE outcome = 'denied'"
                )
            )
        ).all()
        assert rows, "the refusal was not recorded"
        assert any("publish" in row.action for row in rows)
        assert any(row.denial_reason for row in rows), (
            "a denial was recorded with no reason for an administrator to read"
        )
        await session.rollback()


async def test_a_denial_reason_never_reaches_the_caller(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A refusal that explains itself confirms the resource exists."""
    _left, right = two_workspaces
    context = await _context_for(app_engine, right)
    decision = context.explain(Action.PUBLISH)

    assert not decision.allowed
    assert decision.reason, "the administrator-facing reason is missing"

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(right.tenant_id)},
        )
        with pytest.raises(PermissionDenied) as raised:
            await guard.authorise(session, context, Action.PUBLISH)
        await session.rollback()

    message = str(raised.value)
    assert decision.reason not in message
    assert "publish" not in message.lower()
    assert "policy" not in message.lower()


async def test_audit_rows_for_a_denial_stay_inside_the_tenant(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A refusal is evidence, and evidence belongs to one organisation."""
    _left, right = two_workspaces
    context = await _context_for(app_engine, right)

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(right.tenant_id)},
        )
        with pytest.raises(PermissionDenied):
            await guard.authorise(session, context, Action.PUBLISH)
        await session.flush()

        tenants = (
            await session.execute(
                text("SELECT DISTINCT tenant_id FROM audit_events")
            )
        ).scalars().all()
        assert set(tenants) == {right.tenant_id}
        await session.rollback()


async def test_the_audit_event_model_matches_what_the_guard_writes(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Reads the row back through the ORM, so a column rename cannot pass unnoticed."""
    _left, right = two_workspaces
    context = await _context_for(app_engine, right)

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(right.tenant_id)},
        )
        with pytest.raises(PermissionDenied):
            await guard.authorise(session, context, Action.PUBLISH)
        await session.flush()

        from sqlalchemy import select

        event = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.outcome == "denied")
            )
        ).scalars().first()
        assert event is not None
        assert event.actor_membership_id == right.membership_id
        assert event.resource_type == "tenant"
        assert event.detail.get("requested_action") == "publish"
        await session.rollback()
