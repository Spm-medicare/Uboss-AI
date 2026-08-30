"""Publishing an objective: the summary, the submission, and the approval.

Three routes because they are three decisions by up to two people. A single "publish" call would
collapse the separation PLAN §14 requires into one request that one person makes.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.core.permissions import Action
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.objectives import publish as publishing
from uboss.modules.objectives.models import ObjectiveVersion
from uboss.modules.objectives.publish_schemas import (
    PublishAction,
    PublishSummary,
    VersionRead,
    WarningRead,
)

router = APIRouter(prefix="/objectives/{objective_id}", tags=["objectives"])


@router.get("/publish", summary="What publishing this would mean")
async def summary(
    objective_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> PublishSummary:
    """PLAN §7's publish screen: owners, steps, cost, warnings and the approval route.

    Computed on every read. A stored summary could describe an objective that has since changed,
    and a summary that claims to be current and is not is worse than none.
    """
    result = await publishing.summary(session, context, objective_id)
    return PublishSummary(
        **{
            field: getattr(result, field)
            for field in PublishSummary.model_fields
            if field != "warnings"
        },
        warnings=[
            WarningRead(code=warning.code, message=warning.message)
            for warning in result.warnings
        ],
    )


@router.post("/submit", summary="Send for approval")
async def submit(
    objective_id: uuid.UUID,
    body: PublishAction,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """`edit_draft`, not `publish`.

    Submitting is the last act of writing. Requiring the publish permission for it would mean
    only people who can approve could ask for approval.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.submit",
        payload={"objective_id": str(objective_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        objective = await publishing.submit(
            session, context, objective_id, body.expected_version
        )
        result = {"status": objective.status, "version": str(objective.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/withdraw", summary="Take it back out of the queue")
async def withdraw(
    objective_id: uuid.UUID,
    body: PublishAction,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Somebody spots a mistake after submitting. Ordinary, and necessary."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.withdraw",
        payload={"objective_id": str(objective_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        objective = await publishing.withdraw(
            session, context, objective_id, body.expected_version
        )
        result = {"status": objective.status, "version": str(objective.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/publish", summary="Approve and publish")
async def approve(
    objective_id: uuid.UUID,
    body: PublishAction,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Approval creates the immutable version — PLAN §7.

    Four things are checked, and none of them by the screen: the caller holds `publish` (high
    risk, so a recent password proof), they are the named approver, they did not submit it, and
    the version they read is the version they are approving.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.publish",
        payload={"objective_id": str(objective_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        version = await publishing.publish(
            session, context, objective_id, body.expected_version
        )
        result = {"version_id": str(version.id), "version_no": str(version.version_no)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.get("/versions", summary="What has been published")
async def versions(
    objective_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> list[VersionRead]:
    """Newest first. Every one of these is immutable and is the evidence of what was approved."""
    await guard.authorise(session, context, Action.VIEW)

    rows = list(
        (
            await session.execute(
                select(ObjectiveVersion)
                .where(ObjectiveVersion.objective_id == objective_id)
                .order_by(ObjectiveVersion.version_no.desc())
            )
        )
        .scalars()
        .all()
    )

    names = await _names(session, rows)
    return [
        VersionRead(
            id=row.id,
            version_no=row.version_no,
            title=row.title,
            published_at=row.published_at.isoformat(),
            approved_by_name=names.get(row.approved_by_membership_id),
            published_by_name=names.get(row.published_by_membership_id),
            step_count=len(row.snapshot.get("plan", [])),
        )
        for row in rows
    ]


async def _names(
    session: AsyncSession, rows: list[ObjectiveVersion]
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
