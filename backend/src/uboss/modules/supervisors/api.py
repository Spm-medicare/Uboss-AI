"""Supervisors over HTTP — §10.

The same shape as the other Builders' routes, plus two that are specific to this object and both
come from §10's two independent scopes:

* `PUT /supervisors/{id}` edits the design and **scope 1**, behind `edit_draft`.
* `PUT /supervisors/{id}/handlers/{membership_id}` edits **scope 2**, behind `manage_access`.

Separate routes on purpose. One payload carrying both would let the looser permission decide the
stricter one, and the whole gate rests on the two scopes staying independent.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, Query, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.supervisors import handlers as handler_service
from uboss.modules.supervisors import service
from uboss.modules.supervisors.schemas import (
    HandlerInput,
    HandlerRead,
    SupervisorCreate,
    SupervisorList,
    SupervisorLists,
    SupervisorRead,
    SupervisorScheduleRead,
    SupervisorScheduleWrite,
    SupervisorUpdate,
)

router = APIRouter(prefix="/supervisors", tags=["supervisors"])


@router.get("", summary="The supervisors this person may control")
async def list_supervisors(
    context: CurrentContext,
    session: SessionDep,
    supervisor_status: Annotated[str | None, Query(alias="status")] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> SupervisorList:
    """Narrowed by scope 2. A Supervisor somebody cannot control is not theirs to see, and
    listing it would leak who supervises whom."""
    return await service.list_supervisors(
        session,
        context,
        status=supervisor_status,
        include_archived=include_archived,
    )


@router.get("/lists", summary="The closed vocabularies a supervisor screen needs")
async def supervisor_lists(context: CurrentContext, session: SessionDep) -> SupervisorLists:
    """Kinds, handler roles, gate outcomes and simulation statuses.

    Served rather than kept in the frontend: a second copy of a closed set is a copy that drifts,
    and every one of these is closed because §10 or the workbook closes it.
    """
    return SupervisorLists()


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start a supervisor draft")
async def create(
    body: SupervisorCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """The creator becomes the owner, which makes them Owner without a handler row."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="supervisor.create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        supervisor = await service.create(session, context, body)
        result = {"id": str(supervisor.id), "version": str(supervisor.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.get("/{supervisor_id}", summary="One supervisor, in full")
async def read(
    supervisor_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> SupervisorRead:
    """Both scopes in one response, with what the caller may do on this one."""
    return await service.read(session, context, supervisor_id)


@router.put("/{supervisor_id}", summary="Save the supervisor draft")
async def update(
    supervisor_id: uuid.UUID,
    body: SupervisorUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SupervisorRead:
    """Saving clears every recorded simulation result — a pass against yesterday's design says
    nothing about today's."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="supervisor.update",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return SupervisorRead.model_validate(execution.replay_body)

        await service.update(session, context, supervisor_id, body)
        result = await service.read(session, context, supervisor_id)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.put(
    "/{supervisor_id}/handlers/{membership_id}",
    summary="Add or change a handler — scope 2",
)
async def set_handler(
    supervisor_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: HandlerInput,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> HandlerRead:
    """Its own route and its own permission. §10's two scopes are independent, and a payload
    carrying both would have made the looser permission decide the stricter one."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="supervisor.handler_set",
        payload={
            "supervisor_id": str(supervisor_id),
            "membership_id": str(membership_id),
            **body.model_dump(mode="json"),
        },
    ) as execution:
        if execution.is_replay:
            return HandlerRead.model_validate(execution.replay_body)

        row = await handler_service.set_handler(
            session,
            context,
            supervisor_id,
            membership_id,
            body.role,
            expected_version=body.expected_version,
        )
        found = await service.read(session, context, supervisor_id)
        result = next(
            handler for handler in found.handlers if handler.membership_id == membership_id
        )
        assert result.id == row.id
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.delete(
    "/{supervisor_id}/handlers/{membership_id}", summary="Remove a handler — scope 2"
)
async def remove_handler(
    supervisor_id: uuid.UUID,
    membership_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True)] = 1,
) -> dict[str, str]:
    """Removing yourself is allowed. Removing somebody who outranks you is not."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="supervisor.handler_removed",
        payload={
            "supervisor_id": str(supervisor_id),
            "membership_id": str(membership_id),
            "expected_version": expected_version,
        },
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        await handler_service.remove_handler(
            session,
            context,
            supervisor_id,
            membership_id,
            expected_version=expected_version,
        )
        result = {"removed": str(membership_id)}
        execution.complete_json(status_code=status.HTTP_200_OK, body=result)
        return result


@router.put("/{supervisor_id}/schedule", summary="When this supervisor runs")
async def set_schedule(
    supervisor_id: uuid.UUID,
    body: SupervisorScheduleWrite,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SupervisorScheduleRead:
    """`schedule`, not `edit_draft`: deciding when something starts happening is its own verb.

    Validated by the Job's own recurrence module, so a Supervisor schedule cannot be accepted
    where the identical Job schedule would have been refused.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="supervisor.schedule",
        payload={"supervisor_id": str(supervisor_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return SupervisorScheduleRead.model_validate(execution.replay_body)

        await service.set_schedule(session, context, supervisor_id, body)
        found = await service.read(session, context, supervisor_id)
        if found.schedule is None:  # pragma: no cover — set_schedule just wrote one
            raise RuntimeError("the schedule was written but did not read back")
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=found.schedule.model_dump(mode="json")
        )
        return found.schedule


@router.post("/{supervisor_id}/archive", summary="Archive a supervisor")
async def archive(
    supervisor_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True)] = 1,
) -> dict[str, str]:
    """Archived, never deleted. What an organisation arranged is evidence of what it decided."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="supervisor.archive",
        payload={"supervisor_id": str(supervisor_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        supervisor = await service.archive(
            session, context, supervisor_id, expected_version
        )
        result = {
            "id": str(supervisor.id),
            "version": str(supervisor.version),
            "status": supervisor.status,
        }
        execution.complete_json(status_code=status.HTTP_200_OK, body=result)
        return result
