"""Objectives over HTTP — PLAN §7's cards and Draft form.

Thin routes: parse, call the service, return. Everything that decides anything lives in
`service.py`, so 3.2's proposal path and 3.3's publish get the same behaviour without a route in
front of them.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, Query, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.objectives import service
from uboss.modules.objectives.schemas import (
    ObjectiveCreate,
    ObjectiveList,
    ObjectiveRead,
    ObjectiveUpdate,
    PersonRef,
    WorkbookLists,
)

router = APIRouter(prefix="/objectives", tags=["objectives"])


@router.get("", summary="The objectives in this workspace")
async def list_objectives(
    context: CurrentContext,
    session: SessionDep,
    objective_status: Annotated[str | None, Query(alias="status")] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> ObjectiveList:
    """PLAN §7's cards.

    `is_empty` separates "this workspace has no objectives" from "none match that filter". They
    look identical on screen and need different words — one offers to create the first, the other
    offers to clear the filter.
    """
    return await service.list_objectives(
        session, context, status=objective_status, include_archived=include_archived
    )


@router.get("/lists", summary="The workbook's suggested values")
async def workbook_lists(context: CurrentContext, session: SessionDep) -> WorkbookLists:
    """Departments, triggers, frequencies and the rest, from the approved workbook.

    Served rather than kept in the frontend, because a second copy is a copy that drifts. They
    are suggestions and not validation: every list ends in `Other`, so a value outside it is
    something the workbook explicitly allows.
    """
    return WorkbookLists()


@router.get("/people", summary="Who can be named as owner or approver")
async def people(context: CurrentContext, session: SessionDep) -> list[PersonRef]:
    """Active members of this workspace — a name and a job title, nothing more."""
    return await service.people(session, context)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start a draft")
async def create(
    body: ObjectiveCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Only a title is required. The rest is filled in over however long it takes."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        objective = await service.create(session, context, body)
        result = {"id": str(objective.id), "version": str(objective.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.get("/{objective_id}", summary="One objective, with its step table")
async def read(
    objective_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> ObjectiveRead:
    return await service.read(session, context, objective_id)


@router.patch("/{objective_id}", summary="Save the draft")
async def update(
    objective_id: uuid.UUID,
    body: ObjectiveUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ObjectiveRead:
    """Both the autosave and the explicit Save Draft — PLAN §6 asks for both, and they write the
    same thing.

    Returns the whole objective rather than an acknowledgement, so the client's copy and the
    server's cannot drift after a save that changed something the client did not send.

    The idempotency key is derived from the version being saved, so a retry after a dropped
    connection is recognised as the same save rather than applied twice.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.update",
        payload={"objective_id": str(objective_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return ObjectiveRead.model_validate(execution.replay_body)

        objective = await service.update(session, context, objective_id, body)
        result = await service.read(session, context, objective.id)
        execution.complete_json(status_code=200, body=result.model_dump(mode="json"))
        return result


@router.post("/{objective_id}/archive", summary="Archive an objective")
async def archive(
    objective_id: uuid.UUID,
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
        operation="objective.archive",
        payload={"objective_id": str(objective_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        objective = await service.archive(session, context, objective_id, expected_version)
        result = {"id": str(objective.id), "version": str(objective.version)}
        execution.complete_json(status_code=200, body=result)
        return result
