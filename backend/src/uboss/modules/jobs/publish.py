"""Publishing a Job — the summary, the approval route, and the immutable version.

The same three rules as the Objective's publish, and deliberately the same code shape: the summary
is computed on every read, a warning never blocks and is never hidden, and publishing takes two
people. Somebody who has published an Objective should find this behaves identically.

What differs is what there is to warn about. A Job is a *method*, so the questions are different:
does an unattended step say what to do when its input is missing, does a step use an input nobody
defined, and is a schedule about to start firing something nobody has approved.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.jobs.models import (
    AiAccess,
    Job,
    JobAssignmentRule,
    JobInput,
    JobSchedule,
    JobStatus,
    JobStep,
    JobStepDependency,
    JobVersion,
    StepMode,
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PublishWarning:
    code: str
    message: str


@dataclass(slots=True)
class Summary:
    job_id: uuid.UUID
    name: str
    status: str
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
    #: How many inputs a model may read. The number people most want on this screen, because it
    #: is the one that answers "what does the AI actually see".
    ai_readable_inputs: int

    #: What the schedule would do, if there is one. §8 asks for schedules on the publish screen.
    schedule_summary: str | None
    schedule_auto_run: bool

    warnings: list[PublishWarning] = field(default_factory=list)
    next_action: str = ""
    can_submit: bool = False
    can_approve: bool = False
    version: int = 1


async def summary(
    session: AsyncSession, context: SecurityContext, job_id: uuid.UUID
) -> Summary:
    await guard.authorise(session, context, Action.VIEW)

    job = await _get(session, job_id)
    steps = await _steps(session, job_id)
    rules = list(
        (
            await session.execute(
                select(JobAssignmentRule).where(JobAssignmentRule.job_id == job_id)
            )
        )
        .scalars()
        .all()
    )
    inputs = list(
        (await session.execute(select(JobInput).where(JobInput.job_id == job_id)))
        .scalars()
        .all()
    )
    schedule = (
        await session.execute(select(JobSchedule).where(JobSchedule.job_id == job_id))
    ).scalar_one_or_none()

    names = await _names(
        session,
        job.owner_membership_id,
        job.approver_membership_id,
        job.submitted_by_membership_id,
    )
    objective_name = None
    if job.objective_id is not None:
        from uboss.modules.objectives.models import Objective

        objective_name = (
            await session.execute(
                select(Objective.title).where(Objective.id == job.objective_id)
            )
        ).scalar_one_or_none()

    is_approver = context.membership_id == job.approver_membership_id
    submitted_by_me = context.membership_id == job.submitted_by_membership_id

    return Summary(
        job_id=job.id,
        name=job.name,
        status=job.status,
        owner_name=names.get(job.owner_membership_id),
        approver_name=names.get(job.approver_membership_id),
        submitted_by_name=names.get(job.submitted_by_membership_id),
        department=job.department,
        objective_name=objective_name,
        step_count=len(steps),
        human_steps=sum(1 for step in steps if step.mode == StepMode.HUMAN),
        agent_steps=sum(1 for step in steps if step.mode == StepMode.AI_AGENT),
        hybrid_steps=sum(1 for step in steps if step.mode == StepMode.HYBRID),
        rule_count=len(rules),
        input_count=len(inputs),
        ai_readable_inputs=sum(
            1 for item in inputs if item.ai_access in (AiAccess.READ, AiAccess.READ_WRITE)
        ),
        schedule_summary=_schedule_sentence(schedule),
        schedule_auto_run=bool(schedule and schedule.auto_run),
        warnings=_warnings(job, steps, rules, inputs, schedule),
        next_action=_next_action(job, steps, is_approver, submitted_by_me),
        can_submit=(
            job.status in (JobStatus.DRAFT, JobStatus.NEEDS_REVIEW)
            and bool(steps)
            and job.approver_membership_id is not None
        ),
        can_approve=(
            job.status == JobStatus.READY_TO_PUBLISH and is_approver and not submitted_by_me
        ),
        version=job.version,
    )


def _schedule_sentence(schedule: JobSchedule | None) -> str | None:
    """The schedule in one line a person can check without reading its settings."""
    if schedule is None:
        return None
    when = {
        "hourly": f"every {schedule.interval} hour(s)",
        "daily": "every day" if schedule.interval == 1 else f"every {schedule.interval} days",
        "weekly": "every week" if schedule.interval == 1 else f"every {schedule.interval} weeks",
        "monthly": f"on day {schedule.monthday} of the month",
    }[schedule.frequency]
    return (
        f"{when} at {schedule.at_time.strftime('%H:%M')} {schedule.timezone}"
        f"{'' if schedule.auto_run else ' — auto-run is off'}"
    )


def _warnings(
    job: Job,
    steps: list[JobStep],
    rules: list[JobAssignmentRule],
    inputs: list[JobInput],
    schedule: JobSchedule | None,
) -> list[PublishWarning]:
    """What is odd about this method.

    Every one of these is a legitimate choice somebody might make on purpose, and every one is
    also a way to publish something that fails at three in the morning. Shown, never enforced.
    """
    found: list[PublishWarning] = []

    if not steps:
        found.append(
            PublishWarning("no_steps", "There are no steps. Nothing would happen when this runs.")
        )

    if not rules:
        found.append(
            PublishWarning(
                "no_who_rules",
                "No WHO rule says who does this. It would run with nobody assigned.",
            )
        )

    if job.owner_membership_id == job.approver_membership_id:
        found.append(
            PublishWarning(
                "same_person",
                "The owner and the approver are the same person, so nobody else can approve it.",
            )
        )

    if not (job.completion_evidence or "").strip():
        found.append(
            PublishWarning(
                "no_completion_evidence",
                "Nothing says how anybody knows this finished.",
            )
        )

    #  An unattended step that does not say what to do when its input is missing is the failure
    #  mode of every automation: it does something wrong rather than stopping.
    silent = [
        step
        for step in steps
        if step.mode in (StepMode.AI_AGENT, StepMode.HYBRID)
        and not (step.if_missing_or_wrong or "").strip()
    ]
    if silent:
        found.append(
            PublishWarning(
                "agent_step_without_fallback",
                f"{len(silent)} automated steps do not say what to do if the input is missing "
                "or wrong.",
            )
        )

    #  A step that names something in quotes which is not a defined input. Deliberately narrow —
    #  it only looks at quoted names, because a broader match would flag ordinary prose.
    defined = {item.name.strip().lower() for item in inputs}
    #  Keyed on the lowercased name for the comparison, but the message names it back to the
    #  person exactly as they typed it. Echoing a lowercased version of their own words reads
    #  like the product misread them.
    referenced: dict[str, str] = {}
    for step in steps:
        for text_field in (step.input_exact, step.what_exact_work):
            if text_field:
                for match in re.findall(r"[“\"']([^”\"']{2,60})[”\"']", text_field):
                    referenced.setdefault(match.strip().lower(), match.strip())
    undefined = [referenced[key] for key in sorted(referenced) if key not in defined]
    if undefined:
        found.append(
            PublishWarning(
                "undefined_input_referenced",
                f"Steps mention {', '.join(f'“{name}”' for name in undefined[:3])} but no input "
                "is defined with that name.",
            )
        )

    exposed = [item for item in inputs if item.ai_access != AiAccess.NONE]
    personal = [item for item in exposed if item.classification == "personal_data"]
    if personal:
        found.append(
            PublishWarning(
                "ai_reads_personal_data",
                f"{len(personal)} inputs holding personal data are readable by an agent.",
            )
        )

    if schedule is not None and schedule.auto_run and job.status != JobStatus.PUBLISHED:
        found.append(
            PublishWarning(
                "schedule_waiting",
                "Auto-run is on. This will start running on its own as soon as it is published.",
            )
        )
    if schedule is not None and schedule.auto_run and schedule.pinned_version_id is None:
        found.append(
            PublishWarning(
                "schedule_not_pinned",
                "The schedule runs whatever version is published at the time, so a later change "
                "takes effect without anybody scheduling it.",
            )
        )

    return found


def _next_action(
    job: Job, steps: list[JobStep], is_approver: bool, submitted_by_me: bool
) -> str:
    if job.status in (JobStatus.PUBLISHED, JobStatus.ACTIVE):
        return "This job is published. Editing it means publishing a new version."
    if job.status == JobStatus.ARCHIVED:
        return "This job is archived."
    if not steps:
        return "Describe at least one step of the method before this can be published."
    if job.approver_membership_id is None:
        return "Name an approver before this can be submitted."
    if job.status == JobStatus.READY_TO_PUBLISH:
        if is_approver and submitted_by_me:
            return (
                "You submitted this, so somebody else has to approve it. Ask the owner to name "
                "a different approver."
            )
        if is_approver:
            return "Waiting for you to approve it."
        return "Waiting for the approver."
    return "Ready to send for approval."


async def submit(
    session: AsyncSession,
    context: SecurityContext,
    job_id: uuid.UUID,
    expected_version: int,
) -> Job:
    """`edit_draft` — submitting is the last act of writing, not the first act of approving."""
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    job = await _get(session, job_id)
    if job.version != expected_version:
        raise Conflict("Somebody else changed this job. Reload it and try again.")
    if job.status not in (JobStatus.DRAFT, JobStatus.NEEDS_REVIEW):
        raise ValidationFailed(
            f"This job is {job.status.replace('_', ' ')} and cannot be submitted."
        )
    if job.approver_membership_id is None:
        raise ValidationFailed("Name an approver before submitting this.")
    if not await _steps(session, job_id):
        raise ValidationFailed(
            "There is no method to publish. Describe at least one step before submitting."
        )

    job.status = JobStatus.READY_TO_PUBLISH
    job.submitted_by_membership_id = context.membership_id
    job.submitted_at = _now()
    job.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="job.submitted",
        resource_type="job",
        resource_id=job.id,
        actor=context,
        detail={"approver": str(job.approver_membership_id)},
    )
    return job


async def withdraw(
    session: AsyncSession,
    context: SecurityContext,
    job_id: uuid.UUID,
    expected_version: int,
) -> Job:
    """Take it back. The submitter is cleared so the next submission is judged on its own."""
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    job = await _get(session, job_id)
    if job.version != expected_version:
        raise Conflict("Somebody else changed this job. Reload it and try again.")
    if job.status != JobStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This job is not waiting for approval.")

    job.status = JobStatus.NEEDS_REVIEW
    job.submitted_by_membership_id = None
    job.submitted_at = None
    job.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="job.withdrawn",
        resource_type="job",
        resource_id=job.id,
        actor=context,
    )
    return job


async def publish(
    session: AsyncSession,
    context: SecurityContext,
    job_id: uuid.UUID,
    expected_version: int,
) -> JobVersion:
    """Approve it, and freeze the method that was approved.

    The same four checks as an Objective: `publish` held and recently proved, the caller is the
    named approver, they did not submit it, and the version they read is the one they approve.
    """
    await guard.authorise(session, context, Action.PUBLISH)

    job = await _get(session, job_id)
    if job.version != expected_version:
        raise Conflict(
            "This job changed since you opened it. Reload and read it again before approving."
        )
    if job.status != JobStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This job has not been submitted for approval.")
    if job.approver_membership_id != context.membership_id:
        raise ValidationFailed("You are not the named approver for this job.")

    await guard.refuse_self_approval(
        session,
        context,
        submitted_by_membership_id=job.submitted_by_membership_id or uuid.UUID(int=0),
        resource=guard.Resource(type="job", id=job.id),
    )

    snapshot = await _snapshot(session, job)
    version = JobVersion(
        tenant_id=context.tenant_id,
        job_id=job.id,
        snapshot=snapshot,
        name=job.name,
        published_by_membership_id=job.submitted_by_membership_id,
        approved_by_membership_id=context.membership_id,
    )
    session.add(version)
    await session.flush()

    job.status = JobStatus.PUBLISHED
    job.published_version_id = version.id
    job.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="job.published",
        resource_type="job",
        resource_id=job.id,
        actor=context,
        detail={
            "version_id": str(version.id),
            "version_no": version.version_no,
            "submitted_by": str(job.submitted_by_membership_id),
            "steps": len(snapshot.get("steps", [])),
        },
    )
    return version


# ---------------------------------------------------------------------------- internals


async def _snapshot(session: AsyncSession, job: Job) -> dict[str, Any]:
    """The whole method, frozen: header, steps, WHO rules, inputs and the schedule.

    The schedule goes in because a published version that did not record when it ran could not
    answer "why did this fire at 3 a.m. in March", which is the question a clock change produces.
    """
    steps = await _steps(session, job.id)
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
    schedule = (
        await session.execute(select(JobSchedule).where(JobSchedule.job_id == job.id))
    ).scalar_one_or_none()

    edges: dict[str, list[str]] = {}
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
            edges.setdefault(str(edge.step_id), []).append(str(edge.depends_on_step_id))

    return {
        "job": {
            column: _plain(getattr(job, column))
            for column in (
                "name",
                "department",
                "external_ref",
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
            )
        },
        "objective_id": _plain(job.objective_id),
        "objective_step_id": _plain(job.objective_step_id),
        "owner_membership_id": _plain(job.owner_membership_id),
        "approver_membership_id": _plain(job.approver_membership_id),
        "steps": [
            {
                "id": str(step.id),
                "position": step.position,
                **{
                    column: getattr(step, column)
                    for column in (
                        "who_person",
                        "who_role",
                        "when_trigger",
                        "when_frequency",
                        "what_exact_work",
                        "input_exact",
                        "input_found_where",
                        "how_exact_method",
                        "where_performed",
                        "rule_formula_check",
                        "output",
                        "output_destination",
                        "approval",
                        "if_missing_or_wrong",
                        "time_taken",
                        "mode",
                    )
                },
                "depends_on": edges.get(str(step.id), []),
            }
            for step in steps
        ],
        "assignment_rules": [
            {
                "position": rule.position,
                "who_type": rule.who_type,
                "target_id": _plain(rule.target_id),
                "target_label": rule.target_label,
                "condition_note": rule.condition_note,
                "all_must_act": rule.all_must_act,
            }
            for rule in rules
        ],
        "inputs": [
            {
                "position": item.position,
                "name": item.name,
                "input_type": item.input_type,
                "source": item.source,
                "requirement": item.requirement,
                "condition_note": item.condition_note,
                "validation_note": item.validation_note,
                "classification": item.classification,
                "retention_note": item.retention_note,
                "ai_access": item.ai_access,
            }
            for item in inputs
        ],
        "schedule": (
            {
                "auto_run": schedule.auto_run,
                "timezone": schedule.timezone,
                "frequency": schedule.frequency,
                "interval": schedule.interval,
                "at_time": schedule.at_time.isoformat(),
                "weekdays": schedule.weekdays,
                "monthday": schedule.monthday,
                "dst_policy": schedule.dst_policy,
                "ambiguous_policy": schedule.ambiguous_policy,
                "skip_dates": schedule.skip_dates,
                "weekdays_only": schedule.weekdays_only,
                "overlap_policy": schedule.overlap_policy,
                "missed_run_policy": schedule.missed_run_policy,
                "max_concurrent": schedule.max_concurrent,
                "requires_approval_per_run": schedule.requires_approval_per_run,
            }
            if schedule is not None
            else None
        ),
        "frozen_at": _now().isoformat(),
    }


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def _steps(session: AsyncSession, job_id: uuid.UUID) -> list[JobStep]:
    return list(
        (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.position)
            )
        )
        .scalars()
        .all()
    )


async def _names(
    session: AsyncSession, *ids: uuid.UUID | None
) -> dict[uuid.UUID | None, str]:
    wanted = [value for value in ids if value is not None]
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


async def _get(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise NotFound("No such job.")
    return job
