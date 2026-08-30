"""Creating and editing an Objective draft.

The same four things every mutation in this repository does: authorise through the one guard,
match the version the caller read, write an audit event, and commit all of it together.

**Which permission covers what.** PLAN §14's vocabulary, nothing invented:

* Reading an objective is `view`.
* Creating and editing a draft is `edit_draft` — literally the verb.
* Publishing is `publish`, and it arrives in 3.3 with the approval route.

**Editing is refused unless the objective is editable.** A published version is immutable, and
`analyzing` is excluded too: a proposal is being worked out against these fields, and changing
them underneath it would produce a plan for an objective that no longer exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.objectives.models import (
    Objective,
    ObjectiveCurrentStep,
    ObjectiveStatus,
)
from uboss.modules.objectives.schemas import (
    CurrentStepRead,
    ObjectiveCard,
    ObjectiveCreate,
    ObjectiveList,
    ObjectiveRead,
    ObjectiveUpdate,
    PersonRef,
)

#: The workbook's sheet has twenty numbered rows. More than this in one objective is a process
#: nobody can review in one sitting, and the answer is to split the objective — which is a better
#: outcome than a form that scrolls for a minute.
MAX_STEPS = 60


def _now() -> datetime:
    return datetime.now(UTC)


async def list_objectives(
    session: AsyncSession,
    context: SecurityContext,
    *,
    status: str | None = None,
    include_archived: bool = False,
) -> ObjectiveList:
    """The cards — PLAN §7's list view.

    `is_empty` distinguishes "this workspace has no objectives" from "none match that filter".
    On screen those look identical and need different words: one offers to create the first one,
    the other offers to clear the filter.
    """
    await guard.authorise(session, context, Action.VIEW)

    counts = (
        select(
            ObjectiveCurrentStep.objective_id.label("objective_id"),
            func.count().label("step_count"),
        )
        .group_by(ObjectiveCurrentStep.objective_id)
        .subquery()
    )

    statement = (
        select(Objective, Membership.display_name, func.coalesce(counts.c.step_count, 0))
        .outerjoin(Membership, Membership.id == Objective.owner_membership_id)
        .outerjoin(counts, counts.c.objective_id == Objective.id)
        .order_by(Objective.updated_at.desc())
    )
    if not include_archived:
        statement = statement.where(Objective.archived_at.is_(None))
    if status:
        statement = statement.where(Objective.status == status)

    rows = (await session.execute(statement)).all()

    total = (
        await session.execute(
            select(func.count()).select_from(Objective).where(Objective.archived_at.is_(None))
        )
    ).scalar_one()

    return ObjectiveList(
        objectives=[
            ObjectiveCard(
                id=objective.id,
                title=objective.title,
                status=objective.status,
                department=objective.department,
                priority=objective.priority,
                owner_name=owner_name,
                target_date=objective.target_date,
                step_count=step_count,
                updated_at=objective.updated_at,
            )
            for objective, owner_name, step_count in rows
        ],
        is_empty=total == 0,
    )


async def read(
    session: AsyncSession, context: SecurityContext, objective_id: uuid.UUID
) -> ObjectiveRead:
    await guard.authorise(session, context, Action.VIEW)
    objective = await _get(session, objective_id)
    return await _describe(session, objective)


async def people(session: AsyncSession, context: SecurityContext) -> list[PersonRef]:
    """Who can be named as owner or approver.

    Everybody active in this workspace. Only a name and a job title leave the server — the
    address stays in `users`, which the application role cannot read anyway.
    """
    await guard.authorise(session, context, Action.VIEW)
    members = (
        (
            await session.execute(
                select(Membership)
                .where(Membership.status == "active")
                .order_by(Membership.display_name)
            )
        )
        .scalars()
        .all()
    )
    return [
        PersonRef(
            membership_id=member.id,
            display_name=member.display_name,
            job_title=member.job_title,
        )
        for member in members
    ]


async def create(
    session: AsyncSession, context: SecurityContext, payload: ObjectiveCreate
) -> Objective:
    """Start a draft. Only a title is needed.

    PLAN §6's journey begins at "Create/Open Draft" — a form that demanded eight groups before it
    would save anything is a form people fill in somewhere else first, and then paste.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    objective = Objective(
        tenant_id=context.tenant_id,
        title=payload.title.strip(),
        department=payload.department,
        #  The person starting it is the owner until somebody says otherwise. An unowned
        #  objective is one nobody is answerable for.
        owner_membership_id=context.membership_id,
        created_by_membership_id=context.membership_id,
        status=ObjectiveStatus.DRAFT,
    )
    session.add(objective)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="objective.created",
        resource_type="objective",
        resource_id=objective.id,
        actor=context,
        detail={"title": objective.title},
    )
    return objective


#: Everything `ObjectiveUpdate` can set on the row itself. `current_steps` is handled separately
#: because it is a child table, and `expected_version` is the concurrency check rather than data.
_SCALAR_FIELDS = frozenset(
    {
        "title",
        "department",
        "owner_membership_id",
        "expected_result",
        "workload_count",
        "workload_unit",
        "target_date",
        "description",
        "priority",
        "baseline",
        "success_measures",
        "included_work",
        "excluded_work",
        "stakeholders",
        "geography",
        "start_date",
        "urgency",
        "budget_note",
        "policy_constraints",
        "dependencies",
        "risk_note",
        "approver_membership_id",
        "visibility",
        "handles_sensitive_data",
        "sensitive_data_note",
        "ai_assistance",
        "human_checkpoints",
    }
)


async def update(
    session: AsyncSession,
    context: SecurityContext,
    objective_id: uuid.UUID,
    payload: ObjectiveUpdate,
) -> Objective:
    """Save a draft — both the autosave and the explicit Save Draft.

    They write the same thing; what differs is how often and what the screen says. Making them
    one path means an autosave can never save something a deliberate save would not.

    **The step table is replaced wholesale**, not diffed. It is edited as a grid — rows are
    reordered and removed — and a diff computed on the client would be a second implementation of
    what the server already does, disagreeing with it the first time somebody dragged a row.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    objective = await _get(session, objective_id)
    if not objective.is_editable:
        raise ValidationFailed(
            f"This objective is {objective.status.replace('_', ' ')} and cannot be edited."
        )
    if objective.version != payload.expected_version:
        raise Conflict(
            "Somebody else saved this objective while you were editing. Reload it and apply "
            "your change again."
        )

    changes = payload.model_dump(exclude_unset=True)
    changes.pop("expected_version", None)
    steps = changes.pop("current_steps", None)

    for field, value in changes.items():
        if field not in _SCALAR_FIELDS:  # pragma: no cover - schema forbids extras
            continue
        setattr(objective, field, value)

    if payload.owner_membership_id is not None:
        await _require_member(session, payload.owner_membership_id, "owner")
    if payload.approver_membership_id is not None:
        await _require_member(session, payload.approver_membership_id, "approver")

    if steps is not None:
        await _replace_steps(session, context, objective, steps)

    objective.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="objective.updated",
        resource_type="objective",
        resource_id=objective.id,
        actor=context,
        #  Which fields, never their values. An objective carries a company's plans, and an audit
        #  trail is not the place to keep a second copy of them.
        detail={"fields": sorted(changes), "steps_replaced": steps is not None},
    )
    return objective


async def archive(
    session: AsyncSession,
    context: SecurityContext,
    objective_id: uuid.UUID,
    expected_version: int,
) -> Objective:
    """Archive, never delete. PLAN §30 — every run recorded against it needs it to still exist."""
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    objective = await _get(session, objective_id)
    if objective.version != expected_version:
        raise Conflict("Somebody else changed this objective. Reload it and try again.")
    if objective.archived_at is not None:
        return objective

    objective.archived_at = _now()
    objective.status = ObjectiveStatus.ARCHIVED
    objective.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="objective.archived",
        resource_type="objective",
        resource_id=objective.id,
        actor=context,
        detail={"title": objective.title},
    )
    return objective


# ---------------------------------------------------------------------------- internals


async def _get(session: AsyncSession, objective_id: uuid.UUID) -> Objective:
    objective = (
        await session.execute(select(Objective).where(Objective.id == objective_id))
    ).scalar_one_or_none()
    if objective is None:
        #  Not found and not permitted are the same answer. Row-level security has already made
        #  another organisation's rows invisible, so this is the truth as well as the safe reply.
        raise NotFound("No such objective.")
    return objective


async def _require_member(
    session: AsyncSession, membership_id: uuid.UUID, role: str
) -> Membership:
    member = (
        await session.execute(select(Membership).where(Membership.id == membership_id))
    ).scalar_one_or_none()
    if member is None:
        raise ValidationFailed(f"That {role} is not a member of this workspace.")
    return member


async def _replace_steps(
    session: AsyncSession,
    context: SecurityContext,
    objective: Objective,
    steps: list[dict[str, Any]],
) -> None:
    if len(steps) > MAX_STEPS:
        raise ValidationFailed(
            f"An objective can describe up to {MAX_STEPS} steps. Split it into two objectives "
            "rather than one nobody can review in a sitting."
        )

    await session.execute(
        delete(ObjectiveCurrentStep).where(
            ObjectiveCurrentStep.objective_id == objective.id
        )
    )
    #  Flushed before the inserts, so the unique constraint on `(objective, position)` sees the
    #  deletes first. Without this a reorder that reuses a position fails on a row that is about
    #  to disappear.
    await session.flush()

    for index, step in enumerate(steps, start=1):
        session.add(
            ObjectiveCurrentStep(
                tenant_id=context.tenant_id,
                objective_id=objective.id,
                position=index,
                **{key: value for key, value in step.items() if value not in (None, "")},
            )
        )
    await session.flush()


async def _describe(session: AsyncSession, objective: Objective) -> ObjectiveRead:
    steps = (
        (
            await session.execute(
                select(ObjectiveCurrentStep)
                .where(ObjectiveCurrentStep.objective_id == objective.id)
                .order_by(ObjectiveCurrentStep.position)
            )
        )
        .scalars()
        .all()
    )

    names: dict[uuid.UUID, str] = {}
    wanted = [
        member_id
        for member_id in (objective.owner_membership_id, objective.approver_membership_id)
        if member_id is not None
    ]
    if wanted:
        for member in (
            (await session.execute(select(Membership).where(Membership.id.in_(wanted))))
            .scalars()
            .all()
        ):
            names[member.id] = member.display_name

    return ObjectiveRead(
        **{
            column: getattr(objective, column)
            for column in (
                "id",
                "title",
                "department",
                "owner_membership_id",
                "expected_result",
                "workload_count",
                "workload_unit",
                "target_date",
                "description",
                "baseline",
                "success_measures",
                "included_work",
                "excluded_work",
                "stakeholders",
                "geography",
                "start_date",
                "urgency",
                "budget_note",
                "policy_constraints",
                "dependencies",
                "risk_note",
                "approver_membership_id",
                "handles_sensitive_data",
                "sensitive_data_note",
                "human_checkpoints",
                "published_version_id",
                "archived_at",
                "version",
                "created_at",
                "updated_at",
            )
        },
        status=objective.status,
        priority=objective.priority,
        visibility=objective.visibility,
        ai_assistance=objective.ai_assistance,
        owner_name=names.get(objective.owner_membership_id)
        if objective.owner_membership_id
        else None,
        approver_name=names.get(objective.approver_membership_id)
        if objective.approver_membership_id
        else None,
        current_steps=[
            CurrentStepRead.model_validate(step, from_attributes=True) for step in steps
        ],
        is_editable=objective.is_editable,
    )
