"""Jobs over HTTP.

Deliberately the same shape as the Objective's routes: list, lists, create, read, save, archive.
A person who has used one Builder should find the next behaves the same way, and so should
whoever reads the code six months from now.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, Query, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.jobs import service
from uboss.modules.jobs.schemas import (
    JobCreate,
    JobList,
    JobRead,
    JobUpdate,
    JobWorkbookLists,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", summary="The jobs in this workspace")
async def list_jobs(
    context: CurrentContext,
    session: SessionDep,
    job_status: Annotated[str | None, Query(alias="status")] = None,
    objective_id: Annotated[uuid.UUID | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> JobList:
    """`is_empty` separates "no jobs yet" from "none match that filter" — different words."""
    return await service.list_jobs(
        session,
        context,
        status=job_status,
        objective_id=objective_id,
        include_archived=include_archived,
    )


@router.get("/lists", summary="The workbook's suggested values for Form 3")
async def workbook_lists(context: CurrentContext, session: SessionDep) -> JobWorkbookLists:
    """Methods, input types, approval timings and the rest, from the approved sheet.

    Served rather than kept in the frontend: a second copy of an approved list is a copy that
    drifts. They are suggestions, not validation — each ends in `Other`.
    """
    return JobWorkbookLists()


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start a job draft")
async def create(
    body: JobCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """A name is enough. Naming an objective carries its department across rather than asking."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="job.create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        job = await service.create(session, context, body)
        result = {"id": str(job.id), "version": str(job.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.get("/{job_id}", summary="One job, with its steps, WHO rules and inputs")
async def read(
    job_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> JobRead:
    return await service.read(session, context, job_id)


@router.patch("/{job_id}", summary="Save the draft")
async def update(
    job_id: uuid.UUID,
    body: JobUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> JobRead:
    """Autosave and Save Draft alike.

    Returns the whole job, so the client's copy and the server's cannot drift after a save that
    changed something the client did not send — the version number, which every later save
    depends on.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="job.update",
        payload={"job_id": str(job_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return JobRead.model_validate(execution.replay_body)

        job = await service.update(session, context, job_id, body)
        result = await service.read(session, context, job.id)
        execution.complete_json(status_code=200, body=result.model_dump(mode="json"))
        return result


@router.post("/{job_id}/archive", summary="Archive a job")
async def archive(
    job_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True, ge=1)] = 1,
) -> dict[str, str]:
    """Archived, never deleted — every run recorded against it needs it to still exist."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="job.archive",
        payload={"job_id": str(job_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        job = await service.archive(session, context, job_id, expected_version)
        result = {"id": str(job.id), "version": str(job.version)}
        execution.complete_json(status_code=200, body=result)
        return result
