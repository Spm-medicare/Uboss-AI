"""Publishing a Job.

The separation of duty is the same rule as the Objective's and is tested there in full; what this
suite adds is the warnings a *method* produces, which are different questions — does an unattended
step say what to do when its input is missing, does a step reference an input nobody defined, and
is a schedule about to start firing something nobody has approved.
"""

from __future__ import annotations

import uuid
from datetime import time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy import service as hierarchy
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.jobs import publish, schedule_service, service
from uboss.modules.jobs.models import JobStatus
from uboss.modules.jobs.schemas import (
    AssignmentRuleInput,
    JobCreate,
    JobInputDefinition,
    JobStepInput,
    JobUpdate,
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


async def _complete_job(
    session: AsyncSession, context: SecurityContext, approver_id: uuid.UUID
) -> uuid.UUID:
    """A job with everything the warnings look for, so a clean one produces none."""
    job = await service.create(session, context, JobCreate(name="Prepare a quotation"))
    await session.flush()
    await service.update(
        session,
        context,
        job.id,
        JobUpdate(
            completion_evidence="The quotation is in the CRM with a number.",
            approver_membership_id=approver_id,
            steps=[
                JobStepInput(
                    what_exact_work="Read the enquiry",
                    how_exact_method="Extract",
                    if_missing_or_wrong="Ask the user",
                    mode="hybrid",
                )
            ],
            assignment_rules=[
                AssignmentRuleInput(who_type="role", target_label="Sales coordinator")
            ],
            inputs=[JobInputDefinition(name="Enquiry email", input_type="Email")],
            expected_version=job.version,
        ),
    )
    await session.flush()
    return job.id


async def test_a_complete_job_produces_no_warnings(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The baseline. Without this, a warning that never fires would look like one that works."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)

        summary = await publish.summary(session, context, job_id)
        assert summary.warnings == []
        assert summary.can_submit
        await session.rollback()


async def test_an_automated_step_without_a_fallback_is_flagged(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The failure mode of every automation: it does something wrong rather than stopping."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)
        job = await service.read(session, context, job_id)

        await service.update(
            session,
            context,
            job_id,
            JobUpdate(
                steps=[
                    JobStepInput(what_exact_work="Post the invoice", mode="ai_agent"),
                ],
                expected_version=job.version,
            ),
        )
        await session.flush()

        summary = await publish.summary(session, context, job_id)
        codes = {warning.code for warning in summary.warnings}
        assert "agent_step_without_fallback" in codes
        #  Flagged, not blocked.
        assert summary.can_submit
        await session.rollback()


async def test_a_step_referencing_an_undefined_input_is_flagged(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Only quoted names are matched — a broader rule would flag ordinary prose."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)
        job = await service.read(session, context, job_id)

        await service.update(
            session,
            context,
            job_id,
            JobUpdate(
                steps=[
                    JobStepInput(
                        what_exact_work='Check the price against the “Contract price list”',
                        if_missing_or_wrong="Stop and report",
                    )
                ],
                expected_version=job.version,
            ),
        )
        await session.flush()

        summary = await publish.summary(session, context, job_id)
        flagged = next(
            w for w in summary.warnings if w.code == "undefined_input_referenced"
        )
        assert "Contract price list" in flagged.message
        await session.rollback()


async def test_an_agent_reading_personal_data_is_flagged(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Reading is allowed and worth saying out loud. Writing is refused outright elsewhere."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)
        job = await service.read(session, context, job_id)

        await service.update(
            session,
            context,
            job_id,
            JobUpdate(
                inputs=[
                    JobInputDefinition(
                        name="Employee record",
                        input_type="System Data",
                        classification="personal_data",
                        ai_access="read",
                    )
                ],
                expected_version=job.version,
            ),
        )
        await session.flush()

        summary = await publish.summary(session, context, job_id)
        assert "ai_reads_personal_data" in {w.code for w in summary.warnings}
        await session.rollback()


async def test_a_waiting_schedule_says_it_will_start(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Auto-run set before publishing means it starts the moment approval lands.

    Which somebody may well mean — and should read before pressing approve rather than after.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)

        await schedule_service.set_schedule(
            session,
            context,
            job_id,
            {
                "auto_run": True,
                "timezone": "Asia/Kolkata",
                "frequency": "daily",
                "at_time": time(9, 0),
            },
            expected_version=None,
        )
        await session.flush()

        summary = await publish.summary(session, context, job_id)
        codes = {warning.code for warning in summary.warnings}
        assert "schedule_waiting" in codes
        assert "schedule_not_pinned" in codes
        assert summary.schedule_summary is not None
        assert "Asia/Kolkata" in summary.schedule_summary
        await session.rollback()


async def test_a_second_person_approves_and_the_method_is_frozen(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The snapshot holds the schedule too.

    A version that did not record when it ran could not answer "why did this fire at 3 a.m. in
    March", which is the question a clock change produces.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, author, colleague)

        await schedule_service.set_schedule(
            session,
            author,
            job_id,
            {
                "auto_run": True,
                "timezone": "Europe/London",
                "frequency": "daily",
                "at_time": time(9, 0),
            },
            expected_version=None,
        )
        await session.flush()

        job = await service.read(session, author, job_id)
        await publish.submit(session, author, job_id, job.version)
        await session.flush()

        approver = await _context(session, left, membership_id=colleague)
        summary = await publish.summary(session, approver, job_id)
        assert summary.can_approve

        version = await publish.publish(session, approver, job_id, summary.version)
        await session.flush()

        assert version.version_no == 1
        assert version.approved_by_membership_id == colleague
        assert len(version.snapshot["steps"]) == 1
        assert version.snapshot["schedule"]["timezone"] == "Europe/London"
        assert len(version.snapshot["inputs"]) == 1
        assert len(version.snapshot["assignment_rules"]) == 1

        published = await service.read(session, approver, job_id)
        assert published.status == JobStatus.PUBLISHED
        assert not published.is_editable
        await session.rollback()


async def test_the_submitter_cannot_approve_their_own_job(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """PLAN §14, held identically to the Objective's — the same guard, not a second copy."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, context.membership_id)

        job = await service.read(session, context, job_id)
        await publish.submit(session, context, job_id, job.version)
        await session.flush()

        refreshed = await service.read(session, context, job_id)
        with pytest.raises(PermissionDenied):
            await publish.publish(session, context, job_id, refreshed.version)
        await session.rollback()


async def test_a_job_with_no_steps_cannot_be_submitted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Publishing an empty method would put something in the runtime that does nothing."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job = await service.create(session, context, JobCreate(name="Empty"))
        await session.flush()
        await service.update(
            session,
            context,
            job.id,
            JobUpdate(approver_membership_id=colleague, expected_version=job.version),
        )
        await session.flush()

        current = await service.read(session, context, job.id)
        with pytest.raises(ValidationFailed) as refused:
            await publish.submit(session, context, job.id, current.version)
        assert "no method" in str(refused.value).lower()
        await session.rollback()
