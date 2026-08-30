"""A job's schedule, and what it would actually do.

`GET /preview` is the route PLAN §8 asks for by name. It takes a `from_time` so somebody
configuring a schedule in July can look at October — which is when the clocks change, and the one
thing about a schedule that cannot be reasoned about from its settings.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.jobs import schedule_service
from uboss.modules.jobs.schedule_schemas import (
    SchedulePreview,
    ScheduleRead,
    ScheduleWrite,
)

router = APIRouter(prefix="/jobs/{job_id}/schedule", tags=["jobs"])


@router.get("", summary="A job's schedule")
async def read(
    job_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> ScheduleRead | None:
    """Null when there is none — a job that does not run by itself, which is most of them."""
    schedule = await schedule_service.read(session, context, job_id)
    return ScheduleRead.model_validate(schedule, from_attributes=True) if schedule else None


@router.get("/preview", summary="When this would actually run")
async def preview(
    job_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    count: Annotated[int, Query(ge=1, le=50)] = 10,
    from_time: Annotated[datetime | None, Query()] = None,
) -> SchedulePreview:
    """PLAN §8's recurrence preview.

    Nobody can read `interval=2, weekdays=[1,3], dst=shift` and know when it fires. Ten instants
    can be checked at a glance — and they come from the same function the runtime will use, so
    what somebody approves is what happens.
    """
    result = await schedule_service.preview(
        session, context, job_id, count=count, from_time=from_time
    )
    return SchedulePreview(
        timezone=result.timezone, occurrences=result.occurrences, notes=result.notes
    )


@router.put("", summary="Set the schedule")
async def set_schedule(
    job_id: uuid.UUID,
    body: ScheduleWrite,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ScheduleRead:
    """Create or replace it. The recurrence is validated before anything is written."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="job.schedule.set",
        payload={"job_id": str(job_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return ScheduleRead.model_validate(execution.replay_body)

        schedule = await schedule_service.set_schedule(
            session,
            context,
            job_id,
            body.model_dump(exclude={"expected_version"}),
            expected_version=body.expected_version,
        )
        result = ScheduleRead.model_validate(schedule, from_attributes=True)
        execution.complete_json(status_code=200, body=result.model_dump(mode="json"))
        return result


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Stop running by itself")
async def remove(
    job_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> None:
    """The job stays; it simply no longer runs on its own."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="job.schedule.remove",
        payload={"job_id": str(job_id)},
    ) as execution:
        if execution.is_replay:
            return

        await schedule_service.remove(session, context, job_id)
        execution.complete_json(status_code=200, body={"status": "removed"})
