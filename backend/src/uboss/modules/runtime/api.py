"""Starting, reading and stopping a run.

Four routes, and the order inside the first one is the whole design: the row is committed, then
the workflow is started. See `temporal.start_run` for why that order and not the other.

**`run` is its own verb.** PLAN §14's vocabulary has one, and this uses it rather than borrowing
`publish` or `edit_draft`. Somebody who may design a Job and somebody who may run one are
different people in most organisations, and collapsing them would make that impossible to express.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.dependencies import CurrentContext, SessionDep, SettingsDep
from uboss.core.errors import NotFound
from uboss.core.idempotency import require_idempotency_key
from uboss.core.logging import get_logger
from uboss.core.permissions import Action
from uboss.db.base import bind_tenant
from uboss.modules.identity import guard
from uboss.modules.runtime import service, temporal
from uboss.modules.runtime.models import Run, RunEvent, RunStep, RunTrigger, StepState

log = get_logger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


class StartRun(BaseModel):
    """Which published version to run."""

    model_config = ConfigDict(extra="forbid")

    job_version_id: uuid.UUID


class RunStepRead(BaseModel):
    id: uuid.UUID
    position: int
    title: str
    mode: str
    state: str
    attempt: int
    result: dict[str, object] | None = None
    failure_detail: str | None = None


class RunRead(BaseModel):
    """One run, as a screen reads it."""

    id: uuid.UUID
    job_id: uuid.UUID
    job_version_id: uuid.UUID
    state: str
    trigger: str
    #: How far along, as two counts rather than a percentage. A percentage of steps implies each
    #: one is the same size, and they are not.
    steps_total: int
    steps_done: int
    failure_detail: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RunEventRead(BaseModel):
    kind: str
    detail: dict[str, object]
    occurred_at: str
    run_step_id: uuid.UUID | None = None


class RunDetail(RunRead):
    steps: list[RunStepRead]
    events: list[RunEventRead]


class CancelRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Required, and not from a list. Why a run was stopped is the thing somebody reading the
    #: evidence next month needs, and a dropdown of four reasons produces four meaningless ones.
    reason: str = Field(min_length=1, max_length=500)


@router.post("", status_code=201, summary="Start a run of a published version")
async def start_run(
    body: StartRun,
    session: SessionDep,
    settings: SettingsDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RunRead:
    """Create the run, commit it, then start the workflow.

    **That order, and it matters.** A crash after the commit leaves a `pending` run — visible in
    every list, resolvable by a person or a reconciler. A crash the other way round would leave a
    workflow no row points at: nothing could find it, show it or stop it.

    If the workflow service is unreachable the run is left `pending` and the caller is told the run
    was not started. It is not deleted: something did happen, and a row that vanished would make
    the failure invisible.
    """
    await guard.authorise(session, context, Action.RUN)

    started = await service.start(
        session, context, job_version_id=body.job_version_id, trigger=RunTrigger.MANUAL
    )
    #  Committed before the workflow starts. The whole point of the ordering.
    await _commit(session, context)

    client = await temporal.connect(settings)
    await temporal.start_run(
        client,
        tenant_id=context.tenant_id,
        run_id=started.run_id,
        workflow_id=started.workflow_id,
    )

    return await _read(session, started.run_id)


@router.get("", summary="Runs in this workspace")
async def list_runs(
    session: SessionDep,
    context: CurrentContext,
    job_id: uuid.UUID | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> list[RunRead]:
    await guard.authorise(session, context, Action.VIEW)

    query = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if job_id is not None:
        query = query.where(Run.job_id == job_id)
    runs = list((await session.execute(query)).scalars().all())

    #  One query for the step counts of every run on the page, rather than one per run.
    counts = await _step_counts(session, [run.id for run in runs])
    return [_summary(run, counts) for run in runs]


@router.get("/{run_id}", summary="One run, with its steps and what happened")
async def read_run(
    run_id: uuid.UUID, session: SessionDep, context: CurrentContext
) -> RunDetail:
    await guard.authorise(session, context, Action.VIEW)
    run = await _run(session, run_id)

    steps = list(
        (
            await session.execute(
                select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position)
            )
        )
        .scalars()
        .all()
    )
    events = list(
        (
            await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run.id)
                .order_by(RunEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )

    return RunDetail(
        **_summary(
            run,
            {run.id: (len(steps), sum(1 for step in steps if step.state in _FINISHED))},
        ).model_dump(),
        steps=[
            RunStepRead(
                id=step.id,
                position=step.position,
                title=step.title,
                mode=step.mode,
                state=step.state,
                attempt=step.attempt,
                result=step.result,
                failure_detail=step.failure_detail,
            )
            for step in steps
        ],
        events=[
            RunEventRead(
                kind=event.kind,
                detail=event.detail,
                occurred_at=event.occurred_at.isoformat(),
                run_step_id=event.run_step_id,
            )
            for event in events
        ],
    )


@router.post("/{run_id}/cancel", summary="Stop a run")
async def cancel_run(
    run_id: uuid.UUID,
    body: CancelRun,
    session: SessionDep,
    settings: SettingsDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RunRead:
    """Mark the run cancelled, then ask Temporal to stop the workflow.

    The row first, again: a cancelled row with a workflow still going is recoverable — the next
    activity finds the run finished and stops. A stopped workflow with a row that still says
    `running` is a run nothing will ever finish.
    """
    await guard.authorise(session, context, Action.RUN)
    run = await _run(session, run_id)

    await service.cancel(session, context, run, reason=body.reason)
    await _commit(session, context)

    client = await temporal.connect(settings)
    #  Best effort, and logged rather than silent. The row is the record — a workflow that has
    #  already finished raises here and that is not a failure of the cancellation — but a
    #  swallowed error is how a queue of orphaned workflows builds up unnoticed.
    try:
        await temporal.cancel_run(client, workflow_id=run.workflow_id)
    except Exception as cause:
        log.info(
            "run_workflow_cancel_ignored", run_id=str(run_id), error=type(cause).__name__
        )

    return await _read(session, run_id)


async def _commit(session: AsyncSession, context: CurrentContext) -> None:
    """Commit, then bind the tenant again.

    **`app.tenant_id` is transaction-local**, which is what makes row-level security a boundary
    rather than a session setting somebody can leave behind. The consequence is easy to miss:
    committing in the middle of a request ends the transaction and takes the binding with it, so
    the *next* statement runs unbound and every policy refuses it — with
    `invalid input syntax for type uuid: ""`, which reads like a data bug and is not one.

    Almost no route commits mid-request. This one has to: the run's row must be durable before the
    workflow is started, or a crash between them leaves a workflow nothing points at. So it
    re-binds, here, in one place.
    """
    await session.commit()
    await bind_tenant(session, context.tenant_id)


# ── reading ──────────────────────────────────────────────────────────────────────────────


async def _run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        #  Row-level security has already made another tenant's run invisible, so this is the same
        #  answer for "does not exist" and "not yours" — which is the point.
        raise NotFound("That run does not exist.")
    return run


async def _read(session: AsyncSession, run_id: uuid.UUID) -> RunRead:
    run = await _run(session, run_id)
    return _summary(run, await _step_counts(session, [run.id]))


async def _step_counts(
    session: AsyncSession, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """`(total, finished)` per run. One query for the whole page, not one per run.

    Both counted here rather than the total being filled in later: a progress reading assembled
    from two places is one that eventually shows 3 of 0.
    """
    if not run_ids:
        return {}
    rows = (
        await session.execute(
            select(
                RunStep.run_id,
                func.count(),
                func.count().filter(RunStep.state.in_(_FINISHED)),
            )
            .where(RunStep.run_id.in_(run_ids))
            .group_by(RunStep.run_id)
        )
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


#: The step states that count as done. `skipped` counts — the run passed it — and `failed` counts
#: because the run is not still working on it. Taken from the enum rather than restated, so a new
#: state cannot be added in one place and forgotten here.
_FINISHED = StepState.finished()


def _summary(run: Run, counts: dict[uuid.UUID, tuple[int, int]]) -> RunRead:
    total, done = counts.get(run.id, (0, 0))
    return RunRead(
        id=run.id,
        job_id=run.job_id,
        job_version_id=run.job_version_id,
        state=run.state,
        trigger=run.trigger,
        steps_total=total,
        steps_done=done,
        failure_detail=run.failure_detail,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
    )
