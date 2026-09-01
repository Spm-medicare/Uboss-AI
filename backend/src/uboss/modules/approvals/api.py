"""Approvals, over HTTP — §11's Approvals tab and the decision behind it.

**There is no `POST /approvals`.** An approval is raised when a run reaches an approval step; a
route that created one would be a way to demand a sign-off with no work behind it and nothing to
check the sign-off against.

## Deciding goes through the task

`POST /approvals/{id}/decide` is the Approvals tab's own verb, and it completes the **task** — the
same path `POST /tasks/{id}/complete` takes, with the same permission checks, the same run step
finished and the same Temporal signal. Two routes writing two different halves of one decision is
how a rejected approval ends up on a task that still says `pending`.

## Separation of duty, refused three times

`guard.refuse_self_approval` here, `service.decide` in the domain, `ck_approvals_not_self` in the
database. An approval that was not really a second pair of eyes looks exactly like one that was,
so the rule cannot live in one place.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.dependencies import CurrentContext, SessionDep, SettingsDep
from uboss.core.errors import NotFound, PermissionDenied
from uboss.core.idempotency import require_idempotency_key
from uboss.core.logging import get_logger
from uboss.core.permissions import Action
from uboss.db.base import bind_tenant
from uboss.modules.approvals import service
from uboss.modules.approvals.models import Approval, ApprovalState
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.runtime import temporal
from uboss.modules.runtime.models import Run
from uboss.modules.tasks import service as tasks
from uboss.modules.tasks.models import Task

log = get_logger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalRead(BaseModel):
    """One decision, as the Approvals tab reads it."""

    id: uuid.UUID
    run_id: uuid.UUID
    task_id: uuid.UUID
    job_id: uuid.UUID | None = None
    #: What the Job's author wrote in §9's Approval column. Null when they left it empty — the
    #: task's own instructions still say what the work was.
    question: str | None = None
    title: str
    state: str
    requested_by_membership_id: uuid.UUID
    requested_by_name: str | None = None
    approver_membership_id: uuid.UUID | None = None
    approver_name: str | None = None
    reason: str | None = None
    decided_by_name: str | None = None
    decided_at: str | None = None
    due_at: str | None = None
    escalation_note: str | None = None
    escalated_to_name: str | None = None
    escalated_at: str | None = None
    created_at: str
    #: Whether the person asking may decide it. False for the requester — separation of duty —
    #: so the screen shows the reason rather than a button that always refuses.
    may_decide: bool = False


class ApprovalCounts(BaseModel):
    waiting_on_me: int


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `approved`, `rejected` or `changes_requested`.
    state: str
    #: Required for a refusal. Enforced by the service and by a check constraint.
    reason: str | None = Field(default=None, max_length=4000)


class Escalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Optional, because a Job's `escalation_to` is free text and there may be no membership to
    #: name. One of the two must be given.
    to_membership_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=200)


@router.get("/counts", summary="How many decisions are waiting on me")
async def counts(session: SessionDep, context: CurrentContext) -> ApprovalCounts:
    await guard.authorise(session, context, Action.VIEW)
    return ApprovalCounts(
        waiting_on_me=await service.open_count(session, context.membership_id)
    )


@router.get("", summary="Approvals in this workspace")
async def list_approvals(
    session: SessionDep,
    context: CurrentContext,
    mine: bool = True,
    state: str | None = None,
    run_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ApprovalRead]:
    """`mine` is scoped by the query, not by the screen.

    A filter the frontend applies is a filter somebody can remove with a query parameter.
    """
    await guard.authorise(session, context, Action.VIEW)

    query = select(Approval).order_by(Approval.created_at.desc()).limit(limit)
    if mine:
        query = query.where(
            (Approval.approver_membership_id == context.membership_id)
            | (Approval.escalated_to_membership_id == context.membership_id)
        )
    if state is not None:
        query = query.where(Approval.state == state)
    if run_id is not None:
        query = query.where(Approval.run_id == run_id)

    rows = list((await session.execute(query)).scalars().all())
    return await read_many(session, context, rows)


@router.get("/{approval_id}", summary="One approval")
async def read_approval(
    approval_id: uuid.UUID, session: SessionDep, context: CurrentContext
) -> ApprovalRead:
    await guard.authorise(session, context, Action.VIEW)
    approval = await _approval(session, approval_id)
    return (await read_many(session, context, [approval]))[0]


@router.post("/{approval_id}/decide", summary="Approve, reject or ask for changes")
async def decide(
    approval_id: uuid.UUID,
    body: Decision,
    session: SessionDep,
    settings: SettingsDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ApprovalRead:
    """Record the decision, finish the task and the step, then wake the run.

    Goes through `tasks.complete` rather than writing the approval alone: that is what finishes
    the run step and lets the workflow continue, and a decision recorded without it would leave a
    decided approval on a run still waiting for one.
    """
    await guard.authorise(session, context, Action.APPROVE)
    approval = await _approval(session, approval_id)
    task = await _task(session, approval)

    #  Not "may they approve things" but "may they approve *this*": the person who set the work
    #  going cannot be the one who signs it off.
    await guard.refuse_self_approval(
        session,
        context,
        submitted_by_membership_id=approval.requested_by_membership_id,
        resource=guard.Resource(type="approval", id=approval.id),
    )
    if (
        approval.approver_membership_id is not None
        and approval.approver_membership_id != context.membership_id
        and approval.escalated_to_membership_id != context.membership_id
    ):
        #  Asked of somebody specific. Holding `approve` over a workspace does not make somebody
        #  else's decision yours to make.
        raise PermissionDenied("That decision was asked of somebody else.")

    await tasks.complete(
        session,
        context,
        task,
        outcome=service.outcome_for(body.state),
        note=body.reason,
    )
    workflow_id = await _workflow_id(session, approval.run_id)
    await session.commit()
    await bind_tenant(session, context.tenant_id)

    await temporal.wake_run(settings, workflow_id)
    return await _one(session, context, approval_id)


@router.post("/{approval_id}/escalate", summary="Put somebody else on a decision")
async def escalate(
    approval_id: uuid.UUID,
    body: Escalation,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ApprovalRead:
    """The approval stays pending. Escalating is not deciding.

    Needs `assign`, not `approve`: moving a decision to somebody else is a statement about who
    does the work, and somebody who may approve is not automatically somebody who may reroute.
    """
    await guard.authorise(
        session,
        context,
        Action.ASSIGN,
        resource=guard.Resource(type="approval", id=approval_id),
    )
    approval = await _approval(session, approval_id)

    await service.escalate(
        session,
        context,
        approval,
        to_membership_id=body.to_membership_id,
        note=body.note,
    )
    await session.commit()
    await bind_tenant(session, context.tenant_id)
    return await _one(session, context, approval_id)


# ── internals ────────────────────────────────────────────────────────────────────────────


async def _approval(session: AsyncSession, approval_id: uuid.UUID) -> Approval:
    approval = (
        await session.execute(select(Approval).where(Approval.id == approval_id))
    ).scalar_one_or_none()
    if approval is None:
        #  Row-level security has already hidden another workspace's, so "not yours" and "does
        #  not exist" are one answer.
        raise NotFound("That approval does not exist.")
    return approval


async def _task(session: AsyncSession, approval: Approval) -> Task:
    task = (
        await session.execute(select(Task).where(Task.id == approval.task_id))
    ).scalar_one_or_none()
    if task is None:
        raise NotFound("The task this approval belongs to no longer exists.")
    return task


async def _workflow_id(session: AsyncSession, run_id: uuid.UUID) -> str | None:
    run = (
        await session.execute(select(Run).where(Run.id == run_id))
    ).scalar_one_or_none()
    return run.workflow_id if run is not None else None


async def read_many(
    session: AsyncSession, context: CurrentContext, approvals: list[Approval]
) -> list[ApprovalRead]:
    """Approvals as the wire sees them, names filled in, one query per lookup.

    Public because the task detail embeds an approval, and a second implementation of this
    mapping is a second place for `may_decide` to be computed differently from the route that
    enforces it.
    """
    if not approvals:
        return []

    tasks_by_id = {
        task.id: task
        for task in (
            await session.execute(
                select(Task).where(Task.id.in_([row.task_id for row in approvals]))
            )
        )
        .scalars()
        .all()
    }
    runs_by_id = {
        run.id: run
        for run in (
            await session.execute(
                select(Run).where(Run.id.in_([row.run_id for row in approvals]))
            )
        )
        .scalars()
        .all()
    }
    names = await _names(
        session,
        [row.requested_by_membership_id for row in approvals]
        + [row.approver_membership_id for row in approvals]
        + [row.decided_by_membership_id for row in approvals]
        + [row.escalated_to_membership_id for row in approvals],
    )

    return [
        ApprovalRead(
            id=row.id,
            run_id=row.run_id,
            task_id=row.task_id,
            job_id=runs_by_id[row.run_id].job_id if row.run_id in runs_by_id else None,
            question=row.question,
            title=(
                tasks_by_id[row.task_id].title
                if row.task_id in tasks_by_id
                #  Never a made-up title. A task that has gone says so.
                else "This approval's task no longer exists."
            ),
            state=row.state,
            requested_by_membership_id=row.requested_by_membership_id,
            requested_by_name=names.get(row.requested_by_membership_id),
            approver_membership_id=row.approver_membership_id,
            approver_name=(
                names.get(row.approver_membership_id)
                if row.approver_membership_id is not None
                else None
            ),
            reason=row.reason,
            decided_by_name=(
                names.get(row.decided_by_membership_id)
                if row.decided_by_membership_id is not None
                else None
            ),
            decided_at=row.decided_at.isoformat() if row.decided_at else None,
            due_at=row.due_at.isoformat() if row.due_at else None,
            escalation_note=row.escalation_note,
            escalated_to_name=(
                names.get(row.escalated_to_membership_id)
                if row.escalated_to_membership_id is not None
                else None
            ),
            escalated_at=row.escalated_at.isoformat() if row.escalated_at else None,
            created_at=row.created_at.isoformat(),
            may_decide=_may_decide(row, context),
        )
        for row in approvals
    ]


def _may_decide(approval: Approval, context: CurrentContext) -> bool:
    """The same three conditions the route enforces, answered for the screen.

    Kept beside them rather than in the frontend: two implementations of one rule is one rule the
    interface can get wrong, and the one printed on the screen is the one people believe.
    """
    if approval.state in ApprovalState.closed():
        return False
    if approval.requested_by_membership_id == context.membership_id:
        return False
    if approval.approver_membership_id is None:
        return Action.APPROVE in context.granted_actions
    return context.membership_id in {
        approval.approver_membership_id,
        approval.escalated_to_membership_id,
    }


async def _names(
    session: AsyncSession, ids: list[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    wanted = [value for value in ids if value is not None]
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(Membership.id, Membership.display_name).where(Membership.id.in_(wanted))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def _one(
    session: AsyncSession, context: CurrentContext, approval_id: uuid.UUID
) -> ApprovalRead:
    approval = await _approval(session, approval_id)
    return (await read_many(session, context, [approval]))[0]
