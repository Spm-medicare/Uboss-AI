"""Creating and editing a Job draft.

The same shape as the Objective's service, deliberately: authorise through the one guard, match
the version, replace child collections wholesale, write an audit event, commit together. A person
who has used one Builder should find the next one behaves the same way, and so should whoever
reads the code.

Permissions, in PLAN §14's vocabulary: reading is `view`, writing a draft is `edit_draft`, and
publishing is `publish` — which arrives in 4.4 with the approval route.
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
from uboss.modules.jobs.models import (
    Job,
    JobAssignmentRule,
    JobInput,
    JobStatus,
    JobStep,
    JobStepDependency,
    JobTool,
)
from uboss.modules.jobs.schemas import (
    AssignmentRuleRead,
    JobCard,
    JobCreate,
    JobInputRead,
    JobList,
    JobRead,
    JobStepRead,
    JobToolRead,
    JobUpdate,
)
from uboss.modules.objectives.models import Objective

#: Form 3's sheet has twenty numbered rows. Past this, nobody reviews a method properly and the
#: honest answer is two jobs.
MAX_STEPS = 60
MAX_RULES = 20
MAX_INPUTS = 40
MAX_TOOLS = 20


def _now() -> datetime:
    return datetime.now(UTC)


async def list_jobs(
    session: AsyncSession,
    context: SecurityContext,
    *,
    status: str | None = None,
    objective_id: uuid.UUID | None = None,
    include_archived: bool = False,
) -> JobList:
    await guard.authorise(session, context, Action.VIEW)

    counts = (
        select(JobStep.job_id.label("job_id"), func.count().label("step_count"))
        .group_by(JobStep.job_id)
        .subquery()
    )

    statement = (
        select(
            Job,
            Membership.display_name,
            Objective.title,
            func.coalesce(counts.c.step_count, 0),
        )
        .outerjoin(Membership, Membership.id == Job.owner_membership_id)
        .outerjoin(Objective, Objective.id == Job.objective_id)
        .outerjoin(counts, counts.c.job_id == Job.id)
        .order_by(Job.updated_at.desc())
    )
    if not include_archived:
        statement = statement.where(Job.archived_at.is_(None))
    if status:
        statement = statement.where(Job.status == status)
    if objective_id is not None:
        statement = statement.where(Job.objective_id == objective_id)

    rows = (await session.execute(statement)).all()
    total = (
        await session.execute(
            select(func.count()).select_from(Job).where(Job.archived_at.is_(None))
        )
    ).scalar_one()

    return JobList(
        jobs=[
            JobCard(
                id=job.id,
                name=job.name,
                status=job.status,
                department=job.department,
                owner_name=owner_name,
                objective_name=objective_name,
                trigger=job.trigger,
                frequency=job.frequency,
                step_count=step_count,
                updated_at=job.updated_at,
            )
            for job, owner_name, objective_name, step_count in rows
        ],
        is_empty=total == 0,
    )


async def read(
    session: AsyncSession, context: SecurityContext, job_id: uuid.UUID
) -> JobRead:
    await guard.authorise(session, context, Action.VIEW)
    return await _describe(session, await _get(session, job_id))


async def create(
    session: AsyncSession, context: SecurityContext, payload: JobCreate
) -> Job:
    """Start a draft from a name.

    If it names an objective, that objective's department is carried across rather than asked for
    again — Form 3 says both are *linked* from Form 2, and retyping is how two records of one
    fact start to disagree.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    department = payload.department
    if payload.objective_id is not None:
        objective = (
            await session.execute(
                select(Objective).where(Objective.id == payload.objective_id)
            )
        ).scalar_one_or_none()
        if objective is None:
            raise ValidationFailed("That objective is not in this workspace.")
        department = department or objective.department

    job = Job(
        tenant_id=context.tenant_id,
        name=payload.name.strip(),
        objective_id=payload.objective_id,
        department=department,
        owner_membership_id=context.membership_id,
        created_by_membership_id=context.membership_id,
        status=JobStatus.DRAFT,
    )
    session.add(job)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="job.created",
        resource_type="job",
        resource_id=job.id,
        actor=context,
        detail={"name": job.name},
    )
    return job


_SCALAR_FIELDS = frozenset(
    {
        "name",
        "objective_id",
        "objective_step_id",
        "department",
        "external_ref",
        "owner_membership_id",
        "current_person",
        "current_role",
        "trigger",
        "frequency",
        "high_level_work",
        "start_requirement",
        "completion_evidence",
        "normal_completion_time",
        "time_unit",
        "purpose",
        "expected_output",
        "quality_checks",
        "sla_note",
        "retry_policy",
        "failure_action",
        "escalation_to",
        "visibility",
        "approver_membership_id",
    }
)


async def update(
    session: AsyncSession,
    context: SecurityContext,
    job_id: uuid.UUID,
    payload: JobUpdate,
) -> Job:
    """Save the draft.

    Each of the three collections is replaced wholesale when it is sent, and left alone when it
    is not. Replaced rather than diffed for the same reason as everywhere else in this codebase:
    a diff on the client is a second implementation of what the server already does, and the two
    disagree the first time somebody reorders a row.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    job = await _get(session, job_id)
    if not job.is_editable:
        raise ValidationFailed(
            f"This job is {job.status.replace('_', ' ')} and cannot be edited."
        )
    if job.version != payload.expected_version:
        raise Conflict(
            "Somebody else saved this job while you were editing. Reload it and apply your "
            "change again."
        )

    changes = payload.model_dump(exclude_unset=True)
    changes.pop("expected_version", None)
    steps = changes.pop("steps", None)
    rules = changes.pop("assignment_rules", None)
    inputs = changes.pop("inputs", None)
    tools = changes.pop("tools", None)

    for field, value in changes.items():
        if field in _SCALAR_FIELDS:
            setattr(job, field, value)

    if payload.owner_membership_id is not None:
        await _require_member(session, payload.owner_membership_id, "owner")
    if payload.approver_membership_id is not None:
        await _require_member(session, payload.approver_membership_id, "approver")

    if steps is not None:
        await _replace_steps(session, context, job, steps)
    if rules is not None:
        await _replace_rules(session, context, job, rules)
    if inputs is not None:
        await _replace_inputs(session, context, job, inputs)
    if tools is not None:
        await _replace_tools(session, context, job, tools)

    job.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="job.updated",
        resource_type="job",
        resource_id=job.id,
        actor=context,
        #  Which fields, never their values. A job carries a company's method, and an audit trail
        #  is not the place to keep a second copy of it.
        detail={
            "fields": sorted(changes),
            "steps_replaced": steps is not None,
            "rules_replaced": rules is not None,
            "inputs_replaced": inputs is not None,
            "tools_replaced": tools is not None,
        },
    )
    return job


async def archive(
    session: AsyncSession,
    context: SecurityContext,
    job_id: uuid.UUID,
    expected_version: int,
) -> Job:
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    job = await _get(session, job_id)
    if job.version != expected_version:
        raise Conflict("Somebody else changed this job. Reload it and try again.")
    if job.archived_at is not None:
        return job

    job.archived_at = _now()
    job.status = JobStatus.ARCHIVED
    job.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="job.archived",
        resource_type="job",
        resource_id=job.id,
        actor=context,
        detail={"name": job.name},
    )
    return job


# ---------------------------------------------------------------------------- internals


async def _get(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = (
        await session.execute(select(Job).where(Job.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise NotFound("No such job.")
    return job


async def _require_member(
    session: AsyncSession, membership_id: uuid.UUID, role: str
) -> None:
    member = (
        await session.execute(select(Membership).where(Membership.id == membership_id))
    ).scalar_one_or_none()
    if member is None:
        raise ValidationFailed(f"That {role} is not a member of this workspace.")


async def _replace_steps(
    session: AsyncSession,
    context: SecurityContext,
    job: Job,
    steps: list[dict[str, Any]],
) -> None:
    if len(steps) > MAX_STEPS:
        raise ValidationFailed(
            f"A job can describe up to {MAX_STEPS} steps. Split it into two jobs rather than "
            "one nobody can review in a sitting."
        )

    #  Dependencies go first: they reference the steps by id, and the ids are about to change.
    #  Replacing the step list means the old edges no longer describe anything.
    await session.execute(
        delete(JobStepDependency).where(
            JobStepDependency.step_id.in_(
                select(JobStep.id).where(JobStep.job_id == job.id)
            )
        )
    )
    await session.execute(delete(JobStep).where(JobStep.job_id == job.id))
    #  Flushed before the inserts, or a reorder that reuses a position collides with a row that
    #  is about to disappear.
    await session.flush()

    for index, step in enumerate(steps, start=1):
        session.add(
            JobStep(
                tenant_id=context.tenant_id,
                job_id=job.id,
                position=index,
                **{key: value for key, value in step.items() if value not in (None, "")},
            )
        )
    await session.flush()


async def _replace_rules(
    session: AsyncSession,
    context: SecurityContext,
    job: Job,
    rules: list[dict[str, Any]],
) -> None:
    if len(rules) > MAX_RULES:
        raise ValidationFailed(f"A job can have up to {MAX_RULES} assignment rules.")

    await session.execute(
        delete(JobAssignmentRule).where(JobAssignmentRule.job_id == job.id)
    )
    await session.flush()

    for index, rule in enumerate(rules, start=1):
        if rule.get("target_id") is None and not str(rule.get("target_label") or "").strip():
            raise ValidationFailed(
                "Every WHO rule has to point at somebody — pick a person, team, department, "
                "role or position, or describe the group."
            )
        session.add(
            JobAssignmentRule(
                tenant_id=context.tenant_id,
                job_id=job.id,
                position=index,
                who_type=rule["who_type"],
                target_id=rule.get("target_id"),
                target_label=rule.get("target_label"),
                condition_note=rule.get("condition_note"),
                all_must_act=bool(rule.get("all_must_act", False)),
            )
        )
    await session.flush()


async def _replace_inputs(
    session: AsyncSession,
    context: SecurityContext,
    job: Job,
    inputs: list[dict[str, Any]],
) -> None:
    if len(inputs) > MAX_INPUTS:
        raise ValidationFailed(f"A job can define up to {MAX_INPUTS} inputs.")

    names = [str(item.get("name", "")).strip().lower() for item in inputs]
    duplicate = next((name for name in names if names.count(name) > 1), None)
    if duplicate:
        #  Caught here as well as by the unique index, so the message names the input rather
        #  than being a constraint violation the person has to decode.
        raise ValidationFailed(
            f"Two inputs are both called “{duplicate}”. A step could mean either."
        )

    await session.execute(delete(JobInput).where(JobInput.job_id == job.id))
    await session.flush()

    for index, item in enumerate(inputs, start=1):
        if item.get("requirement") == "Conditional" and not str(
            item.get("condition_note") or ""
        ).strip():
            raise ValidationFailed(
                f"“{item.get('name')}” is conditional, so say when it is required."
            )
        if (
            item.get("classification") == "personal_data"
            and item.get("ai_access") == "read_write"
        ):
            raise ValidationFailed(
                f"“{item.get('name')}” holds personal data, so an agent cannot be given write "
                "access to it."
            )
        session.add(
            JobInput(
                tenant_id=context.tenant_id,
                job_id=job.id,
                position=index,
                name=str(item["name"]).strip(),
                input_type=item["input_type"],
                source=item.get("source"),
                requirement=item.get("requirement", "Optional"),
                condition_note=item.get("condition_note"),
                validation_note=item.get("validation_note"),
                classification=item.get("classification", "internal"),
                retention_note=item.get("retention_note"),
                ai_access=item.get("ai_access", "none"),
            )
        )
    await session.flush()


async def _replace_tools(
    session: AsyncSession,
    context: SecurityContext,
    job: Job,
    tools: list[dict[str, Any]],
) -> None:
    """Replace the tool declarations.

    Written after the steps, because a tool may name the step that uses it and the step ids
    change on every save. The position is resolved to the current step here rather than being
    stored as a number, so a reorder cannot silently repoint a permission at different work.
    """
    if len(tools) > MAX_TOOLS:
        raise ValidationFailed(f"A job can declare up to {MAX_TOOLS} tools.")

    await session.execute(delete(JobTool).where(JobTool.job_id == job.id))
    await session.flush()

    steps = list(
        (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.position)
            )
        )
        .scalars()
        .all()
    )
    by_position = {step.position: step.id for step in steps}

    for index, tool in enumerate(tools, start=1):
        permissions = [str(value) for value in (tool.get("permissions") or [])]
        if not permissions:
            name = tool.get("name")
            raise ValidationFailed(
                f"Say what {name} is allowed to do. A tool with no permission is one every "
                "call would be refused."
            )
        session.add(
            JobTool(
                tenant_id=context.tenant_id,
                job_id=job.id,
                position=index,
                name=str(tool["name"]).strip(),
                permissions=permissions,
                step_id=by_position.get(tool.get("step_position") or 0),
                note=tool.get("note"),
            )
        )
    await session.flush()


async def _describe(session: AsyncSession, job: Job) -> JobRead:
    steps = list(
        (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.position)
            )
        )
        .scalars()
        .all()
    )
    rules = list(
        (
            await session.execute(
                select(JobAssignmentRule)
                .where(JobAssignmentRule.job_id == job.id)
                .order_by(JobAssignmentRule.position)
            )
        )
        .scalars()
        .all()
    )
    inputs = list(
        (
            await session.execute(
                select(JobInput).where(JobInput.job_id == job.id).order_by(JobInput.position)
            )
        )
        .scalars()
        .all()
    )
    tools = list(
        (
            await session.execute(
                select(JobTool).where(JobTool.job_id == job.id).order_by(JobTool.position)
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
                    select(JobStepDependency).where(
                        JobStepDependency.step_id.in_([step.id for step in steps])
                    )
                )
            )
            .scalars()
            .all()
        ):
            edges.setdefault(edge.step_id, []).append(edge.depends_on_step_id)

    names: dict[uuid.UUID, str] = {}
    wanted = [
        value
        for value in (job.owner_membership_id, job.approver_membership_id)
        if value is not None
    ]
    if wanted:
        names = {
            member.id: member.display_name
            for member in (
                (await session.execute(select(Membership).where(Membership.id.in_(wanted))))
                .scalars()
                .all()
            )
        }

    objective_name: str | None = None
    if job.objective_id is not None:
        objective_name = (
            await session.execute(
                select(Objective.title).where(Objective.id == job.objective_id)
            )
        ).scalar_one_or_none()

    return JobRead(
        **{
            column: getattr(job, column)
            for column in (
                "id",
                "name",
                "objective_id",
                "objective_step_id",
                "department",
                "external_ref",
                "owner_membership_id",
                "current_person",
                "current_role",
                "trigger",
                "frequency",
                "high_level_work",
                "start_requirement",
                "completion_evidence",
                "normal_completion_time",
                "time_unit",
                "purpose",
                "expected_output",
                "quality_checks",
                "sla_note",
                "retry_policy",
                "failure_action",
                "escalation_to",
                "approver_membership_id",
                "published_version_id",
                "archived_at",
                "version",
                "created_at",
                "updated_at",
            )
        },
        status=job.status,
        visibility=job.visibility,
        objective_name=objective_name,
        owner_name=names.get(job.owner_membership_id) if job.owner_membership_id else None,
        approver_name=(
            names.get(job.approver_membership_id) if job.approver_membership_id else None
        ),
        steps=[
            JobStepRead.model_validate(
                {
                    **{
                        column: getattr(step, column)
                        for column in JobStepRead.model_fields
                        if column not in ("depends_on",)
                    },
                    "depends_on": edges.get(step.id, []),
                }
            )
            for step in steps
        ],
        assignment_rules=[
            AssignmentRuleRead.model_validate(rule, from_attributes=True) for rule in rules
        ],
        inputs=[JobInputRead.model_validate(item, from_attributes=True) for item in inputs],
        tools=[
            JobToolRead(
                id=tool.id,
                position=tool.position,
                name=tool.name,
                permissions=tool.permissions,
                integration_id=tool.integration_id,
                #  Resolved back to a position for the client, which edits by position.
                step_position=next(
                    (step.position for step in steps if step.id == tool.step_id), None
                ),
                note=tool.note,
            )
            for tool in tools
        ],
        is_editable=job.is_editable,
    )
