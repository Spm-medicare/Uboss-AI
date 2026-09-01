"""Publishing a Supervisor — §10 group 10, and the gate `PLAN.md` names for Gate 6.

> Exit: failure simulation and forbidden-action tests pass.

The two halves live in different places, and it is worth saying which is which. **Failure
simulation** is per Supervisor and is enforced here: at least one scenario, and every one passing.
**Forbidden-action** is repository-wide — §10's four prohibitions — and its home is
`tests/integration/test_supervisor_forbidden_actions.py`, which is where a claim about what the
system cannot do belongs.

**One gate, and it is the one the plan names.** §10 does not repeat §9's *"tests and permission
review are publish gates"* sentence, so there is no permission-review gate here. Everything else
worth saying is a warning: shown, never hidden, never in the way. A second gate invented at this
point would be a rule nobody approved.

**Nobody approves their own work.** `docs/product/SKILL_REGISTRY.md` states the general rule —
*"No Skill or Agent can approve/promote itself."* The same four checks as the Objective, the Job
and the Agent: `publish` held and recently proved, the caller is the named approver, they did not
submit it, and the version they read is the one they approve.

**Publishing is also a handler action.** It goes through `guard.authorise_handler`, so the
approver needs `publish` in the workspace *and* a handler role that confers it — which is Owner
alone. A workspace administrator who is not a handler on this Supervisor cannot publish it.
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
from uboss.modules.identity import guard as workspace_guard
from uboss.modules.identity.models import Membership
from uboss.modules.supervisors import guard
from uboss.modules.supervisors.models import (
    SimulationStatus,
    Supervisor,
    SupervisorDependency,
    SupervisorEscalation,
    SupervisorHandler,
    SupervisorKind,
    SupervisorNotification,
    SupervisorQualityGate,
    SupervisorSchedule,
    SupervisorSimulation,
    SupervisorStatus,
    SupervisorSupervised,
    SupervisorVersion,
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PublishWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: str
    name: str
    passed: bool
    reason: str


@dataclass(slots=True)
class Summary:
    """What publishing this would mean, and what is standing in the way."""

    supervisor_id: uuid.UUID
    name: str
    kind: str
    status: str
    owner_name: str | None
    approver_name: str | None
    submitted_by_name: str | None

    #: The two scopes, counted separately because they are two separate questions.
    supervised_count: int
    handler_count: int
    dependency_count: int
    quality_gate_count: int
    escalation_count: int
    notification_count: int
    has_schedule: bool
    schedule_auto_run: bool

    simulations_passed: int
    simulations_total: int

    gates: list[GateResult] = field(default_factory=list)
    warnings: list[PublishWarning] = field(default_factory=list)
    next_action: str = ""
    can_submit: bool = False
    can_approve: bool = False
    version: int = 1


async def summary(
    session: AsyncSession, context: SecurityContext, supervisor_id: uuid.UUID
) -> Summary:
    supervisor = await _get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.VIEW)

    supervised = await _rows(session, SupervisorSupervised, supervisor_id)
    handlers = await _rows(session, SupervisorHandler, supervisor_id)
    dependencies = await _rows(session, SupervisorDependency, supervisor_id)
    quality = await _rows(session, SupervisorQualityGate, supervisor_id)
    escalations = await _rows(session, SupervisorEscalation, supervisor_id)
    notifications = await _rows(session, SupervisorNotification, supervisor_id)
    simulations = await _rows(session, SupervisorSimulation, supervisor_id)
    schedule = (
        await session.execute(
            select(SupervisorSchedule).where(
                SupervisorSchedule.supervisor_id == supervisor_id
            )
        )
    ).scalar_one_or_none()

    names = await _names(
        session,
        supervisor.owner_membership_id,
        supervisor.approver_membership_id,
        supervisor.submitted_by_membership_id,
    )
    gate = _simulation_gate(simulations)
    warnings = _warnings(supervisor, supervised, handlers, quality, escalations, schedule)

    can_approve = (
        supervisor.status == SupervisorStatus.READY_TO_PUBLISH
        and supervisor.approver_membership_id == context.membership_id
        and supervisor.submitted_by_membership_id != context.membership_id
        and gate.passed
    )

    return Summary(
        supervisor_id=supervisor.id,
        name=supervisor.name,
        kind=supervisor.kind,
        status=supervisor.status,
        owner_name=names.get(supervisor.owner_membership_id),
        approver_name=names.get(supervisor.approver_membership_id),
        submitted_by_name=names.get(supervisor.submitted_by_membership_id),
        supervised_count=len(supervised),
        handler_count=len(handlers),
        dependency_count=len(dependencies),
        quality_gate_count=len(quality),
        escalation_count=len(escalations),
        notification_count=len(notifications),
        has_schedule=schedule is not None,
        schedule_auto_run=bool(schedule and schedule.auto_run),
        simulations_passed=sum(
            1 for row in simulations if row.status == SimulationStatus.PASS
        ),
        simulations_total=len(simulations),
        gates=[gate],
        warnings=warnings,
        next_action=_next_action(supervisor, gate, context),
        #  Not `is_editable` alone. `submit()` also requires an approver, something supervised
        #  and a passing simulation gate, so a button driven by editability alone was enabled for
        #  a call that could only be refused — and said nothing about why.
        can_submit=(
            supervisor.is_editable
            and supervisor.approver_membership_id is not None
            and gate.passed
        ),
        can_approve=can_approve,
        version=supervisor.version,
    )


def _simulation_gate(simulations: list[SupervisorSimulation]) -> GateResult:
    """The gate `PLAN.md` names: *"failure simulation … tests pass."*

    At least one, because a Supervisor whose failure behaviour nobody wrote down has not been
    tested — and every one passing, because a scenario recorded as failing is a known problem
    somebody decided to publish anyway.
    """
    if not simulations:
        return GateResult(
            gate="failure_simulation",
            name="Failure simulation",
            passed=False,
            reason=(
                "No failure scenario has been written. A supervisor whose behaviour when things "
                "go wrong nobody has described has not been tested."
            ),
        )
    unfinished = [row for row in simulations if row.status != SimulationStatus.PASS]
    if unfinished:
        listed = "; ".join(
            f"{row.name} is {row.status.replace('_', ' ')}"
            for row in sorted(unfinished, key=lambda row: row.position)
        )
        return GateResult(
            gate="failure_simulation",
            name="Failure simulation",
            passed=False,
            reason=f"Every scenario must pass before this publishes. {listed}.",
        )
    return GateResult(
        gate="failure_simulation",
        name="Failure simulation",
        passed=True,
        reason=f"All {len(simulations)} scenarios pass against the current design.",
    )


def _warnings(
    supervisor: Supervisor,
    supervised: list[SupervisorSupervised],
    handlers: list[SupervisorHandler],
    quality: list[SupervisorQualityGate],
    escalations: list[SupervisorEscalation],
    schedule: SupervisorSchedule | None,
) -> list[PublishWarning]:
    """Everything worth saying that the plan does not make a gate.

    Shown, never hidden, never in the way. §10 names one gate for a Supervisor; a second invented
    here would be a rule nobody approved.
    """
    warnings: list[PublishWarning] = []

    if not handlers and supervisor.kind == SupervisorKind.DEPARTMENT:
        warnings.append(
            PublishWarning(
                code="no_handlers",
                message=(
                    "Nobody but the owner can control this department supervisor. The plan's "
                    "decision table asks for explicit selected people rather than automatic "
                    "department-wide control, so somebody has to be named."
                ),
            )
        )

    if not escalations:
        warnings.append(
            PublishWarning(
                code="no_escalations",
                message=(
                    "No escalation rule is defined, so nothing says who hears about a failure "
                    "or when."
                ),
            )
        )

    if not quality:
        warnings.append(
            PublishWarning(
                code="no_quality_gates",
                message=(
                    "No quality gate is defined. §10 asks a supervisor to detect quality and "
                    "policy problems, and it has nothing to detect them against."
                ),
            )
        )

    if supervisor.max_concurrency is None and supervisor.token_cap is None:
        warnings.append(
            PublishWarning(
                code="no_ceilings",
                message=(
                    "Neither a concurrency limit nor a token ceiling is set, so this supervisor "
                    "is bounded only by the workspace policy."
                ),
            )
        )

    if schedule is not None and schedule.auto_run and not supervised:
        warnings.append(
            PublishWarning(
                code="auto_run_with_nothing_to_run",
                message=(
                    "Auto-run is on and nothing is supervised, so it will fire and find nothing "
                    "to do."
                ),
            )
        )

    #  Somebody left and the column naming them was cleared. Reported rather than enforced —
    #  refusing the deletion would block an offboarding, which is a worse failure.
    running = supervisor.status in (
        SupervisorStatus.PUBLISHED,
        SupervisorStatus.ACTIVE,
        SupervisorStatus.PAUSED,
    )
    if running and not supervisor.escalation_membership_id and not supervisor.escalation_label:
        warnings.append(
            PublishWarning(
                code="no_escalation_contact",
                message=(
                    "This supervisor is running and has nobody to escalate to — the person named "
                    "has most likely left. Name someone before it next fails."
                ),
            )
        )

    return warnings


def _next_action(
    supervisor: Supervisor, gate: GateResult, context: SecurityContext
) -> str:
    if supervisor.is_editable:
        if not gate.passed:
            return gate.reason
        if supervisor.approver_membership_id is None:
            return "Name an approver, then send this for approval."
        return "Send this for approval."
    if supervisor.status == SupervisorStatus.READY_TO_PUBLISH:
        if not gate.passed:
            return gate.reason
        if supervisor.approver_membership_id == context.membership_id:
            if supervisor.submitted_by_membership_id == context.membership_id:
                return "You submitted this, so somebody else has to approve it."
            return "Read it, then approve and publish."
        return "Waiting for the named approver."
    if supervisor.status == SupervisorStatus.PUBLISHED:
        return "Published. Editing it starts a new draft."
    return ""


async def record_simulations(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    entries: list[dict[str, Any]],
    *,
    expected_version: int,
) -> list[SupervisorSimulation]:
    """Write the failure scenarios and whatever has been observed of them.

    `edit_draft` and a handler role that confers it: a person who may not edit the design has no
    business asserting that it behaves correctly when things break. Approving what those results
    mean is the separate act, and it is somebody else's.
    """
    supervisor = await _get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.EDIT_DRAFT)

    if not supervisor.is_editable:
        raise ValidationFailed(
            f"This supervisor is {supervisor.status.replace('_', ' ')}. "
            "Results are recorded on a draft."
        )
    if supervisor.version != expected_version:
        raise Conflict("Somebody else changed this supervisor. Reload it and try again.")

    names = [entry["name"].strip() for entry in entries]
    if len(set(names)) != len(names):
        raise ValidationFailed("Two scenarios share a name.")

    existing = {row.name: row for row in await _rows(session, SupervisorSimulation, supervisor_id)}
    written: list[SupervisorSimulation] = []
    for position, entry in enumerate(entries, start=1):
        name = entry["name"].strip()
        row = existing.pop(name, None)
        if row is None:
            row = SupervisorSimulation(
                tenant_id=supervisor.tenant_id, supervisor_id=supervisor.id, name=name
            )
            session.add(row)
        row.what_fails = entry["what_fails"]
        row.expected_response = entry["expected_response"]
        status = entry.get("status", SimulationStatus.NOT_RUN)
        row.status = status
        row.observed = entry.get("observed")
        #  Stamped from the caller and the clock. A result somebody could backdate or attribute
        #  elsewhere is not evidence.
        observed = status != SimulationStatus.NOT_RUN
        row.run_by_membership_id = context.membership_id if observed else None
        row.run_at = _now() if observed else None
        row.position = position
        written.append(row)

    #  Anything not sent was removed from the list.
    for stale in existing.values():
        await session.delete(stale)

    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.simulations_recorded",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        detail={"results": {row.name: row.status for row in written}},
    )
    return written


def clear_results(simulations: list[SupervisorSimulation]) -> int:
    """Set every observed result back to `not_run`, and say how many were cleared.

    Called when the design changes. A pass recorded against yesterday's dependencies says nothing
    about today's, and deciding which edits "do not count" is exactly the judgement that lets a
    stale pass through. The scenario survives — what it tries and what should happen are part of
    the design. Only what was observed is cleared, because that is the part no longer true.
    """
    cleared = 0
    for row in simulations:
        if row.status == SimulationStatus.NOT_RUN:
            continue
        row.status = SimulationStatus.NOT_RUN
        row.observed = None
        row.run_by_membership_id = None
        row.run_at = None
        cleared += 1
    return cleared


async def submit(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    expected_version: int,
) -> Supervisor:
    """Send it for approval. The gate is checked here as well as at publish."""
    supervisor = await _get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.EDIT_DRAFT)

    if supervisor.version != expected_version:
        raise Conflict("Somebody else changed this supervisor. Reload it and try again.")
    if not supervisor.is_editable:
        raise ValidationFailed(
            f"This supervisor is {supervisor.status.replace('_', ' ')} and cannot be submitted."
        )
    if supervisor.approver_membership_id is None:
        raise ValidationFailed(
            "Name an approver — a person, not a role — before submitting this."
        )
    #  A Supervisor supervising nothing supervises nothing. Structural rather than a gate: the
    #  plan names one gate, and this is the same class of check as a Job needing a step.
    if not await _rows(session, SupervisorSupervised, supervisor_id):
        raise ValidationFailed(
            "Nothing is supervised. Name at least one person or agent before submitting."
        )
    _require(_simulation_gate(await _rows(session, SupervisorSimulation, supervisor_id)))

    supervisor.status = SupervisorStatus.READY_TO_PUBLISH
    supervisor.submitted_by_membership_id = context.membership_id
    supervisor.submitted_at = _now()
    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.submitted",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        detail={"approver": str(supervisor.approver_membership_id)},
    )
    return supervisor


async def withdraw(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    expected_version: int,
) -> Supervisor:
    """Take it back. The submitter is cleared so the next submission is judged on its own."""
    supervisor = await _get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.EDIT_DRAFT)

    if supervisor.version != expected_version:
        raise Conflict("Somebody else changed this supervisor. Reload it and try again.")
    if supervisor.status != SupervisorStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This supervisor is not waiting for approval.")

    supervisor.status = SupervisorStatus.NEEDS_REVIEW
    supervisor.submitted_by_membership_id = None
    supervisor.submitted_at = None
    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.withdrawn",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
    )
    return supervisor


async def publish(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    expected_version: int,
) -> SupervisorVersion:
    """Approve it, and freeze the design that was approved.

    The gate is re-checked here, not only at submission: a simulation result can be cleared by an
    edit between the two, and a publish that trusted the earlier check would approve a design
    nobody tested.
    """
    supervisor = await _get(session, supervisor_id)
    #  Both boundaries. `publish` in the workspace, and a handler role that confers it — which is
    #  Owner alone. A workspace administrator who is not a handler here cannot publish this.
    await guard.authorise_handler(session, context, supervisor, Action.PUBLISH)

    if supervisor.version != expected_version:
        raise Conflict(
            "This supervisor changed since you opened it. Reload and read it again before "
            "approving."
        )
    if supervisor.status != SupervisorStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This supervisor has not been submitted for approval.")
    if supervisor.approver_membership_id != context.membership_id:
        raise ValidationFailed("You are not the named approver for this supervisor.")

    await workspace_guard.refuse_self_approval(
        session,
        context,
        submitted_by_membership_id=supervisor.submitted_by_membership_id or uuid.UUID(int=0),
        resource=workspace_guard.Resource(type="supervisor", id=supervisor.id),
    )
    _require(_simulation_gate(await _rows(session, SupervisorSimulation, supervisor_id)))

    snapshot = await _snapshot(session, supervisor)
    version = SupervisorVersion(
        tenant_id=context.tenant_id,
        supervisor_id=supervisor.id,
        snapshot=snapshot,
        name=supervisor.name,
        published_by_membership_id=supervisor.submitted_by_membership_id,
        approved_by_membership_id=context.membership_id,
    )
    session.add(version)
    await session.flush()

    supervisor.status = SupervisorStatus.PUBLISHED
    supervisor.published_version_id = version.id
    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.published",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        detail={
            "version_id": str(version.id),
            "version_no": version.version_no,
            "submitted_by": str(supervisor.submitted_by_membership_id),
            "supervised": len(snapshot.get("supervised", [])),
            "handlers": len(snapshot.get("handlers", [])),
        },
    )
    return version


async def versions(
    session: AsyncSession, context: SecurityContext, supervisor_id: uuid.UUID
) -> list[SupervisorVersion]:
    """Everything ever published for this Supervisor, newest first."""
    supervisor = await _get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.VIEW)
    rows = (
        await session.execute(
            select(SupervisorVersion)
            .where(SupervisorVersion.supervisor_id == supervisor_id)
            .order_by(SupervisorVersion.version_no.desc())
        )
    ).scalars()
    return list(rows)


# ---------------------------------------------------------------------------- internals


def _require(gate: GateResult) -> None:
    if not gate.passed:
        raise ValidationFailed(gate.reason)


async def _get(session: AsyncSession, supervisor_id: uuid.UUID) -> Supervisor:
    supervisor = (
        await session.execute(select(Supervisor).where(Supervisor.id == supervisor_id))
    ).scalar_one_or_none()
    if supervisor is None:
        raise NotFound("No such supervisor.")
    return supervisor


async def _rows(session: AsyncSession, model: Any, supervisor_id: uuid.UUID) -> list[Any]:
    return list(
        (
            await session.execute(
                select(model).where(model.supervisor_id == supervisor_id)
            )
        )
        .scalars()
        .all()
    )


async def _names(
    session: AsyncSession, *membership_ids: uuid.UUID | None
) -> dict[uuid.UUID | None, str | None]:
    wanted = [value for value in membership_ids if value is not None]
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(Membership.id, Membership.display_name).where(Membership.id.in_(wanted))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def _snapshot(session: AsyncSession, supervisor: Supervisor) -> dict[str, Any]:
    """The whole design, frozen — **both scopes included**.

    The handler list is part of what was approved, not a setting alongside it: approving a
    Supervisor is approving who may control it. A snapshot that left it out would be a record of
    half the decision.
    """
    supervised = sorted(
        await _rows(session, SupervisorSupervised, supervisor.id), key=lambda r: r.position
    )
    handlers = sorted(
        await _rows(session, SupervisorHandler, supervisor.id), key=lambda r: str(r.membership_id)
    )
    dependencies = await _rows(session, SupervisorDependency, supervisor.id)
    quality = sorted(
        await _rows(session, SupervisorQualityGate, supervisor.id), key=lambda r: r.position
    )
    escalations = sorted(
        await _rows(session, SupervisorEscalation, supervisor.id), key=lambda r: r.position
    )
    notifications = sorted(
        await _rows(session, SupervisorNotification, supervisor.id), key=lambda r: r.position
    )
    simulations = sorted(
        await _rows(session, SupervisorSimulation, supervisor.id), key=lambda r: r.position
    )
    schedule = (
        await session.execute(
            select(SupervisorSchedule).where(
                SupervisorSchedule.supervisor_id == supervisor.id
            )
        )
    ).scalar_one_or_none()

    return {
        "supervisor": {
            "name": supervisor.name,
            "kind": supervisor.kind,
            "owner_membership_id": _plain(supervisor.owner_membership_id),
            "org_node_id": _plain(supervisor.org_node_id),
            "objective_id": _plain(supervisor.objective_id),
            "purpose": supervisor.purpose,
            "trigger": supervisor.trigger,
            "routing_policy": supervisor.routing_policy,
            "max_concurrency": supervisor.max_concurrency,
            "cost_cap_minor_units": supervisor.cost_cap_minor_units,
            "cost_cap_currency": supervisor.cost_cap_currency,
            "token_cap": supervisor.token_cap,
            "sla_minutes": supervisor.sla_minutes,
            "deadline_minutes": supervisor.deadline_minutes,
            "max_retries": supervisor.max_retries,
            "retry_backoff_seconds": supervisor.retry_backoff_seconds,
            "approver_membership_id": _plain(supervisor.approver_membership_id),
            "approver_label": supervisor.approver_label,
            "escalation_membership_id": _plain(supervisor.escalation_membership_id),
            "escalation_label": supervisor.escalation_label,
        },
        "supervised": [
            {
                "position": row.position,
                "membership_id": _plain(row.membership_id),
                "agent_id": _plain(row.agent_id),
                "agent_version_id": _plain(row.agent_version_id),
            }
            for row in supervised
        ],
        #  Approving a Supervisor is approving who may control it.
        "handlers": [
            {
                "membership_id": _plain(row.membership_id),
                "role": row.role,
                "granted_by_membership_id": _plain(row.granted_by_membership_id),
                "granted_at": _plain(row.granted_at),
            }
            for row in handlers
        ],
        "dependencies": [
            {
                "supervised_id": _plain(row.supervised_id),
                "depends_on_id": _plain(row.depends_on_id),
            }
            for row in dependencies
        ],
        "quality_gates": [
            {
                "position": row.position,
                "name": row.name,
                "condition": row.condition,
                "evidence": row.evidence,
                "on_failure": row.on_failure,
            }
            for row in quality
        ],
        "escalations": [
            {
                "position": row.position,
                "situation": row.situation,
                "required_action": row.required_action,
                "escalate_to_membership_id": _plain(row.escalate_to_membership_id),
                "escalate_to_label": row.escalate_to_label,
                "after_minutes": row.after_minutes,
            }
            for row in escalations
        ],
        "notifications": [
            {
                "position": row.position,
                "event": row.event,
                "channel": row.channel,
                "to_handlers": row.to_handlers,
                "recipient_membership_id": _plain(row.recipient_membership_id),
                "recipient_label": row.recipient_label,
            }
            for row in notifications
        ],
        "schedule": (
            {
                "auto_run": schedule.auto_run,
                "timezone": schedule.timezone,
                "frequency": schedule.frequency,
                "interval": schedule.interval,
                "at_time": schedule.at_time.isoformat(),
                "weekdays": list(schedule.weekdays),
                "monthday": schedule.monthday,
                "dst_policy": schedule.dst_policy,
                "ambiguous_policy": schedule.ambiguous_policy,
                "skip_dates": list(schedule.skip_dates),
                "weekdays_only": schedule.weekdays_only,
                "missed_run_policy": schedule.missed_run_policy,
                "overlap_policy": schedule.overlap_policy,
            }
            if schedule is not None
            else None
        ),
        "simulations": [
            {
                "position": row.position,
                "name": row.name,
                "what_fails": row.what_fails,
                "expected_response": row.expected_response,
                "status": row.status,
                "observed": row.observed,
                "run_by_membership_id": _plain(row.run_by_membership_id),
                "run_at": _plain(row.run_at),
            }
            for row in simulations
        ],
    }


def _plain(value: Any) -> Any:
    """UUIDs and datetimes as strings, so the snapshot is JSON a person can read."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
