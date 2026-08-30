"""Publishing a Job: the summary, the submission, and the approval.

Three routes, the same as the Objective's, because they are the same three decisions by up to two
people. A single "publish" call would collapse PLAN §14's separation into one request.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.core.permissions import Action
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.jobs import publish as publishing
from uboss.modules.jobs.models import JobStatus, JobVersion


class JobPublishAction(BaseModel):
    """The version the person was looking at when they decided."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class JobWarningRead(BaseModel):
    code: str
    message: str


class JobPublishSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    name: str
    status: JobStatus
    owner_name: str | None
    approver_name: str | None
    submitted_by_name: str | None
    department: str | None
    objective_name: str | None

    step_count: int
    human_steps: int
    agent_steps: int
    hybrid_steps: int
    rule_count: int
    input_count: int
    #: The number that answers "what does the AI actually see".
    ai_readable_inputs: int

    #: The schedule in one line, or null when there is none.
    schedule_summary: str | None
    schedule_auto_run: bool

    warnings: list[JobWarningRead] = Field(default_factory=list)
    next_action: str
    can_submit: bool
    can_approve: bool
    version: int


class JobVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_no: int
    name: str
    published_at: str
    approved_by_name: str | None = None
    published_by_name: str | None = None
    step_count: int = 0


router = APIRouter(prefix="/jobs/{job_id}", tags=["jobs"])


@router.get("/publish", summary="What publishing this would mean")
async def summary(
    job_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> JobPublishSummary:
    """Computed on every read, so it cannot describe a job that has since changed."""
    result = await publishing.summary(session, context, job_id)
    return JobPublishSummary(
        **{
            field: getattr(result, field)
            for field in JobPublishSummary.model_fields
            if field != "warnings"
        },
        warnings=[
            JobWarningRead(code=warning.code, message=warning.message)
            for warning in result.warnings
        ],
    )


@router.post("/submit", summary="Send for approval")
async def submit(
    job_id: uuid.UUID,
    body: JobPublishAction,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="job.submit",
        payload={"job_id": str(job_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        job = await publishing.submit(session, context, job_id, body.expected_version)
        result = {"status": job.status, "version": str(job.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/withdraw", summary="Take it back out of the queue")
async def withdraw(
    job_id: uuid.UUID,
    body: JobPublishAction,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="job.withdraw",
        payload={"job_id": str(job_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        job = await publishing.withdraw(session, context, job_id, body.expected_version)
        result = {"status": job.status, "version": str(job.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/publish", summary="Approve and publish")
async def approve(
    job_id: uuid.UUID,
    body: JobPublishAction,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Approval creates the immutable version, and the snapshot includes the schedule.

    A published version that did not record when it ran could not answer "why did this fire at
    3 a.m. in March", which is the question a clock change produces.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="job.publish",
        payload={"job_id": str(job_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        version = await publishing.publish(session, context, job_id, body.expected_version)
        result = {"version_id": str(version.id), "version_no": str(version.version_no)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.get("/versions", summary="What has been published")
async def versions(
    job_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> list[JobVersionRead]:
    await guard.authorise(session, context, Action.VIEW)

    rows = list(
        (
            await session.execute(
                select(JobVersion)
                .where(JobVersion.job_id == job_id)
                .order_by(JobVersion.version_no.desc())
            )
        )
        .scalars()
        .all()
    )
    names = await _names(session, rows)
    return [
        JobVersionRead(
            id=row.id,
            version_no=row.version_no,
            name=row.name,
            published_at=row.published_at.isoformat(),
            approved_by_name=names.get(row.approved_by_membership_id),
            published_by_name=names.get(row.published_by_membership_id),
            step_count=len(row.snapshot.get("steps", [])),
        )
        for row in rows
    ]


async def _names(
    session: AsyncSession, rows: list[JobVersion]
) -> dict[uuid.UUID | None, str]:
    wanted: set[uuid.UUID] = set()
    for row in rows:
        for value in (row.approved_by_membership_id, row.published_by_membership_id):
            if value is not None:
                wanted.add(value)
    if not wanted:
        return {}
    return {
        member.id: member.display_name
        for member in (
            (await session.execute(select(Membership).where(Membership.id.in_(wanted))))
            .scalars()
            .all()
        )
    }
