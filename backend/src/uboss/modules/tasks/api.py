"""§11's To-do list, over HTTP.

**There is no `POST /tasks`.** A task exists because a run reached a human step; a route that
created one would be a way to put work into the governed list without a governed method behind it.
Everything here reads or closes work the runtime made.

## Who may do what

Reading is `view`. Acting on a task is narrower than a permission: it must be **yours**, or
unassigned and you hold `assign`. Holding `view` over a workspace does not make you able to
complete somebody else's work, and the check is here rather than in the screen.

An approval task additionally needs `approve`, and the person who started the run cannot be the
one who approves it — `guard.refuse_self_approval`, the same rule releases use.

## The signal comes last

Completing a task commits, and only then signals the workflow. The signal carries nothing, so the
workflow reads the database when it wakes; a signal sent before the commit would wake it to find
the step unchanged and the run would stall with nothing to say why.

If the workflow service is unreachable the task stays completed and the caller is told the run did
not advance. The alternative — rolling the completion back — would throw away somebody's work
because a third service was down.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from uboss.core.dependencies import CurrentContext, SessionDep, SettingsDep
from uboss.core.errors import NotFound, PermissionDenied
from uboss.core.idempotency import require_idempotency_key
from uboss.core.logging import get_logger
from uboss.core.permissions import Action
from uboss.db.base import bind_tenant
from uboss.modules.approvals import api as approvals_api
from uboss.modules.approvals import service as approvals
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.runtime import temporal
from uboss.modules.runtime.models import Run, RunStep
from uboss.modules.tasks import service
from uboss.modules.tasks.models import (
    Task,
    TaskComment,
    TaskEvidence,
    TaskFollower,
    TaskKind,
    TaskState,
)

log = get_logger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])

#: §11's five tabs, verbatim: *Assigned to me*, *Approvals*, *Input requested*, *Following*,
#: *Completed*. Named here so the frontend and the backend cannot disagree about what a tab means.
#:
#: `unassigned` is **not** a sixth tab — the plan names five. It is a filter the list accepts so
#: that a task whose WHO rules matched nobody is reachable by somebody who may hand work out;
#: without it that work would exist and appear in nobody's list at all.
Tab = Literal["mine", "approvals", "input", "following", "completed", "unassigned"]


# ── what goes over the wire ──────────────────────────────────────────────────────────────


class TaskRead(BaseModel):
    """One row of the list."""

    id: uuid.UUID
    run_id: uuid.UUID
    run_step_id: uuid.UUID
    job_id: uuid.UUID | None = None
    kind: str
    title: str
    state: str
    #: Null when §8's WHO rules matched nobody. The screen says so rather than showing a blank.
    assignee_membership_id: uuid.UUID | None = None
    assignee_name: str | None = None
    assigned_via: str
    outcome: str | None = None
    outcome_note: str | None = None
    due_at: str | None = None
    created_at: str
    completed_at: str | None = None
    completed_by_name: str | None = None
    #: Whether the person asking is following it — what the star in the list is drawn from.
    following: bool = False


class CommentRead(BaseModel):
    id: uuid.UUID
    membership_id: uuid.UUID
    author_name: str | None = None
    body: str
    created_at: str


class EvidenceRead(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    note: str | None = None
    attached_by_membership_id: uuid.UUID
    created_at: str


class TaskDetail(TaskRead):
    instructions: str | None = None
    step_position: int
    run_state: str
    comments: list[CommentRead]
    evidence: list[EvidenceRead]
    followers: list[uuid.UUID]
    #: The decision behind an approval task — who asked, who may decide, and the question in the
    #: Job author's words. Null for every other kind, and for an approval on a run nobody started.
    #: Carried here rather than fetched separately so the panel cannot draw an approve button
    #: before it knows whether this person is allowed to press it.
    approval: approvals_api.ApprovalRead | None = None


class TaskCounts(BaseModel):
    """What the sidebar badge reads, and the numbers §11's tabs carry.

    `mine_open` is the sidebar's: *"Sidebar count includes actionable pending items, not
    informational notifications."* Approvals and inputs are subsets of it, not additions — adding
    them would count the same task twice.
    """

    mine_open: int
    approvals: int
    input_requested: int
    unassigned: int
    following_open: int


class Complete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: One of `TaskOutcome`, and which ones are allowed depends on the task's kind.
    outcome: str
    #: Required for a rejection or a request for changes — enforced by the service and by a
    #: check constraint, so it cannot be bypassed by writing to the database directly.
    note: str | None = Field(default=None, max_length=4000)


class Decline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class Delegate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_membership_id: uuid.UUID
    note: str | None = Field(default=None, max_length=1000)


class Reassign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_membership_id: uuid.UUID


class NewComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)


class NewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: uuid.UUID
    note: str | None = Field(default=None, max_length=500)


# ── reading ──────────────────────────────────────────────────────────────────────────────


@router.get("/counts", summary="How much is waiting on me")
async def counts(session: SessionDep, context: CurrentContext) -> TaskCounts:
    """Three numbers, each one a query the tabs also run — so a badge and its tab agree."""
    await guard.authorise(session, context, Action.VIEW)

    following = select(TaskFollower.task_id).where(
        TaskFollower.membership_id == context.membership_id
    )
    mine = (
        Task.assignee_membership_id == context.membership_id,
        Task.state.in_(TaskState.open()),
    )
    return TaskCounts(
        mine_open=await service.open_count(session, context.membership_id),
        approvals=await _count(session, *mine, Task.kind == TaskKind.APPROVAL),
        input_requested=await _count(session, *mine, Task.kind == TaskKind.INPUT),
        unassigned=await _count(
            session,
            Task.assignee_membership_id.is_(None),
            Task.state.in_(TaskState.open()),
        ),
        following_open=await _count(
            session, Task.id.in_(following), Task.state.in_(TaskState.open())
        ),
    )


@router.get("", summary="The To-do list")
async def list_tasks(
    session: SessionDep,
    context: CurrentContext,
    tab: Tab = "mine",
    kind: str | None = None,
    run_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[TaskRead]:
    """§11's five tabs, and the one filter that keeps unheld work visible.

    Every tab is scoped to the caller **by the query**, not by the screen: a filter the frontend
    applies is a filter somebody can remove with a query parameter.

    *Approvals* and *Input requested* are the same rows as *Assigned to me*, narrowed by kind —
    one table, three tabs, so a badge and its tab are one query rather than three that can
    disagree.
    """
    await guard.authorise(session, context, Action.VIEW)

    query = select(Task).order_by(Task.created_at.desc()).limit(limit)
    following = select(TaskFollower.task_id).where(
        TaskFollower.membership_id == context.membership_id
    )

    if tab in {"mine", "approvals", "input"}:
        query = query.where(
            Task.assignee_membership_id == context.membership_id,
            Task.state.in_(TaskState.open()),
        )
        if tab == "approvals":
            query = query.where(Task.kind == TaskKind.APPROVAL)
        elif tab == "input":
            query = query.where(Task.kind == TaskKind.INPUT)
    elif tab == "unassigned":
        query = query.where(
            Task.assignee_membership_id.is_(None), Task.state.in_(TaskState.open())
        )
    elif tab == "following":
        query = query.where(Task.id.in_(following))
    elif tab == "completed":
        #  Mine, finished — what somebody looks at to answer "what did I do last week". It
        #  includes work they closed for somebody else, because they did it.
        query = query.where(
            or_(
                Task.assignee_membership_id == context.membership_id,
                Task.completed_by_membership_id == context.membership_id,
            ),
            Task.state.in_(TaskState.closed()),
        )

    if kind is not None:
        query = query.where(Task.kind == kind)
    if run_id is not None:
        query = query.where(Task.run_id == run_id)

    rows = list((await session.execute(query)).scalars().all())
    return await _rows(session, context, rows)


@router.get("/{task_id}", summary="One task, with its conversation and evidence")
async def read_task(
    task_id: uuid.UUID, session: SessionDep, context: CurrentContext
) -> TaskDetail:
    await guard.authorise(session, context, Action.VIEW)
    task = await _task(session, task_id)

    step = (
        await session.execute(select(RunStep).where(RunStep.id == task.run_step_id))
    ).scalar_one_or_none()
    run = (
        await session.execute(select(Run).where(Run.id == task.run_id))
    ).scalar_one_or_none()
    comments = list(
        (
            await session.execute(
                select(TaskComment)
                .where(TaskComment.task_id == task.id)
                .order_by(TaskComment.created_at)
            )
        )
        .scalars()
        .all()
    )
    evidence = list(
        (
            await session.execute(
                select(TaskEvidence)
                .where(TaskEvidence.task_id == task.id)
                .order_by(TaskEvidence.created_at)
            )
        )
        .scalars()
        .all()
    )
    followers = list(
        (
            await session.execute(
                select(TaskFollower.membership_id).where(TaskFollower.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )

    names = await _names(
        session,
        [task.assignee_membership_id, task.completed_by_membership_id]
        + [row.membership_id for row in comments],
    )
    approval = await approvals.for_task(session, task.id)
    approval_read = (
        (await approvals_api.read_many(session, context, [approval]))[0]
        if approval is not None
        else None
    )

    base = _read(task, names, following=context.membership_id in followers, run=run)
    return TaskDetail(
        **base.model_dump(),
        instructions=task.instructions,
        step_position=step.position if step is not None else 0,
        run_state=run.state if run is not None else "unknown",
        comments=[
            CommentRead(
                id=row.id,
                membership_id=row.membership_id,
                author_name=names.get(row.membership_id),
                body=row.body,
                created_at=row.created_at.isoformat(),
            )
            for row in comments
        ],
        evidence=[
            EvidenceRead(
                id=row.id,
                file_id=row.file_id,
                note=row.note,
                attached_by_membership_id=row.attached_by_membership_id,
                created_at=row.created_at.isoformat(),
            )
            for row in evidence
        ],
        followers=followers,
        approval=approval_read,
    )


# ── acting ───────────────────────────────────────────────────────────────────────────────


@router.post("/{task_id}/start", summary="Pick a task up")
async def start_task(
    task_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> TaskRead:
    await guard.authorise(session, context, Action.VIEW)
    task = await _task(session, task_id)
    await _must_be_mine(session, context, task)

    await service.start(session, context, task)
    await session.commit()
    await bind_tenant(session, context.tenant_id)
    return await _one(session, context, task_id)


@router.post("/{task_id}/complete", summary="Finish a task and let the run continue")
async def complete_task(
    task_id: uuid.UUID,
    body: Complete,
    session: SessionDep,
    settings: SettingsDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> TaskRead:
    """Close the task, finish the step, commit — then wake the workflow.

    The order is the same one `POST /runs` keeps and for the same reason: what happened is durable
    before anything is told about it.
    """
    await guard.authorise(session, context, Action.VIEW)
    task = await _task(session, task_id)
    await _must_be_mine(session, context, task)

    if task.kind == TaskKind.APPROVAL:
        #  An approval is a second pair of eyes or it is nothing. Both checks: the permission,
        #  and then whether this person is the one who set the work going.
        await guard.authorise(
            session,
            context,
            Action.APPROVE,
            resource=guard.Resource(type="task", id=task.id),
        )
        run = (
            await session.execute(select(Run).where(Run.id == task.run_id))
        ).scalar_one_or_none()
        if run is not None and run.started_by_membership_id is not None:
            await guard.refuse_self_approval(
                session,
                context,
                submitted_by_membership_id=run.started_by_membership_id,
                resource=guard.Resource(type="task", id=task.id),
            )

    await service.complete(session, context, task, outcome=body.outcome, note=body.note)
    workflow_id = await _workflow_id(session, task)
    await session.commit()
    await bind_tenant(session, context.tenant_id)

    await temporal.wake_run(settings, workflow_id)
    return await _one(session, context, task_id)


@router.post("/{task_id}/decline", summary="Hand a task back")
async def decline_task(
    task_id: uuid.UUID,
    body: Decline,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> TaskRead:
    """The step stays waiting and a fresh, unassigned task takes its place.

    No signal is sent: nothing was done, and waking the workflow would advance a run past work
    that still needs doing.
    """
    await guard.authorise(session, context, Action.VIEW)
    task = await _task(session, task_id)
    await _must_be_mine(session, context, task)

    await service.decline(session, context, task, reason=body.reason)
    await session.commit()
    await bind_tenant(session, context.tenant_id)
    return await _one(session, context, task_id)


@router.post("/{task_id}/delegate", status_code=201, summary="Pass a task to somebody else")
async def delegate_task(
    task_id: uuid.UUID,
    body: Delegate,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> TaskRead:
    """Returns the **new** task, because that is the one that now exists to be done."""
    await guard.authorise(session, context, Action.VIEW)
    task = await _task(session, task_id)
    await _must_be_mine(session, context, task)

    handed = await service.delegate(
        session,
        context,
        task,
        to_membership_id=body.to_membership_id,
        note=body.note,
    )
    new_id = handed.id
    await session.commit()
    await bind_tenant(session, context.tenant_id)
    return await _one(session, context, new_id)


@router.post("/{task_id}/reassign", summary="Give an unheld task an owner")
async def reassign_task(
    task_id: uuid.UUID,
    body: Reassign,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> TaskRead:
    """Needs `assign`, not `view`. Deciding who does a piece of work is its own authority."""
    await guard.authorise(
        session, context, Action.ASSIGN, resource=guard.Resource(type="task", id=task_id)
    )
    task = await _task(session, task_id)

    await service.reassign(session, context, task, to_membership_id=body.to_membership_id)
    await session.commit()
    await bind_tenant(session, context.tenant_id)
    return await _one(session, context, task_id)


@router.post("/{task_id}/comments", status_code=201, summary="Say something on a task")
async def add_comment(
    task_id: uuid.UUID,
    body: NewComment,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> CommentRead:
    await guard.authorise(session, context, Action.COMMENT)
    task = await _task(session, task_id)

    row = await service.comment(session, context, task, body=body.body)
    created = row.created_at
    result = CommentRead(
        id=row.id,
        membership_id=row.membership_id,
        author_name=(await _names(session, [row.membership_id])).get(row.membership_id),
        body=row.body,
        created_at=created.isoformat(),
    )
    await session.commit()
    return result


@router.post("/{task_id}/evidence", status_code=201, summary="Attach proof to a task")
async def add_evidence(
    task_id: uuid.UUID,
    body: NewEvidence,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> EvidenceRead:
    """The file must already be in this workspace — row-level security is what makes that true."""
    await guard.authorise(session, context, Action.VIEW)
    task = await _task(session, task_id)
    await _must_be_mine(session, context, task)

    row = await service.attach(
        session, context, task, file_id=body.file_id, note=body.note
    )
    result = EvidenceRead(
        id=row.id,
        file_id=row.file_id,
        note=row.note,
        attached_by_membership_id=row.attached_by_membership_id,
        created_at=row.created_at.isoformat(),
    )
    await session.commit()
    return result


@router.post("/{task_id}/follow", status_code=204, summary="Watch a task")
async def follow_task(
    task_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> None:
    """Following is already idempotent, and it still asks for a key.

    The rule in `CLAUDE.md` is unconditional — *every* mutating `/v1` request carries one — and a
    route exempted because it happens to be safe today is a route nobody re-examines when it stops
    being safe. The cost is one header.
    """
    await guard.authorise(session, context, Action.VIEW)
    task = await _task(session, task_id)
    await service.follow(session, context, task)
    await session.commit()


@router.delete("/{task_id}/follow", status_code=204, summary="Stop watching a task")
async def unfollow_task(
    task_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> None:
    await guard.authorise(session, context, Action.VIEW)
    task = await _task(session, task_id)
    await service.unfollow(session, context, task)
    await session.commit()


# ── internals ────────────────────────────────────────────────────────────────────────────


async def _task(session: AsyncSession, task_id: uuid.UUID) -> Task:
    task = (
        await session.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    if task is None:
        #  Row-level security has already hidden another workspace's task, so "not yours" and
        #  "does not exist" are the same answer — which is the point.
        raise NotFound("That task does not exist.")
    return task


async def _must_be_mine(
    session: AsyncSession, context: CurrentContext, task: Task
) -> None:
    """Acting on a task needs it to be yours, or unheld and you allowed to hand work out.

    Narrower than a permission on purpose. `view` over a workspace is a reading right; without
    this, anybody who could see the To-do list could complete anybody's work in it and the audit
    row would name the wrong person's job.
    """
    if task.assignee_membership_id == context.membership_id:
        return
    if task.assignee_membership_id is None:
        await guard.authorise(
            session, context, Action.ASSIGN, resource=guard.Resource(type="task", id=task.id)
        )
        return
    raise PermissionDenied("That task belongs to somebody else.")


async def _workflow_id(session: AsyncSession, task: Task) -> str | None:
    run = (
        await session.execute(select(Run).where(Run.id == task.run_id))
    ).scalar_one_or_none()
    return run.workflow_id if run is not None else None


async def _count(session: AsyncSession, *where: ColumnElement[bool]) -> int:
    """A count done by the database. Counting rows in Python would read every one of them."""
    return int(
        (
            await session.execute(select(func.count()).select_from(Task).where(*where))
        ).scalar_one()
    )


async def _names(
    session: AsyncSession, ids: list[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    """Display names for a page of rows, in one query.

    Names rather than ids in the response because a list of UUIDs is not a To-do list anybody can
    read, and the alternative — the frontend looking each one up — is one request per row.
    """
    wanted = [value for value in ids if value is not None]
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(Membership.id, Membership.display_name).where(Membership.id.in_(wanted))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


def _read(
    task: Task,
    names: dict[uuid.UUID, str],
    *,
    following: bool,
    run: Run | None = None,
) -> TaskRead:
    return TaskRead(
        id=task.id,
        run_id=task.run_id,
        run_step_id=task.run_step_id,
        job_id=run.job_id if run is not None else None,
        kind=task.kind,
        title=task.title,
        state=task.state,
        assignee_membership_id=task.assignee_membership_id,
        assignee_name=(
            names.get(task.assignee_membership_id)
            if task.assignee_membership_id is not None
            else None
        ),
        assigned_via=task.assigned_via,
        outcome=task.outcome,
        outcome_note=task.outcome_note,
        due_at=task.due_at.isoformat() if task.due_at else None,
        created_at=task.created_at.isoformat(),
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        completed_by_name=(
            names.get(task.completed_by_membership_id)
            if task.completed_by_membership_id is not None
            else None
        ),
        following=following,
    )


async def _rows(
    session: AsyncSession, context: CurrentContext, tasks: list[Task]
) -> list[TaskRead]:
    if not tasks:
        return []
    ids = [task.id for task in tasks]
    followed = set(
        (
            await session.execute(
                select(TaskFollower.task_id).where(
                    TaskFollower.task_id.in_(ids),
                    TaskFollower.membership_id == context.membership_id,
                )
            )
        )
        .scalars()
        .all()
    )
    runs = {
        run.id: run
        for run in (
            await session.execute(
                select(Run).where(Run.id.in_([task.run_id for task in tasks]))
            )
        )
        .scalars()
        .all()
    }
    names = await _names(
        session,
        [task.assignee_membership_id for task in tasks]
        + [task.completed_by_membership_id for task in tasks],
    )
    return [
        _read(
            task,
            names,
            following=task.id in followed,
            run=runs.get(task.run_id),
        )
        for task in tasks
    ]


async def _one(
    session: AsyncSession, context: CurrentContext, task_id: uuid.UUID
) -> TaskRead:
    task = await _task(session, task_id)
    return (await _rows(session, context, [task]))[0]
