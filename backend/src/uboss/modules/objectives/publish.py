"""The publish summary, the approval route, and the immutable version it produces.

PLAN §6's journey ends:

    Publish summary → Authorized approval → Immutable Published version/card

and §7 says what the summary must contain: *"Publish shows owners, steps, schedules, permissions,
cost, warnings and approval route. Approval creates immutable ObjectiveVersion."*

Three rules run through this module:

**The summary is computed, never stored.** It is derived from the objective and its plan every
time it is asked for, so it cannot describe a version of the objective that no longer exists.
A summary somebody read yesterday is worth nothing; a summary that *claims* to be current and is
not is worth less than nothing.

**A warning never blocks, and is never hidden.** The person approving is entitled to see what is
odd about what they are approving — an agent step on sensitive work, a plan with no approval in
it, a step nobody is responsible for. Blocking on these would be the product overruling a decision
that is the organisation's to make; hiding them would be the product deciding they do not matter.

**Publishing is two people.** PLAN §14 separates the author from the approver, and
`guard.refuse_self_approval` holds it. Submitting and approving are separate calls with separate
permissions, so a single person cannot do both even by calling the API directly.
"""

from __future__ import annotations

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
from uboss.modules.objectives.models import (
    Objective,
    ObjectiveCurrentStep,
    ObjectiveStatus,
    ObjectiveVersion,
)
from uboss.modules.objectives.proposal_models import (
    ObjectiveStep,
    StepDependency,
    StepKind,
    StepSource,
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PublishWarning:
    """Something the approver should see before deciding. Never a blocker."""

    code: str
    message: str


@dataclass(slots=True)
class Summary:
    """What §7 requires on the publish screen."""

    objective_id: uuid.UUID
    title: str
    status: str
    owner_name: str | None
    approver_name: str | None
    submitted_by_name: str | None
    department: str | None
    expected_result: str | None

    #: Counts by block kind, which is the shape of the question "how much of this is automatic".
    step_count: int
    human_steps: int
    agent_steps: int
    hybrid_steps: int
    approval_steps: int
    output_steps: int
    #: How much of the plan a person changed after the model proposed it.
    ai_proposed: int
    ai_edited: int
    human_added: int

    #: What the analysis cost, from the run that produced the plan. Real numbers or nothing —
    #: §7 asks for cost on this screen, and an estimate would be a number somebody quoted.
    analysis_model: str | None
    analysis_tokens: int

    warnings: list[PublishWarning] = field(default_factory=list)
    #: What has to happen next, and who does it. Named rather than described, so nobody has to
    #: work out whether it is their turn.
    next_action: str = ""
    can_submit: bool = False
    can_approve: bool = False
    version: int = 1


async def summary(
    session: AsyncSession, context: SecurityContext, objective_id: uuid.UUID
) -> Summary:
    """Everything the approver needs, computed now."""
    await guard.authorise(session, context, Action.VIEW)

    objective = await _get(session, objective_id)
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
    names = await _names(
        session,
        objective.owner_membership_id,
        objective.approver_membership_id,
        objective.submitted_by_membership_id,
    )

    by_kind = {kind: 0 for kind in StepKind}
    for step in steps:
        by_kind[StepKind(step.kind)] += 1

    ai_steps = [step for step in steps if step.source == StepSource.AI]
    warnings = _warnings(objective, steps)

    is_owner = context.membership_id == objective.owner_membership_id
    is_approver = context.membership_id == objective.approver_membership_id
    submitted_by_me = context.membership_id == objective.submitted_by_membership_id

    can_submit = (
        objective.status
        in (ObjectiveStatus.DRAFT, ObjectiveStatus.NEEDS_REVIEW)
        and bool(steps)
        and objective.approver_membership_id is not None
    )
    can_approve = (
        objective.status == ObjectiveStatus.READY_TO_PUBLISH
        and is_approver
        and not submitted_by_me
    )

    analysis_model, analysis_tokens = await _analysis_cost(session, objective_id)

    return Summary(
        objective_id=objective.id,
        title=objective.title,
        status=objective.status,
        owner_name=names.get(objective.owner_membership_id),
        approver_name=names.get(objective.approver_membership_id),
        submitted_by_name=names.get(objective.submitted_by_membership_id),
        department=objective.department,
        expected_result=objective.expected_result,
        step_count=len(steps),
        human_steps=by_kind[StepKind.HUMAN],
        agent_steps=by_kind[StepKind.AI_AGENT],
        hybrid_steps=by_kind[StepKind.HYBRID],
        approval_steps=by_kind[StepKind.APPROVAL],
        output_steps=by_kind[StepKind.OUTPUT],
        ai_proposed=len(ai_steps),
        ai_edited=sum(1 for step in ai_steps if step.edited),
        human_added=len(steps) - len(ai_steps),
        analysis_model=analysis_model,
        analysis_tokens=analysis_tokens,
        warnings=warnings,
        next_action=_next_action(objective, steps, is_owner, is_approver, submitted_by_me),
        can_submit=can_submit,
        can_approve=can_approve,
        version=objective.version,
    )


def _warnings(objective: Objective, steps: list[ObjectiveStep]) -> list[PublishWarning]:
    """What is odd about this plan.

    Shown, never enforced. Each of these is a legitimate choice an organisation might make on
    purpose — and each is also the kind of thing somebody approves at speed and regrets. The
    product's job is to make sure they saw it.
    """
    found: list[PublishWarning] = []

    if not steps:
        found.append(
            PublishWarning("no_steps", "There is no plan. Nothing would happen when this runs.")
        )

    if objective.owner_membership_id == objective.approver_membership_id:
        found.append(
            PublishWarning(
                "same_person",
                "The owner and the approver are the same person, so nobody else can approve it.",
            )
        )

    if not any(step.kind == StepKind.APPROVAL for step in steps):
        found.append(
            PublishWarning(
                "no_approval_step",
                "No step in the plan is an approval. Everything runs without anybody signing off.",
            )
        )

    unattended = [step for step in steps if step.kind == StepKind.AI_AGENT]
    if unattended and objective.handles_sensitive_data:
        found.append(
            PublishWarning(
                "agent_on_sensitive",
                f"{len(unattended)} steps run unattended on work marked as handling sensitive "
                "data.",
            )
        )

    nameless = [step for step in steps if not (step.responsible_role or "").strip()]
    if nameless:
        found.append(
            PublishWarning(
                "no_responsible_role",
                f"{len(nameless)} steps have nobody named as responsible.",
            )
        )

    if not (objective.success_measures or "").strip():
        found.append(
            PublishWarning(
                "no_measures",
                "No success measure is recorded, so there is no way to tell whether this worked.",
            )
        )

    return found


def _next_action(
    objective: Objective,
    steps: list[ObjectiveStep],
    is_owner: bool,
    is_approver: bool,
    submitted_by_me: bool,
) -> str:
    """Whose turn it is, in a sentence.

    Written out rather than left for the interface to infer, because the inference is where an
    approval queue goes wrong: two screens each concluding it is the other person's turn.
    """
    if objective.status in (ObjectiveStatus.PUBLISHED, ObjectiveStatus.ACTIVE):
        return "This objective is published. Editing it means publishing a new version."
    if objective.status == ObjectiveStatus.ARCHIVED:
        return "This objective is archived."
    if objective.status == ObjectiveStatus.ANALYZING:
        return "The analysis is still running."
    if not steps:
        return "Add a plan — analyse the current process, or add the steps yourself."
    if objective.approver_membership_id is None:
        return "Name an approver in Governance before this can be submitted."
    if objective.status == ObjectiveStatus.READY_TO_PUBLISH:
        if is_approver and submitted_by_me:
            return (
                "You submitted this, so somebody else has to approve it. Ask the owner to "
                "name a different approver."
            )
        if is_approver:
            return "Waiting for you to approve it."
        return "Waiting for the approver."
    return "Ready to send for approval."


async def submit(
    session: AsyncSession,
    context: SecurityContext,
    objective_id: uuid.UUID,
    expected_version: int,
) -> Objective:
    """Send it for approval.

    `edit_draft`, not `publish`: submitting is the last act of writing, and requiring the publish
    permission to submit would mean only people who can approve could ask for approval.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    objective = await _get(session, objective_id)
    if objective.version != expected_version:
        raise Conflict("Somebody else changed this objective. Reload it and try again.")
    if objective.status not in (ObjectiveStatus.DRAFT, ObjectiveStatus.NEEDS_REVIEW):
        raise ValidationFailed(
            f"This objective is {objective.status.replace('_', ' ')} and cannot be submitted."
        )
    if objective.approver_membership_id is None:
        raise ValidationFailed("Name an approver in Governance before submitting this.")

    steps = (
        await session.execute(
            select(ObjectiveStep.id).where(ObjectiveStep.objective_id == objective_id).limit(1)
        )
    ).first()
    if steps is None:
        raise ValidationFailed(
            "There is no plan to publish. Analyse the current process, or add the steps "
            "yourself, before submitting."
        )

    objective.status = ObjectiveStatus.READY_TO_PUBLISH
    objective.submitted_by_membership_id = context.membership_id
    objective.submitted_at = _now()
    objective.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="objective.submitted",
        resource_type="objective",
        resource_id=objective.id,
        actor=context,
        detail={"approver": str(objective.approver_membership_id)},
    )
    return objective


async def withdraw(
    session: AsyncSession,
    context: SecurityContext,
    objective_id: uuid.UUID,
    expected_version: int,
) -> Objective:
    """Take it back out of the approval queue.

    Ordinary and necessary: somebody spots a mistake after submitting. The submitter is cleared
    so the next submission is judged on its own — otherwise a withdrawn-and-resubmitted objective
    would still be barred from the original submitter's approval, which is not what the rule is
    for.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    objective = await _get(session, objective_id)
    if objective.version != expected_version:
        raise Conflict("Somebody else changed this objective. Reload it and try again.")
    if objective.status != ObjectiveStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This objective is not waiting for approval.")

    objective.status = ObjectiveStatus.NEEDS_REVIEW
    objective.submitted_by_membership_id = None
    objective.submitted_at = None
    objective.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="objective.withdrawn",
        resource_type="objective",
        resource_id=objective.id,
        actor=context,
    )
    return objective


async def publish(
    session: AsyncSession,
    context: SecurityContext,
    objective_id: uuid.UUID,
    expected_version: int,
) -> ObjectiveVersion:
    """Approve it, and freeze what was approved.

    Four things have to be true, and each is checked here rather than by the screen:

    1. The caller holds `publish`, which is high-risk and so needs a recent password proof.
    2. They are the named approver. Holding the permission is not the same as being asked.
    3. They did not submit it — `guard.refuse_self_approval`, PLAN §14's separation of duty.
    4. The version they read is the version they are approving.

    The snapshot is taken inside the same transaction as the status change, so what the version
    records and what was approved cannot differ by an edit that landed in between.
    """
    await guard.authorise(session, context, Action.PUBLISH)

    objective = await _get(session, objective_id)
    if objective.version != expected_version:
        raise Conflict(
            "This objective changed since you opened it. Reload and read it again before "
            "approving."
        )
    if objective.status != ObjectiveStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This objective has not been submitted for approval.")
    if objective.approver_membership_id != context.membership_id:
        #  Not a permission problem — they may well hold `publish`. They are not the person this
        #  objective names, and saying so is more useful than a generic refusal.
        raise ValidationFailed("You are not the named approver for this objective.")

    await guard.refuse_self_approval(
        session,
        context,
        submitted_by_membership_id=objective.submitted_by_membership_id or uuid.UUID(int=0),
        resource=guard.Resource(type="objective", id=objective.id),
    )

    snapshot = await _snapshot(session, objective)

    version = ObjectiveVersion(
        tenant_id=context.tenant_id,
        objective_id=objective.id,
        snapshot=snapshot,
        title=objective.title,
        published_by_membership_id=objective.submitted_by_membership_id,
        approved_by_membership_id=context.membership_id,
    )
    session.add(version)
    await session.flush()

    objective.status = ObjectiveStatus.PUBLISHED
    objective.published_version_id = version.id
    objective.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="objective.published",
        resource_type="objective",
        resource_id=objective.id,
        actor=context,
        detail={
            "version_id": str(version.id),
            "version_no": version.version_no,
            "submitted_by": str(objective.submitted_by_membership_id),
            "steps": len(snapshot.get("plan", [])),
        },
    )
    return version


# ---------------------------------------------------------------------------- internals


async def _snapshot(session: AsyncSession, objective: Objective) -> dict[str, Any]:
    """Everything that was approved, frozen.

    The current process and the plan both go in. A version that recorded only the plan could not
    answer "what were we doing before", which is the question every review of a published
    objective starts with.
    """
    current = list(
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
    plan = list(
        (
            await session.execute(
                select(ObjectiveStep)
                .where(ObjectiveStep.objective_id == objective.id)
                .order_by(ObjectiveStep.position)
            )
        )
        .scalars()
        .all()
    )
    edges: dict[str, list[str]] = {}
    if plan:
        for edge in (
            (
                await session.execute(
                    select(StepDependency).where(
                        StepDependency.step_id.in_([step.id for step in plan])
                    )
                )
            )
            .scalars()
            .all()
        ):
            edges.setdefault(str(edge.step_id), []).append(str(edge.depends_on_step_id))

    return {
        "objective": {
            column: _plain(getattr(objective, column))
            for column in (
                "title",
                "department",
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
                "visibility",
                "handles_sensitive_data",
                "sensitive_data_note",
                "ai_assistance",
                "human_checkpoints",
            )
        },
        "owner_membership_id": _plain(objective.owner_membership_id),
        "approver_membership_id": _plain(objective.approver_membership_id),
        "current_process": [
            {
                "position": step.position,
                "who_person": step.who_person,
                "who_role": step.who_role,
                "when_trigger": step.when_trigger,
                "when_frequency": step.when_frequency,
                "what_exact_work": step.what_exact_work,
                "input_used": step.input_used,
                "input_received_from": step.input_received_from,
                "where_done": step.where_done,
                "output_produced": step.output_produced,
                "output_sent_to": step.output_sent_to,
                "time_taken": step.time_taken,
                "current_problem": step.current_problem,
                "approval": step.approval,
            }
            for step in current
        ],
        "plan": [
            {
                "id": str(step.id),
                "position": step.position,
                "kind": step.kind,
                "title": step.title,
                "detail": step.detail,
                "responsible_role": step.responsible_role,
                "replaces_current_step": step.replaces_current_step,
                "rationale": step.rationale,
                "source": step.source,
                "edited": step.edited,
                "depends_on": edges.get(str(step.id), []),
            }
            for step in plan
        ],
        "frozen_at": _now().isoformat(),
    }


def _plain(value: Any) -> Any:
    """JSON-safe. Dates and ids become strings; everything else is already plain."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def _analysis_cost(
    session: AsyncSession, objective_id: uuid.UUID
) -> tuple[str | None, int]:
    """What the last successful analysis actually cost.

    Real numbers or nothing. §7 asks for cost on the publish screen, and an estimate printed there
    is a number somebody will quote.
    """
    from uboss.modules.objectives.proposal_models import ObjectiveProposal, ProposalStatus

    proposal = (
        await session.execute(
            select(ObjectiveProposal)
            .where(
                ObjectiveProposal.objective_id == objective_id,
                ObjectiveProposal.status == ProposalStatus.SUCCEEDED,
            )
            .order_by(ObjectiveProposal.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if proposal is None:
        return None, 0
    return proposal.model, proposal.input_tokens + proposal.output_tokens


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


async def _get(session: AsyncSession, objective_id: uuid.UUID) -> Objective:
    objective = (
        await session.execute(select(Objective).where(Objective.id == objective_id))
    ).scalar_one_or_none()
    if objective is None:
        raise NotFound("No such objective.")
    return objective
