"""The analysis and the plan, over HTTP.

One route per thing a person does — PLAN §7 lists them: *"add, edit, delete, duplicate, merge,
reorder, change dependencies"*. Separate routes rather than one "save the plan" call, because
each is a distinct intent with its own audit line, and a bulk save would flatten "merged two
steps" into "the plan changed".
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep, SettingsDep
from uboss.core.idempotency import require_idempotency_key
from uboss.core.permissions import Action
from uboss.modules.identity import guard
from uboss.modules.objectives import analysis, graph
from uboss.modules.objectives.proposal_models import (
    STAGE_ORDER,
    AnalysisEvent,
    ObjectiveProposal,
    ObjectiveStep,
    StepDependency,
    StepSource,
)
from uboss.modules.objectives.proposal_schemas import (
    AnalysisRead,
    PlanRead,
    PlanReorder,
    StageRead,
    StepCreate,
    StepDelete,
    StepDependencies,
    StepMerge,
    StepRead,
    StepUpdate,
)

router = APIRouter(prefix="/objectives/{objective_id}", tags=["objectives"])


@router.get("/plan", summary="The execution graph and the analysis behind it")
async def read_plan(
    objective_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> PlanRead:
    """PLAN §6's "editable generated output", plus the real timeline that produced it.

    `never_analysed` separates "no plan yet" from "a plan somebody emptied" — the same on screen,
    and different things to say.
    """
    await guard.authorise(session, context, Action.VIEW)
    return await _plan(session, objective_id)


@router.post("/analyse", summary="Ask Claude for an execution graph")
async def analyse(
    objective_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> PlanRead:
    """PLAN §7 — Claude proposes; it never writes to governed state.

    The six stages run and record themselves as they go, so what the screen shows afterwards is a
    record rather than an animation. The proposal is stored unchanged and the steps created from
    it are ordinary editable rows.

    Returns 200 even when the analysis failed: the plan comes back with the failure on it, which
    is what the screen needs to show. An HTTP error would lose the timeline that explains where
    it stopped.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.analyse",
        payload={"objective_id": str(objective_id)},
    ) as execution:
        if execution.is_replay:
            return PlanRead.model_validate(execution.replay_body)

        await analysis.start(session, settings, context, objective_id)
        result = await _plan(session, objective_id)
        execution.complete_json(status_code=200, body=result.model_dump(mode="json"))
        return result


@router.post("/plan/steps", status_code=status.HTTP_201_CREATED, summary="Add a step")
async def add_step(
    objective_id: uuid.UUID,
    body: StepCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """A step somebody adds by hand. Recorded as `human`, whatever the rest of the plan is."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.step.add",
        payload={"objective_id": str(objective_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        step = await graph.add(
            session,
            context,
            objective_id,
            kind=body.kind,
            title=body.title,
            detail=body.detail,
            responsible_role=body.responsible_role,
            after_step_id=body.after_step_id,
        )
        result = {"id": str(step.id), "version": str(step.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.patch("/plan/steps/{step_id}", summary="Edit a step")
async def update_step(
    objective_id: uuid.UUID,
    step_id: uuid.UUID,
    body: StepUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Editing an AI-proposed step marks it, and the mark never clears.

    Clearing it when somebody changed the step back would make the AI/human comparison lie in the
    model's favour — the one direction it must not lie in.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.step.update",
        payload={"step_id": str(step_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
        step = await graph.update(
            session,
            context,
            step_id,
            expected_version=body.expected_version,
            changes=changes,
        )
        result = {"id": str(step.id), "version": str(step.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/plan/steps/{step_id}/delete", summary="Remove a step")
async def delete_step(
    objective_id: uuid.UUID,
    step_id: uuid.UUID,
    body: StepDelete,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """A POST rather than a DELETE, because it carries `expected_version` in a body.

    A DELETE with a body is legal and widely mishandled by proxies and clients; losing the
    version in transit would turn a guarded delete into an unguarded one.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.step.delete",
        payload={"step_id": str(step_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        await graph.remove(session, context, step_id, body.expected_version)
        result = {"status": "removed", "id": str(step_id)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/plan/steps/{step_id}/duplicate", summary="Duplicate a step")
async def duplicate_step(
    objective_id: uuid.UUID,
    step_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """The copy is `human`: a person chose to make it."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.step.duplicate",
        payload={"step_id": str(step_id)},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        step = await graph.duplicate(session, context, step_id)
        result = {"id": str(step.id), "version": str(step.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/plan/steps/{step_id}/merge", summary="Merge one step into another")
async def merge_step(
    objective_id: uuid.UUID,
    step_id: uuid.UUID,
    body: StepMerge,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """The absorbed step's detail is appended, never dropped — somebody wrote it."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.step.merge",
        payload={"step_id": str(step_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        step = await graph.merge(
            session,
            context,
            step_id,
            body.into_step_id,
            expected_version=body.expected_version,
        )
        result = {"id": str(step.id), "version": str(step.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.put("/plan/order", summary="Reorder the plan")
async def reorder(
    objective_id: uuid.UUID,
    body: PlanReorder,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """The whole order. A partial move needs both sides to agree on the other positions."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.plan.reorder",
        payload={"objective_id": str(objective_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        await graph.reorder(session, context, objective_id, body.order)
        result = {"status": "reordered"}
        execution.complete_json(status_code=200, body=result)
        return result


@router.put("/plan/steps/{step_id}/dependencies", summary="Set what a step waits for")
async def set_dependencies(
    objective_id: uuid.UUID,
    step_id: uuid.UUID,
    body: StepDependencies,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """A dependency that would close a loop is refused by the database, at the point it is drawn."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="objective.step.dependencies",
        payload={"step_id": str(step_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        await graph.set_dependencies(
            session,
            context,
            step_id,
            body.depends_on,
            expected_version=body.expected_version,
        )
        result = {"status": "set"}
        execution.complete_json(status_code=200, body=result)
        return result


# ---------------------------------------------------------------------------- assembling


async def _plan(session: AsyncSession, objective_id: uuid.UUID) -> PlanRead:
    steps = list(
        (
            await session.execute(
                select(ObjectiveStep)
                .where(ObjectiveStep.objective_id == objective_id)
                .order_by(ObjectiveStep.position)
            )
        )
        .scalars()
        .all()
    )

    edges: dict[uuid.UUID, list[uuid.UUID]] = {}
    if steps:
        for edge in (
            (
                await session.execute(
                    select(StepDependency).where(
                        StepDependency.step_id.in_([step.id for step in steps])
                    )
                )
            )
            .scalars()
            .all()
        ):
            edges.setdefault(edge.step_id, []).append(edge.depends_on_step_id)

    latest = (
        await session.execute(
            select(ObjectiveProposal)
            .where(ObjectiveProposal.objective_id == objective_id)
            .order_by(ObjectiveProposal.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    analysis_read: AnalysisRead | None = None
    if latest is not None:
        events = list(
            (
                await session.execute(
                    select(AnalysisEvent)
                    .where(AnalysisEvent.proposal_id == latest.id)
                    .order_by(AnalysisEvent.at)
                )
            )
            .scalars()
            .all()
        )
        #  Last event per stage wins: a stage writes `running` and then `done`, and the second is
        #  the one worth showing.
        by_stage = {event.stage: event for event in events}

        analysis_read = AnalysisRead(
            id=latest.id,
            status=latest.status,
            stage=latest.stage,
            model=latest.model,
            input_tokens=latest.input_tokens,
            output_tokens=latest.output_tokens,
            latency_ms=latest.latency_ms,
            failure_detail=latest.failure_detail,
            started_at=latest.started_at,
            finished_at=latest.finished_at,
            #  All six, whether or not they ran. A stage with no state has not started, which is
            #  a thing the screen can draw honestly.
            stages=[
                StageRead(
                    stage=stage,
                    state=by_stage[stage].state if stage in by_stage else None,
                    detail=by_stage[stage].detail if stage in by_stage else None,
                    at=by_stage[stage].at if stage in by_stage else None,
                )
                for stage in STAGE_ORDER
            ],
            note=(latest.output or {}).get("note"),
        )

    ai_steps = [step for step in steps if step.source == StepSource.AI]
    return PlanRead(
        objective_id=objective_id,
        steps=[
            StepRead(
                id=step.id,
                position=step.position,
                kind=step.kind,
                title=step.title,
                detail=step.detail,
                responsible_role=step.responsible_role,
                replaces_current_step=step.replaces_current_step,
                rationale=step.rationale,
                source=step.source,
                edited=step.edited,
                version=step.version,
                depends_on=edges.get(step.id, []),
            )
            for step in steps
        ],
        analysis=analysis_read,
        never_analysed=latest is None,
        ai_steps=len(ai_steps),
        edited_ai_steps=sum(1 for step in ai_steps if step.edited),
        human_steps=len(steps) - len(ai_steps),
    )
