"""Publishing an objective, and the two rules that make it mean something.

PLAN §7: *"Approval creates immutable ObjectiveVersion."* §14 separates the author from the
approver. Both are tested against the service rather than the screen, because both have to hold
for an API call, a workflow step and a Copilot proposal alike — a check the interface performs is
a check a `curl` gets around.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy import service as hierarchy
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.objectives import graph, publish, service
from uboss.modules.objectives.models import ObjectiveStatus, ObjectiveVersion
from uboss.modules.objectives.schemas import (
    CurrentStepInput,
    ObjectiveCreate,
    ObjectiveUpdate,
)

pytestmark = pytest.mark.anyio


async def _context(
    session: AsyncSession,
    workspace: Workspace,
    *,
    membership_id: uuid.UUID | None = None,
    actions: tuple[str, ...] = (),
) -> SecurityContext:
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

    target = membership_id or workspace.membership_id
    membership = await session.get(Membership, target)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = hierarchy._now()
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=target,
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


async def _ready_to_submit(
    session: AsyncSession, context: SecurityContext, approver_id: uuid.UUID
) -> uuid.UUID:
    """An objective with a plan and a named approver — the state submitting requires."""
    objective = await service.create(session, context, ObjectiveCreate(title="Quotations"))
    await session.flush()
    await service.update(
        session,
        context,
        objective.id,
        ObjectiveUpdate(
            expected_result="Quotations out the same day",
            success_measures="Median turnaround under 4 hours",
            approver_membership_id=approver_id,
            current_steps=[CurrentStepInput(what_exact_work="Copy the line items")],
            expected_version=objective.version,
        ),
    )
    await session.flush()
    await graph.add(
        session,
        context,
        objective.id,
        kind="human",
        title="Check the price",
        responsible_role="Sales coordinator",
    )
    await graph.add(
        session,
        context,
        objective.id,
        kind="approval",
        title="Approve the quotation",
        responsible_role="Sales manager",
    )
    await session.flush()
    return objective.id


async def test_the_summary_says_whose_turn_it_is(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Written by the server, so two screens cannot each conclude it is the other's turn."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        approver = colleague
        objective_id = await _ready_to_submit(session, context, approver)

        summary = await publish.summary(session, context, objective_id)
        assert summary.can_submit
        assert not summary.can_approve
        assert "send for approval" in summary.next_action.lower()
        await session.rollback()


async def test_warnings_are_shown_and_never_block(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Each of these is a choice an organisation may make on purpose.

    Blocking would be the product overruling a decision that is theirs. Hiding would be the
    product deciding it does not matter. Showing is the only honest option.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        approver = colleague

        objective = await service.create(session, context, ObjectiveCreate(title="Thin"))
        await session.flush()
        await service.update(
            session,
            context,
            objective.id,
            ObjectiveUpdate(
                expected_result="Something",
                approver_membership_id=approver,
                current_steps=[CurrentStepInput(what_exact_work="Do it")],
                expected_version=objective.version,
            ),
        )
        #  A plan with one agent step: no approval in it, nobody named, no success measure.
        await graph.add(session, context, objective.id, kind="ai_agent", title="Do the thing")
        await session.flush()

        summary = await publish.summary(session, context, objective.id)
        codes = {warning.code for warning in summary.warnings}
        assert "no_approval_step" in codes
        assert "no_responsible_role" in codes
        assert "no_measures" in codes

        #  Warnings and all, it can still be submitted.
        assert summary.can_submit
        await publish.submit(session, context, objective.id, summary.version)
        await session.flush()
        await session.rollback()


async def test_an_objective_with_no_plan_cannot_be_submitted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Publishing an empty plan would put something in the runtime that does nothing."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        approver = colleague

        objective = await service.create(session, context, ObjectiveCreate(title="Empty"))
        await session.flush()
        await service.update(
            session,
            context,
            objective.id,
            ObjectiveUpdate(
                approver_membership_id=approver, expected_version=objective.version
            ),
        )
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await publish.submit(session, context, objective.id, objective.version)
        assert "no plan" in str(refused.value).lower()
        await session.rollback()


async def test_the_submitter_cannot_approve_their_own_work(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """PLAN §14's separation of duty, held in the service.

    The submitter here also holds `publish` and is the named approver — every permission check
    passes. What refuses them is that they are the person who submitted it, which is the entire
    point of the rule.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        objective_id = await _ready_to_submit(session, context, context.membership_id)

        objective = await service.read(session, context, objective_id)
        await publish.submit(session, context, objective_id, objective.version)
        await session.flush()

        refreshed = await service.read(session, context, objective_id)
        with pytest.raises(PermissionDenied) as refused:
            await publish.publish(session, context, objective_id, refreshed.version)
        assert "someone else" in str(refused.value).lower()

        #  And nothing was published.
        assert (
            await session.execute(
                select(ObjectiveVersion).where(
                    ObjectiveVersion.objective_id == objective_id
                )
            )
        ).scalar_one_or_none() is None
        await session.rollback()


async def test_a_second_person_approves_and_the_version_is_frozen(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The whole journey — PLAN §6's "Immutable Published version/card".

    The snapshot holds both the current process and the plan. A version that recorded only the
    plan could not answer "what were we doing before", which is where every review of a published
    objective starts.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left, actions=("edit_draft", "publish"))
        approver_id = colleague
        objective_id = await _ready_to_submit(session, author, approver_id)

        objective = await service.read(session, author, objective_id)
        await publish.submit(session, author, objective_id, objective.version)
        await session.flush()

        approver = await _context(session, left, membership_id=approver_id)
        summary = await publish.summary(session, approver, objective_id)
        assert summary.can_approve
        assert "waiting for you" in summary.next_action.lower()

        version = await publish.publish(session, approver, objective_id, summary.version)
        await session.flush()

        assert version.version_no == 1
        assert version.approved_by_membership_id == approver_id
        assert version.published_by_membership_id == author.membership_id
        assert len(version.snapshot["plan"]) == 2
        assert len(version.snapshot["current_process"]) == 1

        published = await service.read(session, approver, objective_id)
        assert published.status == ObjectiveStatus.PUBLISHED
        assert published.published_version_id == version.id
        #  And the form is now read-only. A published version is immutable, so the draft it came
        #  from cannot keep being edited underneath it.
        assert not published.is_editable
        await session.rollback()


async def test_approving_a_version_you_did_not_read_is_refused(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The difference between approving what you read and approving what it has become."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left, actions=("edit_draft", "publish"))
        approver_id = colleague
        objective_id = await _ready_to_submit(session, author, approver_id)

        objective = await service.read(session, author, objective_id)
        await publish.submit(session, author, objective_id, objective.version)
        await session.flush()

        approver = await _context(session, left, membership_id=approver_id)
        with pytest.raises(Conflict):
            await publish.publish(session, approver, objective_id, objective.version)
        await session.rollback()


async def test_somebody_who_is_not_the_named_approver_is_refused(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Holding `publish` is not the same as being asked.

    The message says which it is, because "you do not have permission" would send somebody to an
    administrator who cannot help them.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left, actions=("edit_draft", "publish"))
        approver_id = colleague
        objective_id = await _ready_to_submit(session, author, approver_id)

        objective = await service.read(session, author, objective_id)
        await publish.submit(session, author, objective_id, objective.version)
        await session.flush()

        #  A third person, with the same permissions and no invitation.
        #  A third person, with the same permissions and no invitation. The workspace's
        #  original member is not the named approver here, so they serve.
        other = await _context(session, left)
        refreshed = await service.read(session, other, objective_id)

        with pytest.raises(ValidationFailed) as refused:
            await publish.publish(session, other, objective_id, refreshed.version)
        assert "named approver" in str(refused.value)
        await session.rollback()


async def test_withdrawing_clears_the_submitter(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Otherwise a withdrawn-and-resubmitted objective stays barred from the first submitter.

    Which is not what separation of duty is for: the rule is about the person who submitted *this*
    submission, not anyone who ever touched it.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left, actions=("edit_draft", "publish"))
        approver_id = colleague
        objective_id = await _ready_to_submit(session, author, approver_id)

        objective = await service.read(session, author, objective_id)
        await publish.submit(session, author, objective_id, objective.version)
        await session.flush()

        withdrawn = await service.read(session, author, objective_id)
        result = await publish.withdraw(session, author, objective_id, withdrawn.version)
        await session.flush()

        assert result.status == ObjectiveStatus.NEEDS_REVIEW
        assert result.submitted_by_membership_id is None
        #  And it is editable again, which is the reason somebody withdraws.
        assert result.is_editable
        await session.rollback()


async def test_publishing_needs_a_recent_password(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """`publish` is high-risk (PLAN line 366). Holding it is not the same as holding it now."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left, actions=("edit_draft", "publish"))
        approver_id = colleague
        objective_id = await _ready_to_submit(session, author, approver_id)

        objective = await service.read(session, author, objective_id)
        await publish.submit(session, author, objective_id, objective.version)
        await session.flush()

        stale = await _context(session, left, membership_id=approver_id)
        without_proof = SecurityContext(
            tenant_id=stale.tenant_id,
            user_id=stale.user_id,
            membership_id=stale.membership_id,
            session_id=stale.session_id,
            email=stale.email,
            display_name=stale.display_name,
            roles=stale.roles,
            granted_actions=stale.granted_actions,
            org_node_id=stale.org_node_id,
            policy_grants=stale.policy_grants,
        )
        refreshed = await service.read(session, stale, objective_id)

        with pytest.raises(PermissionDenied):
            await publish.publish(session, without_proof, objective_id, refreshed.version)
        await session.rollback()
