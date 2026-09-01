"""Asking for a decision, and recording the one that was made.

**An approval is never created by a person.** It is raised when a run reaches an approval step,
in the same transaction that creates the task — the same rule tasks themselves keep. A route that
let somebody request an approval out of nowhere would be a way to demand a sign-off with no work
behind it, and nothing to check the sign-off against.

## Separation of duty is the whole point

The person who set the work going cannot be the person who approves it. This is enforced three
times over, and none of them is redundant:

* `guard.refuse_self_approval` refuses it with a sentence somebody can read;
* `decide()` refuses it before writing anything;
* `ck_approvals_not_self` refuses the row at all.

An approval that was not really a second pair of eyes is indistinguishable in the data from one
that was — which is precisely why the rule cannot live in one place.

## The task and the approval move together

Deciding writes both: the approval carries the decision, and 7.2's task carries the outcome that
finishes the run step. They are written in one transaction because a rejected approval on a task
still reading `pending` is a run nobody can explain, and the screens read both.

## What this module does not do

**It does not fire on a deadline.** `due_at` is stored and shown; the sweep that escalates an
overdue approval belongs with 7.4's scheduler and 7.5's notifications, and a column implying an
automatic escalation nothing performs would be worse than no column at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.core.logging import get_logger
from uboss.modules.approvals.models import Approval, ApprovalState
from uboss.modules.audit import service as audit
from uboss.modules.notifications import service as notify
from uboss.modules.runtime.models import Run
from uboss.modules.tasks import assignment
from uboss.modules.tasks.models import Task, TaskKind, TaskState

log = get_logger(__name__)

#: How a decision on the approval reads on the task it belongs to. One map rather than two
#: `if` chains, so the two records cannot disagree about what was decided.
OUTCOME_FOR: dict[str, str] = {
    ApprovalState.APPROVED: "approved",
    ApprovalState.REJECTED: "rejected",
    ApprovalState.CHANGES_REQUESTED: "changes_requested",
}


async def raise_for_task(
    session: AsyncSession,
    run: Run,
    task: Task,
    *,
    frozen_step: dict[str, Any],
    escalation_note: str | None,
) -> Approval | None:
    """The approval belonging to an approval task. Idempotent, like the task itself.

    Returns `None` for a task that is not an approval — the caller creates every task through one
    path, and a branch there would be a branch to keep in step with `_kind_of`.

    The requester is the person who started the run. For a scheduled run nobody started it, and
    there is then no author to separate the approver from; those raise no approval row and the
    task's own permission check is what governs them. That is honest: separation of duty is a
    statement about two people, and a run with one person in it cannot make it.
    """
    if task.kind != TaskKind.APPROVAL:
        return None
    if run.started_by_membership_id is None:
        log.info("approval_not_raised_no_requester", run_id=str(run.id))
        return None

    existing = await for_task(session, task.id)
    if existing is not None:
        return existing

    approval = Approval(
        tenant_id=run.tenant_id,
        run_id=run.id,
        run_step_id=task.run_step_id,
        task_id=task.id,
        requested_by_membership_id=run.started_by_membership_id,
        approver_membership_id=task.assignee_membership_id,
        question=_question(frozen_step),
        state=ApprovalState.PENDING,
        escalation_note=escalation_note,
        due_at=task.due_at,
    )
    session.add(approval)
    await session.flush()

    #  The approver learns a decision is waiting. Nobody else: an approval addressed to everybody
    #  is an approval nobody feels responsible for.
    if approval.approver_membership_id is not None:
        await notify.approval_requested(
            session,
            tenant_id=run.tenant_id,
            membership_id=approval.approver_membership_id,
            approval_id=approval.id,
            task_id=task.id,
            question=approval.question,
            requested_by=approval.requested_by_membership_id,
        )

    log.info(
        "approval_raised",
        approval_id=str(approval.id),
        run_id=str(run.id),
        has_approver=approval.approver_membership_id is not None,
    )
    return approval


async def for_task(session: AsyncSession, task_id: uuid.UUID) -> Approval | None:
    return (
        await session.execute(select(Approval).where(Approval.task_id == task_id))
    ).scalar_one_or_none()


async def decide(
    session: AsyncSession,
    context: SecurityContext,
    approval: Approval,
    *,
    state: str,
    reason: str | None,
) -> Approval:
    """Record the decision, with the person and the reason on it.

    Raises rather than writing when the decider is the requester. `guard.refuse_self_approval`
    should already have refused — this is the second of the three boundaries, and it exists so
    that a caller which forgot the guard still cannot produce a self-approval.
    """
    if approval.state in ApprovalState.closed():
        raise Conflict(
            "That approval has already been decided. Open it to see what was decided and by whom."
        )
    if state not in ApprovalState.decided():
        raise ValidationFailed(f"'{state}' is not a decision.")
    if state in ApprovalState.refusals() and not (reason or "").strip():
        raise ValidationFailed(
            "Say why. A refusal without a reason is a decision nobody can act on."
        )
    if context.membership_id == approval.requested_by_membership_id:
        raise PermissionDenied("You started this work, so somebody else has to approve it.")

    now = datetime.now(UTC)
    approval.state = state
    approval.reason = (reason or "").strip() or None
    approval.decided_by_membership_id = context.membership_id
    approval.decided_at = now
    approval.updated_at = now

    await audit.record(
        session,
        tenant_id=approval.tenant_id,
        action=f"approvals.{state}",
        resource_type="approval",
        resource_id=approval.id,
        actor=context,
        detail={
            "run_id": str(approval.run_id),
            "task_id": str(approval.task_id),
            "requested_by": str(approval.requested_by_membership_id),
        },
    )
    #  The person who asked, told what was decided. `raise_for` drops it if they decided it
    #  themselves — which separation of duty already forbids, but the check costs nothing and
    #  means no call site has to remember.
    await notify.approval_decided(
        session,
        tenant_id=approval.tenant_id,
        membership_id=approval.requested_by_membership_id,
        approval_id=approval.id,
        task_id=approval.task_id,
        state=state,
        reason=approval.reason,
        decided_by=context.membership_id,
    )

    await session.flush()
    log.info("approval_decided", approval_id=str(approval.id), state=state)
    return approval


async def escalate(
    session: AsyncSession,
    context: SecurityContext,
    approval: Approval,
    *,
    to_membership_id: uuid.UUID | None,
    note: str | None,
) -> Approval:
    """Put somebody else's name on a decision nobody is making.

    **The approval stays pending.** Escalating is not deciding, and a state that closed it would
    lose the fact that the question is still open. What changes is who is named and that it is on
    the record — which is what an escalation is for.
    """
    if approval.state in ApprovalState.closed():
        raise Conflict("That approval has already been decided.")
    if to_membership_id is None and not (note or "").strip():
        raise ValidationFailed("Say who this is going to, or why it is being escalated.")
    #  **The id has to be somebody here.** `escalated_to_membership_id` is a plain column with no
    #  foreign key, so another workspace's id would be written without complaint and then resolve
    #  to no name on every screen that read it — a decision addressed to somebody who does not
    #  exist here. `is_active` compares the tenant explicitly, so the answer does not depend on
    #  which database role happens to be connected.
    if to_membership_id is not None and not await assignment.is_active(
        session, to_membership_id, tenant_id=approval.tenant_id
    ):
        raise ValidationFailed("That person is not active in this workspace.")

    now = datetime.now(UTC)
    approval.escalated_to_membership_id = to_membership_id
    if note and note.strip():
        approval.escalation_note = note.strip()[:200]
    approval.escalated_at = now
    approval.updated_at = now

    await audit.record(
        session,
        tenant_id=approval.tenant_id,
        action="approvals.escalated",
        resource_type="approval",
        resource_id=approval.id,
        actor=context,
        detail={
            "to_membership_id": str(to_membership_id) if to_membership_id else None,
            "note": approval.escalation_note,
        },
    )
    #  The person it went to. Escalation is only useful if the new name learns about it.
    if to_membership_id is not None:
        await notify.raise_for(
            session,
            tenant_id=approval.tenant_id,
            membership_id=to_membership_id,
            category=notify.Category.APPROVAL_INPUT,
            event="approval.escalated",
            title="A decision was escalated to you",
            body=approval.escalation_note,
            deep_link=f"/todo?tab=approvals&task={approval.task_id}",
            dedupe_key=f"approval-escalated:{approval.id}",
            subject_type="approval",
            subject_id=approval.id,
            actor_membership_id=context.membership_id,
            action_required=True,
        )

    await session.flush()
    return approval


async def withdraw(
    session: AsyncSession,
    context: SecurityContext | None,
    approval: Approval,
    *,
    why: str,
) -> Approval:
    """The question stopped being asked — the run was cancelled, or the task was handed back.

    Not a rejection. Nobody said no, and a refusal nobody made would sit in somebody's record as
    though they had. Called by the task and run paths rather than by a route: withdrawing an
    approval that is still being asked about would be a way to skip it.
    """
    if approval.state in ApprovalState.closed():
        return approval

    approval.state = ApprovalState.WITHDRAWN
    approval.reason = why
    approval.updated_at = datetime.now(UTC)
    await session.flush()
    log.info("approval_withdrawn", approval_id=str(approval.id), why=why)
    return approval


async def open_count(session: AsyncSession, membership_id: uuid.UUID) -> int:
    """Approvals waiting on this person — what the Approvals tab counts.

    Counts the ones *addressed to them*, including any escalated to them. An approval waiting on
    nobody is not counted against a person who has not been asked.
    """
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Approval)
                .where(
                    Approval.state == ApprovalState.PENDING,
                    (Approval.approver_membership_id == membership_id)
                    | (Approval.escalated_to_membership_id == membership_id),
                )
            )
        ).scalar_one()
    )


async def withdraw_for_task(
    session: AsyncSession, task: Task, *, why: str
) -> Approval | None:
    """Close the approval belonging to a task that is no longer going to be decided."""
    if task.kind != TaskKind.APPROVAL:
        return None
    approval = await for_task(session, task.id)
    if approval is None:
        return None
    return await withdraw(session, None, approval, why=why)


async def withdraw_for_run(
    session: AsyncSession, run_id: uuid.UUID, *, why: str
) -> int:
    """Every pending approval on a run that has stopped. Returns how many were closed."""
    approvals = list(
        (
            await session.execute(
                select(Approval).where(
                    Approval.run_id == run_id, Approval.state == ApprovalState.PENDING
                )
            )
        )
        .scalars()
        .all()
    )
    for approval in approvals:
        await withdraw(session, None, approval, why=why)
    return len(approvals)


def _question(frozen_step: dict[str, Any]) -> str | None:
    """§9's Approval column, as the author wrote it.

    Nothing is generated. A step whose author left it empty gets no question rather than one this
    code invented — and the task's own instructions still say what the work was.
    """
    value = str(frozen_step.get("approval") or "").strip()
    return value or None


def outcome_for(state: str) -> str:
    """How a decision reads on the task. Raises rather than guessing at an unknown state."""
    outcome = OUTCOME_FOR.get(state)
    if outcome is None:
        raise ValidationFailed(f"'{state}' is not a decision.")
    return outcome


def is_open(task: Task) -> bool:
    """Whether the task behind an approval can still be acted on."""
    return task.state in TaskState.open()
