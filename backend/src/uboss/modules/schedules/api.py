"""What a schedule actually did — the history, and the one verb it accepts.

**There is no `POST /firings`.** A firing exists because the scheduler recorded an occurrence; a
route that created one would be a way to run a job while calling it a schedule.

The one verb is `release`: §8's `requires_approval_per_run` holds each occurrence until a person
lets it go, and this is that person's button. It needs `approve` — releasing a held run *is* the
per-run approval the schedule asked for — and it starts the workflow only after the decision is
committed, in the same order every other run start keeps.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from uboss.core.dependencies import CurrentContext, SessionDep, SettingsDep
from uboss.core.errors import NotFound
from uboss.core.idempotency import require_idempotency_key
from uboss.core.logging import get_logger
from uboss.core.permissions import Action
from uboss.db.base import bind_tenant
from uboss.modules.identity import guard
from uboss.modules.runtime import temporal
from uboss.modules.schedules import service
from uboss.modules.schedules.models import ScheduleFiring

log = get_logger(__name__)

router = APIRouter(tags=["schedules"])


class FiringRead(BaseModel):
    """One occurrence, and what became of it."""

    id: uuid.UUID
    schedule_id: uuid.UUID
    job_id: uuid.UUID
    due_at: str
    fired_at: str | None = None
    state: str
    #: Which rule skipped it, or what failed. The page shows this verbatim — "it did not run" is
    #: the answer nobody can act on, and the scheduler always wrote a better one.
    detail: str | None = None
    run_id: uuid.UUID | None = None
    was_missed: bool


@router.get("/jobs/{job_id}/schedule/firings", summary="What this schedule actually did")
async def list_firings(
    job_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[FiringRead]:
    """Newest first. Skips and failures included, with their reasons —

    a correctly-behaving schedule skips every bank holiday, and a history that hid the skips
    would make it look broken twice a year.
    """
    await guard.authorise(session, context, Action.VIEW)
    rows = list(
        (
            await session.execute(
                select(ScheduleFiring)
                .where(ScheduleFiring.job_id == job_id)
                .order_by(ScheduleFiring.due_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_read(row) for row in rows]


@router.post(
    "/schedule-firings/{firing_id}/release",
    summary="Let a held occurrence run",
)
async def release_firing(
    firing_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> FiringRead:
    """The per-run approval §8's `requires_approval_per_run` asked for.

    `approve`, not `run`: the schedule's author decided each occurrence needs a sign-off, and the
    person signing off is making an approval, whatever button label they clicked. The run row is
    committed before the workflow starts — the ordering every run start in this system keeps.
    """
    await guard.authorise(
        session,
        context,
        Action.APPROVE,
        resource=guard.Resource(type="schedule_firing", id=firing_id),
    )
    firing = (
        await session.execute(
            select(ScheduleFiring).where(ScheduleFiring.id == firing_id)
        )
    ).scalar_one_or_none()
    if firing is None:
        raise NotFound("That occurrence does not exist.")

    try:
        started = await service.release(session, context, firing)
    except service.AlreadyReleased:
        #  A retry of a release that worked. Nothing to commit and no workflow to start — the
        #  occurrence is answered as it stands, which is what was asked for.
        return _read(firing)

    await session.commit()
    await bind_tenant(session, context.tenant_id)

    client = await temporal.connect(settings)
    await temporal.start_run(
        client,
        tenant_id=started.tenant_id,
        run_id=started.run_id,
        workflow_id=started.workflow_id,
    )

    refreshed = (
        await session.execute(
            select(ScheduleFiring).where(ScheduleFiring.id == firing_id)
        )
    ).scalar_one()
    return _read(refreshed)


def _read(row: ScheduleFiring) -> FiringRead:
    return FiringRead(
        id=row.id,
        schedule_id=row.schedule_id,
        job_id=row.job_id,
        due_at=row.due_at.isoformat(),
        fired_at=row.fired_at.isoformat() if row.fired_at else None,
        state=row.state,
        detail=row.detail,
        run_id=row.run_id,
        was_missed=row.was_missed,
    )
