"""Editing the execution graph a proposal produced.

PLAN §7: *"Users may add, edit, delete, duplicate, merge, reorder, change dependencies, compare
AI/human changes and rerun only a selected section."* Every one of those is a function here, and
they all work on ordinary rows — a step the model proposed and a step somebody typed are the same
kind of thing the moment they exist.

**`edited` is what makes the comparison possible.** Changing an AI-proposed step sets it, and
never clears it. `source = 'ai' AND edited` is precisely "the model suggested this and a human
corrected it", which is the question §7 asks and the one an evaluation of the model needs
answered honestly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.objectives.models import Objective
from uboss.modules.objectives.proposal_models import (
    ObjectiveStep,
    StepDependency,
    StepSource,
)

#: The same ceiling the proposal has. A graph past this is one nobody reviews properly, and the
#: honest answer is a narrower objective.
MAX_STEPS = 40


async def add(
    session: AsyncSession,
    context: SecurityContext,
    objective_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    detail: str | None = None,
    responsible_role: str | None = None,
    after_step_id: uuid.UUID | None = None,
) -> ObjectiveStep:
    """A step somebody adds by hand. `source = 'human'` from the start."""
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    objective = await _editable(session, objective_id)

    steps = await _steps(session, objective_id)
    if len(steps) >= MAX_STEPS:
        raise ValidationFailed(
            f"A plan can hold {MAX_STEPS} steps. Narrow the objective rather than growing it."
        )

    #  Inserted after a named step, or at the end. Positions are renumbered rather than left with
    #  gaps: a gap is a position somebody will eventually try to use.
    at = len(steps) + 1
    if after_step_id is not None:
        anchor = next((step for step in steps if step.id == after_step_id), None)
        if anchor is None:
            raise NotFound("No such step.")
        at = anchor.position + 1
        for step in steps:
            if step.position >= at:
                step.position += 1
        await session.flush()

    row = ObjectiveStep(
        tenant_id=context.tenant_id,
        objective_id=objective_id,
        position=at,
        kind=kind,
        title=title.strip(),
        detail=detail,
        responsible_role=responsible_role,
        source=StepSource.HUMAN,
    )
    session.add(row)
    await session.flush()

    await _record(session, context, objective, "objective.step.added", row.id, {"kind": kind})
    return row


async def update(
    session: AsyncSession,
    context: SecurityContext,
    step_id: uuid.UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> ObjectiveStep:
    """Edit a step.

    An AI-proposed step becomes `edited` and stays `edited`. Clearing the flag when somebody
    changed it back would make the comparison lie in the model's favour, which is the one
    direction it must not lie in.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    step = await _step(session, step_id)
    await _editable(session, step.objective_id)

    if step.version != expected_version:
        raise Conflict("Somebody else changed this step. Reload the plan and try again.")

    allowed = {"kind", "title", "detail", "responsible_role", "rationale"}
    for field, value in changes.items():
        if field in allowed:
            setattr(step, field, value)

    if step.source == StepSource.AI:
        step.edited = True
    step.version += 1
    await session.flush()

    objective = await _editable(session, step.objective_id)
    await _record(
        session,
        context,
        objective,
        "objective.step.updated",
        step.id,
        {"fields": sorted(field for field in changes if field in allowed)},
    )
    return step


async def remove(
    session: AsyncSession, context: SecurityContext, step_id: uuid.UUID, expected_version: int
) -> None:
    """Delete a step, and the dependencies on either side of it.

    Deleted rather than archived. A step in an unpublished plan is a draft, not a record — the
    version that gets published is the evidence, and it does not exist yet.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    step = await _step(session, step_id)
    objective = await _editable(session, step.objective_id)
    if step.version != expected_version:
        raise Conflict("Somebody else changed this step. Reload the plan and try again.")

    objective_id = step.objective_id
    await session.delete(step)
    await session.flush()
    await _renumber(session, objective_id)

    await _record(session, context, objective, "objective.step.removed", step_id, {})


async def duplicate(
    session: AsyncSession, context: SecurityContext, step_id: uuid.UUID
) -> ObjectiveStep:
    """Copy a step, immediately after the original.

    The copy is `human` whatever the original was: a person chose to make it, and attributing it
    to the model would inflate what the model produced.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    step = await _step(session, step_id)
    await _editable(session, step.objective_id)

    return await add(
        session,
        context,
        step.objective_id,
        kind=step.kind,
        title=f"{step.title} (copy)"[:300],
        detail=step.detail,
        responsible_role=step.responsible_role,
        after_step_id=step.id,
    )


async def merge(
    session: AsyncSession,
    context: SecurityContext,
    step_id: uuid.UUID,
    into_step_id: uuid.UUID,
    *,
    expected_version: int,
) -> ObjectiveStep:
    """Fold one step into another.

    The absorbed step's detail is appended rather than discarded — somebody wrote it, and a merge
    that silently dropped half of what it merged would be a delete wearing a friendlier name.
    Its dependencies move to the survivor, minus any that would point at itself.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    if step_id == into_step_id:
        raise ValidationFailed("A step cannot be merged into itself.")

    source = await _step(session, step_id)
    target = await _step(session, into_step_id)
    #  Guarded on the step that disappears. Every other mutation on a step carries its version and
    #  this one — the only one that deletes — did not, so a merge could absorb a step somebody had
    #  rewritten a moment earlier and take the rewrite with it.
    if source.version != expected_version:
        raise Conflict(
            "That step was changed by somebody else while you were editing. "
            "Reload the plan and apply your change again."
        )
    if source.objective_id != target.objective_id:
        raise ValidationFailed("Those steps belong to different objectives.")
    objective = await _editable(session, source.objective_id)

    if source.detail:
        target.detail = (
            f"{target.detail}\n\n{source.detail}" if target.detail else source.detail
        )
    if source.source == StepSource.AI or target.source == StepSource.AI:
        target.edited = True
    target.version += 1

    #  Move the edges, skipping the ones that would make the survivor wait for itself.
    for edge in await _edges_touching(session, source.id):
        if edge.step_id == source.id and edge.depends_on_step_id != target.id:
            session.add(
                StepDependency(
                    tenant_id=context.tenant_id,
                    step_id=target.id,
                    depends_on_step_id=edge.depends_on_step_id,
                )
            )
        elif edge.depends_on_step_id == source.id and edge.step_id != target.id:
            session.add(
                StepDependency(
                    tenant_id=context.tenant_id,
                    step_id=edge.step_id,
                    depends_on_step_id=target.id,
                )
            )
    objective_id = source.objective_id
    await session.delete(source)
    await session.flush()
    await _renumber(session, objective_id)

    await _record(
        session,
        context,
        objective,
        "objective.step.merged",
        target.id,
        {"absorbed": str(step_id)},
    )
    return target


async def reorder(
    session: AsyncSession,
    context: SecurityContext,
    objective_id: uuid.UUID,
    order: list[uuid.UUID],
) -> None:
    """Set the order of the whole plan.

    The full list, not a move: sending "step X to position 4" needs the server and the client to
    agree on what the other positions were, and after a concurrent edit they do not.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    objective = await _editable(session, objective_id)

    steps = await _steps(session, objective_id)
    known = {step.id for step in steps}
    if set(order) != known:
        raise ValidationFailed(
            "That ordering does not match the plan. Reload it and try again."
        )

    #  Moved out of the way first: positions are unique per objective, so assigning them one at a
    #  time collides with whatever currently holds the target position.
    for step in steps:
        step.position += len(steps)
    await session.flush()

    by_id = {step.id: step for step in steps}
    for position, step_id in enumerate(order, start=1):
        by_id[step_id].position = position
    await session.flush()

    await _record(
        session, context, objective, "objective.plan.reordered", objective_id, {}
    )


async def set_dependencies(
    session: AsyncSession,
    context: SecurityContext,
    step_id: uuid.UUID,
    depends_on: list[uuid.UUID],
    *,
    expected_version: int,
) -> None:
    """Replace what this step waits for.

    A dependency that would close a loop is refused by the database. The error surfaces here, at
    the point somebody drew the edge, rather than at the end of an unrelated request.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    step = await _step(session, step_id)
    #  The whole set is replaced, so an edit made against an older view of it silently drops
    #  whatever was added in between.
    if step.version != expected_version:
        raise Conflict(
            "That step was changed by somebody else while you were editing. "
            "Reload the plan and apply your change again."
        )
    objective = await _editable(session, step.objective_id)

    steps = {row.id for row in await _steps(session, step.objective_id)}
    unknown = [target for target in depends_on if target not in steps]
    if unknown:
        raise ValidationFailed("A step cannot wait for something outside this plan.")
    if step_id in depends_on:
        raise ValidationFailed("A step cannot wait for itself.")

    await session.execute(
        delete(StepDependency).where(StepDependency.step_id == step_id)
    )
    await session.flush()

    for target in depends_on:
        session.add(
            StepDependency(
                tenant_id=context.tenant_id,
                step_id=step_id,
                depends_on_step_id=target,
            )
        )
    #  The cycle trigger fires here.
    await session.flush()

    #  `edited` is about the model's work: an AI step a person changed. The **version** is not —
    #  it is the optimistic guard, and it belongs on any step whose dependencies just changed.
    #  Bumping it only for AI steps left every hand-written step with a version that never moved,
    #  so the `expected_version` this function now checks would have been satisfied by any stale
    #  value at all. `update`, ten lines up, already had the split the right way round.
    if step.source == StepSource.AI:
        step.edited = True
    step.version += 1
    await session.flush()

    await _record(
        session,
        context,
        objective,
        "objective.step.dependencies_set",
        step_id,
        {"count": len(depends_on)},
    )


# ---------------------------------------------------------------------------- internals


async def _steps(session: AsyncSession, objective_id: uuid.UUID) -> list[ObjectiveStep]:
    return list(
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


async def _step(session: AsyncSession, step_id: uuid.UUID) -> ObjectiveStep:
    step = (
        await session.execute(select(ObjectiveStep).where(ObjectiveStep.id == step_id))
    ).scalar_one_or_none()
    if step is None:
        raise NotFound("No such step.")
    return step


async def _edges_touching(
    session: AsyncSession, step_id: uuid.UUID
) -> list[StepDependency]:
    return list(
        (
            await session.execute(
                select(StepDependency).where(
                    (StepDependency.step_id == step_id)
                    | (StepDependency.depends_on_step_id == step_id)
                )
            )
        )
        .scalars()
        .all()
    )


async def _renumber(session: AsyncSession, objective_id: uuid.UUID) -> None:
    """Close the gap a delete left.

    Gaps are not wrong in themselves, but a position somebody can see and a position the database
    holds should be the same number — otherwise "step 4" means two different things depending on
    who is saying it.
    """
    steps = await _steps(session, objective_id)
    for step in steps:
        step.position += len(steps) + 1
    await session.flush()
    for position, step in enumerate(steps, start=1):
        step.position = position
    await session.flush()


async def _editable(session: AsyncSession, objective_id: uuid.UUID) -> Objective:
    objective = (
        await session.execute(select(Objective).where(Objective.id == objective_id))
    ).scalar_one_or_none()
    if objective is None:
        raise NotFound("No such objective.")
    if not objective.is_editable:
        raise ValidationFailed(
            f"This objective is {objective.status.replace('_', ' ')} and its plan cannot be "
            "changed."
        )
    return objective


async def _record(
    session: AsyncSession,
    context: SecurityContext,
    objective: Objective,
    action: str,
    entity_id: uuid.UUID,
    detail: dict[str, Any],
) -> None:
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action=action,
        resource_type="objective",
        resource_id=objective.id,
        actor=context,
        detail={"step_id": str(entity_id), **detail},
    )
