"""Agents over HTTP.

Deliberately the same shape as the Objective's and the Job's routes: list, lists, create, read,
save, archive. A person who has used one Builder should find the next behaves the same way.

One route is not in the others — `POST /agents/{id}/tools/{tool_id}/grant`. §9: *"Tool suggestions
never grant access."* Saving the form proposes a tool; this grants it, and it is behind
`manage_access` rather than `edit_draft`, because designing an agent and deciding what it may
reach are different authorities.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, Query, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.agents import agent_service as service
from uboss.modules.agents.agent_schemas import (
    AgentCreate,
    AgentList,
    AgentRead,
    AgentUpdate,
    AgentWorkbookLists,
    ToolGrant,
    ToolRead,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", summary="The agents in this workspace")
async def list_agents(
    context: CurrentContext,
    session: SessionDep,
    agent_status: Annotated[str | None, Query(alias="status")] = None,
    job_id: Annotated[uuid.UUID | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> AgentList:
    """`is_empty` separates "no agents yet" from "none match that filter" — different words."""
    return await service.list_agents(
        session,
        context,
        status=agent_status,
        job_id=job_id,
        include_archived=include_archived,
    )


@router.get("/lists", summary="Form 4's suggested values")
async def workbook_lists(context: CurrentContext, session: SessionDep) -> AgentWorkbookLists:
    """Triggers, frequencies, approvals, permissions and the rest, from the approved sheet.

    Served rather than kept in the frontend: a second copy of an approved list is a copy that
    drifts. Suggestions, not validation — each ends in `Other`. The two closed sets, Form 4's six
    error situations and §9's six access choices, are separate fields here for that reason.
    """
    return AgentWorkbookLists()


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start an agent draft")
async def create(
    body: AgentCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """A name is enough. Naming a job carries its objective and approved version across."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="agent.create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        agent = await service.create(session, context, body)
        result = {"id": str(agent.id), "version": str(agent.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.get("/{agent_id}", summary="One agent, in full")
async def read(
    agent_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> AgentRead:
    """Every group in one response, so the form renders from one request."""
    return await service.read(session, context, agent_id)


@router.put("/{agent_id}", summary="Save the agent draft")
async def update(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> AgentRead:
    """`expected_version` is what stops one person's save from discarding another's."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="agent.update",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return AgentRead.model_validate(execution.replay_body)

        await service.update(session, context, agent_id, body)
        result = await service.read(session, context, agent_id)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/{agent_id}/tools/{tool_id}/grant", summary="Grant or withdraw one tool")
async def grant_tool(
    agent_id: uuid.UUID,
    tool_id: uuid.UUID,
    body: ToolGrant,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ToolRead:
    """§9: *"Tool suggestions never grant access."* This is the act that does.

    Behind `manage_access`, and it records who granted it and when — so an access review reads a
    name and a time rather than inferring both from a form's history.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="agent.tool_grant",
        payload={"agent_id": str(agent_id), "tool_id": str(tool_id), **body.model_dump()},
    ) as execution:
        if execution.is_replay:
            return ToolRead.model_validate(execution.replay_body)

        tool = await service.grant_tool(
            session,
            context,
            agent_id,
            tool_id,
            granted=body.granted,
            expected_version=body.expected_version,
        )
        result = ToolRead(
            id=tool.id,
            position=tool.position,
            tool=tool.tool,
            scopes=list(tool.scopes),
            purpose=tool.purpose,
            granted=tool.granted,
            granted_by_membership_id=tool.granted_by_membership_id,
            granted_at=tool.granted_at,
        )
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/{agent_id}/archive", summary="Archive an agent")
async def archive(
    agent_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True)] = 1,
) -> dict[str, str]:
    """Archived, not deleted. What an organisation designed is evidence of what it decided."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="agent.archive",
        payload={"agent_id": str(agent_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        agent = await service.archive(session, context, agent_id, expected_version)
        result = {"id": str(agent.id), "version": str(agent.version), "status": agent.status}
        execution.complete_json(status_code=status.HTTP_200_OK, body=result)
        return result
