"""Approvals — the rules that decide whether a sign-off means anything.

An approval that was not really a second pair of eyes is **indistinguishable in the data** from
one that was. That single fact is why separation of duty is enforced three times over, and why
two of the tests below check the same rule at two different boundaries rather than trusting one.

Six properties:

* an approval step raises an approval, with the requester, the approver and the question on it;
* the person who started the work cannot approve it — refused by the service;
* and refused by the database, when something writes the row without asking the service;
* a refusal must say why, at both boundaries;
* deciding writes the approval *and* the task *and* the run step, or none of them;
* a run that stops withdraws its approvals — withdrawn, never rejected, because nobody said no.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.approvals import service as approvals
from uboss.modules.approvals.models import Approval, ApprovalState
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.runtime import service as runtime
from uboss.modules.runtime.models import Run, RunStep, RunTrigger, StepState
from uboss.modules.tasks import service as tasks
from uboss.modules.tasks.models import TaskKind, TaskOutcome, TaskState

pytestmark = pytest.mark.anyio


async def _context(
    session: AsyncSession, workspace: Workspace, membership_id: uuid.UUID | None = None
) -> SecurityContext:
    """The context the API would build, from a membership's real roles — never a faked one."""
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


async def _approval_run(
    session: AsyncSession,
    workspace: Workspace,
    *,
    approver: uuid.UUID | None,
    escalation_to: str | None = None,
) -> tuple[Run, RunStep, SecurityContext]:
    """A run whose first step is an approval, taken to the point where it waits."""
    context = await _context(session, workspace)
    job_id = uuid.uuid4()
    version_id = uuid.uuid4()
    rules = (
        [{"position": 1, "who_type": "user", "target_id": str(approver)}]
        if approver is not None
        else []
    )
    await session.execute(
        text(
            """
            INSERT INTO jobs (id, tenant_id, name, status, owner_membership_id)
            VALUES (:id, :tenant, 'Payment release', 'draft', :owner)
            """
        ),
        {"id": job_id, "tenant": workspace.tenant_id, "owner": workspace.membership_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO job_versions (id, tenant_id, job_id, snapshot, name, correlation_id)
            VALUES (:id, :tenant, :job, CAST(:snapshot AS jsonb), 'Payment release', 'test')
            """
        ),
        {
            "id": version_id,
            "tenant": workspace.tenant_id,
            "job": job_id,
            "snapshot": json.dumps(
                {
                    "job": {"escalation_to": escalation_to},
                    "steps": [
                        {
                            "position": 1,
                            "mode": "human",
                            "what_exact_work": "Release the payment",
                            "approval": "Finance director signs off over ₹5,00,000",
                        }
                    ],
                    "assignment_rules": rules,
                }
            ),
        },
    )
    await session.execute(
        text(
            "UPDATE jobs SET status = 'published', published_version_id = :v WHERE id = :id"
        ),
        {"v": version_id, "id": job_id},
    )

    started = await runtime.start(
        session,
        tenant_id=workspace.tenant_id,
        job_version_id=version_id,
        trigger=RunTrigger.MANUAL,
        actor=context,
    )
    run = (
        await session.execute(select(Run).where(Run.id == started.run_id))
    ).scalar_one()
    step = await runtime.next_step(session, run.id)
    assert step is not None
    await runtime.begin_step(session, run, step)
    await runtime.wait_for_person(session, run, step)
    return run, step, context


async def test_an_approval_step_raises_an_approval_with_its_question(
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The approval carries who asked, who may decide, and the question in the author's words.

    Those four facts have no column on a task and no business acquiring one — they are meaningless
    for the other two kinds of task, and they are exactly what an audit asks first.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, _starter = await _approval_run(
                session, left, approver=colleague, escalation_to="Head of Finance"
            )
            task = await tasks.create_for_step(session, run, step)
            assert task.kind == TaskKind.APPROVAL

            approval = await approvals.for_task(session, task.id)
            assert approval is not None
            #  The requester is whoever set the work going, which is what separation of duty is
            #  measured against.
            assert approval.requested_by_membership_id == left.membership_id
            assert approval.approver_membership_id == colleague
            assert approval.question == "Finance director signs off over ₹5,00,000"
            #  Free text, copied rather than resolved: the Job's field is a label a person typed.
            assert approval.escalation_note == "Head of Finance"
            assert approval.state == ApprovalState.PENDING


async def test_the_person_who_started_the_work_cannot_approve_it(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**The rule the table exists for.**

    Refused by the service before anything is written — so a caller that reached `decide` without
    the route's guard still cannot record a self-approval.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            #  Assigned to the same person who starts the run: exactly the shape a Job written
            #  carelessly produces.
            run, step, context = await _approval_run(
                session, left, approver=left.membership_id
            )
            task = await tasks.create_for_step(session, run, step)
            approval = await approvals.for_task(session, task.id)
            assert approval is not None

            with pytest.raises(PermissionDenied):
                await approvals.decide(
                    session, context, approval, state="approved", reason=None
                )

            #  And through the task path, which is the one the Approvals tab actually uses.
            with pytest.raises(PermissionDenied):
                await tasks.complete(
                    session, context, task, outcome=TaskOutcome.APPROVED, note=None
                )
            assert approval.state == ApprovalState.PENDING
            assert task.state == TaskState.PENDING


async def test_the_database_refuses_a_self_approval_written_directly(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The second boundary, and it is not redundant.

    The service is what a person sees. `ck_approvals_not_self` is what holds when the row is
    written by a script, a migration, or a route somebody adds next year without reading the
    module. `CLAUDE.md` requires the same doubling of authorization and RLS.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, _starter = await _approval_run(
                session, left, approver=left.membership_id
            )
            task = await tasks.create_for_step(session, run, step)
            approval = await approvals.for_task(session, task.id)
            assert approval is not None

            with pytest.raises(DatabaseError):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            """
                            UPDATE approvals
                            SET state = 'approved', decided_at = now(),
                                decided_by_membership_id = requested_by_membership_id
                            WHERE id = :id
                            """
                        ),
                        {"id": approval.id},
                    )


async def test_a_refusal_must_say_why(
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """At both boundaries again, for the same reason.

    "Changes requested" without the changes is worse than silence: it stops the work and tells
    nobody what would restart it.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, _starter = await _approval_run(session, left, approver=colleague)
            task = await tasks.create_for_step(session, run, step)
            approval = await approvals.for_task(session, task.id)
            assert approval is not None
            deciding = await _context(session, left, colleague)

            with pytest.raises(ValidationFailed):
                await approvals.decide(
                    session, deciding, approval, state="rejected", reason="   "
                )
            with pytest.raises(ValidationFailed):
                await approvals.decide(
                    session, deciding, approval, state="changes_requested", reason=None
                )

            with pytest.raises(DatabaseError):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            """
                            UPDATE approvals
                            SET state = 'rejected', reason = NULL, decided_at = now(),
                                decided_by_membership_id = :m
                            WHERE id = :id
                            """
                        ),
                        {"id": approval.id, "m": colleague},
                    )


async def test_deciding_writes_the_approval_the_task_and_the_step_together(
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """One decision, three records, one transaction.

    A rejected approval on a task still reading `pending` is a run nobody can explain, and the
    screens read all three.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, _starter = await _approval_run(session, left, approver=colleague)
            task = await tasks.create_for_step(session, run, step)
            deciding = await _context(session, left, colleague)

            await tasks.complete(
                session,
                deciding,
                task,
                outcome=TaskOutcome.REJECTED,
                note="Over the limit without a purchase order.",
            )

            approval = await approvals.for_task(session, task.id)
            assert approval is not None
            assert approval.state == ApprovalState.REJECTED
            assert approval.decided_by_membership_id == colleague
            assert approval.reason == "Over the limit without a purchase order."

            assert task.state == TaskState.DONE
            assert task.outcome == TaskOutcome.REJECTED

            refreshed = await session.get(RunStep, step.id)
            assert refreshed is not None
            #  The step finished carrying the decision — a rejection is an answer, not a failure
            #  of the step. What the run does about it is the Job's business, not the runtime's.
            assert refreshed.state == StepState.SUCCEEDED
            assert refreshed.result is not None
            assert refreshed.result["outcome"] == TaskOutcome.REJECTED


async def test_a_cancelled_run_withdraws_its_approvals(
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """**Withdrawn, never rejected.**

    Nobody said no — the question stopped being asked. A refusal nobody made would sit in
    somebody's record as though they had made it, which is a lie the data cannot later correct.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _approval_run(session, left, approver=colleague)
            task = await tasks.create_for_step(session, run, step)

            await runtime.cancel(session, context, run, reason="The supplier withdrew.")

            approval = await approvals.for_task(session, task.id)
            assert approval is not None
            assert approval.state == ApprovalState.WITHDRAWN
            assert approval.decided_by_membership_id is None
            assert approval.decided_at is None
            #  Nothing is counted against the person who was asked and never answered.
            assert await approvals.open_count(session, colleague) == 0


async def test_an_escalation_leaves_the_question_open(
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
    third_person: uuid.UUID,
) -> None:
    """Escalating is not deciding.

    A state that closed the approval would lose the fact that the question is still open — which
    is the entire reason somebody escalated it.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _approval_run(session, left, approver=colleague)
            task = await tasks.create_for_step(session, run, step)
            approval = await approvals.for_task(session, task.id)
            assert approval is not None

            await approvals.escalate(
                session,
                context,
                approval,
                to_membership_id=third_person,
                note="No answer in three days.",
            )

            assert approval.state == ApprovalState.PENDING
            assert approval.escalated_to_membership_id == third_person
            assert approval.escalated_at is not None
            #  It now counts for both of them: the person asked, and the person it went to.
            assert await approvals.open_count(session, colleague) == 1
            assert await approvals.open_count(session, third_person) == 1

            #  And the person it was escalated to may decide it.
            deciding = await _context(session, left, third_person)
            await approvals.decide(
                session, deciding, approval, state="approved", reason=None
            )
            assert approval.state == ApprovalState.APPROVED
            assert (
                await session.scalar(
                    select(Approval.decided_by_membership_id).where(
                        Approval.id == approval.id
                    )
                )
                == third_person
            )


async def test_an_approval_cannot_be_escalated_to_another_workspace(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**Found live, not by reasoning about it.**

    `escalated_to_membership_id` is a plain column: the memberships table is reached through
    row-level security rather than a foreign key, so nothing in the schema stops another
    workspace's id being written there. It went in happily, and then resolved to no name on every
    screen that read it — a decision addressed to somebody who does not exist here.

    `is_active` queries under the bound tenant, so the other workspace's member simply is not
    found. The refusal says so in the same words reassignment and delegation already use.
    """
    left, right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _approval_run(
                session, left, approver=left.membership_id
            )
            task = await tasks.create_for_step(session, run, step)
            approval = await approvals.for_task(session, task.id)
            assert approval is not None

            with pytest.raises(ValidationFailed):
                await approvals.escalate(
                    session,
                    context,
                    approval,
                    to_membership_id=right.membership_id,
                    note=None,
                )
            assert approval.escalated_to_membership_id is None
            assert approval.escalated_at is None
