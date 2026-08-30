"""Creating and editing a Supervisor draft.

The same shape as the other Builders' services: authorise, match the version, replace child
collections wholesale, write an audit event, commit together.

Two things are specific to this one:

**Editing the design clears every simulation result.** A pass recorded against yesterday's
dependencies says nothing about today's, and deciding which edits "do not count" is exactly the
judgement that lets a stale pass through. This is the caller 6.4 said would arrive here.

**Handlers are not in the payload.** Changing who may control a Supervisor is `manage_access` and
changing what it watches is `edit_draft`; one payload carrying both would let the looser
permission decide the stricter one. `handlers.py` owns scope 2 and this file never touches it.
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
from uboss.modules.agents.agent_models import Agent
from uboss.modules.audit import service as audit
from uboss.modules.hierarchy.models import OrgUnit
from uboss.modules.identity import guard as workspace_guard
from uboss.modules.identity.models import Membership
from uboss.modules.objectives.models import Objective
from uboss.modules.supervisors import guard, publish, roles
from uboss.modules.supervisors.models import (
    HandlerRole,
    OnFailure,
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
)
from uboss.modules.supervisors.schemas import (
    DependencyRead,
    EscalationRead,
    HandlerRead,
    NotificationRead,
    QualityGateRead,
    SupervisedRead,
    SupervisorCard,
    SupervisorCreate,
    SupervisorList,
    SupervisorRead,
    SupervisorScheduleRead,
    SupervisorScheduleWrite,
    SupervisorUpdate,
)

_SCALAR_FIELDS = frozenset(
    {
        "name",
        "objective_id",
        "purpose",
        "trigger",
        "routing_policy",
        "max_concurrency",
        "cost_cap_minor_units",
        "cost_cap_currency",
        "token_cap",
        "sla_minutes",
        "deadline_minutes",
        "max_retries",
        "retry_backoff_seconds",
        "approver_membership_id",
        "approver_label",
        "escalation_membership_id",
        "escalation_label",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


async def list_supervisors(
    session: AsyncSession,
    context: SecurityContext,
    *,
    status: str | None = None,
    include_archived: bool = False,
) -> SupervisorList:
    """The Supervisors this person may see.

    Row-level security keeps this inside the workspace; the handler scope narrows it further, so
    the list shows what somebody can actually open rather than a set of locked doors.
    """
    await workspace_guard.authorise(session, context, Action.VIEW)

    supervised = (
        select(
            SupervisorSupervised.supervisor_id.label("supervisor_id"),
            func.count().label("n"),
        )
        .group_by(SupervisorSupervised.supervisor_id)
        .subquery()
    )
    handled = (
        select(
            SupervisorHandler.supervisor_id.label("supervisor_id"), func.count().label("n")
        )
        .group_by(SupervisorHandler.supervisor_id)
        .subquery()
    )

    statement = (
        select(
            Supervisor,
            Membership.display_name,
            func.coalesce(supervised.c.n, 0),
            func.coalesce(handled.c.n, 0),
        )
        .outerjoin(Membership, Membership.id == Supervisor.owner_membership_id)
        .outerjoin(supervised, supervised.c.supervisor_id == Supervisor.id)
        .outerjoin(handled, handled.c.supervisor_id == Supervisor.id)
        .order_by(Supervisor.updated_at.desc())
    )
    if not include_archived:
        statement = statement.where(Supervisor.archived_at.is_(None))
    if status:
        statement = statement.where(Supervisor.status == status)

    rows = (await session.execute(statement)).all()
    visible: list[SupervisorCard] = []
    for supervisor, owner_name, supervised_count, handler_count in rows:
        #  Scope 2 decides what appears. A Supervisor somebody cannot control is not theirs to
        #  see, and listing it would leak who supervises whom.
        if await guard.role_for(session, supervisor, context.membership_id) is None:
            continue
        visible.append(
            SupervisorCard(
                id=supervisor.id,
                name=supervisor.name,
                kind=SupervisorKind(supervisor.kind),
                status=SupervisorStatus(supervisor.status),
                owner_name=owner_name,
                supervised_count=supervised_count,
                handler_count=handler_count,
                updated_at=supervisor.updated_at,
            )
        )

    total = (
        await session.execute(
            select(func.count()).select_from(Supervisor).where(Supervisor.archived_at.is_(None))
        )
    ).scalar_one()
    return SupervisorList(supervisors=visible, is_empty=total == 0)


async def read(
    session: AsyncSession, context: SecurityContext, supervisor_id: uuid.UUID
) -> SupervisorRead:
    supervisor = await get(session, supervisor_id)
    role = await guard.authorise_handler(session, context, supervisor, Action.VIEW)
    return await _describe(session, supervisor, role)


async def create(
    session: AsyncSession, context: SecurityContext, payload: SupervisorCreate
) -> Supervisor:
    """Start a draft.

    The creator becomes the owner, which makes them Owner without a handler row. A Supervisor
    whose creator could not then control it would be a Supervisor nobody could finish.
    """
    await workspace_guard.authorise(session, context, Action.EDIT_DRAFT)

    if payload.kind == SupervisorKind.DEPARTMENT and payload.org_node_id is None:
        raise ValidationFailed(
            "A department supervisor supervises a department. Name the one it is for."
        )
    if payload.kind == SupervisorKind.PERSONAL and payload.org_node_id is not None:
        raise ValidationFailed(
            "A personal supervisor watches its owner's own agents, so it has no department."
        )
    if context.membership_id is None:
        raise ValidationFailed("Only a member of this workspace can own a supervisor.")

    supervisor = Supervisor(
        tenant_id=context.tenant_id,
        name=payload.name.strip(),
        kind=payload.kind,
        owner_membership_id=context.membership_id,
        org_node_id=payload.org_node_id,
        objective_id=payload.objective_id,
        created_by_membership_id=context.membership_id,
        status=SupervisorStatus.DRAFT,
    )
    session.add(supervisor)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.created",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        detail={"name": supervisor.name, "kind": str(payload.kind)},
    )
    return supervisor


async def update(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    payload: SupervisorUpdate,
) -> Supervisor:
    """Save the draft, and clear every simulation result.

    The clearing is not optional and not selective. A pass recorded against yesterday's design
    says nothing about today's, and choosing which edits "do not count" is the judgement that
    lets a stale pass through — so none of them do.
    """
    supervisor = await get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.EDIT_DRAFT)

    if not supervisor.is_editable:
        raise ValidationFailed(
            f"This supervisor is {supervisor.status.replace('_', ' ')} and cannot be edited."
        )
    if supervisor.version != payload.expected_version:
        raise Conflict(
            "Somebody else saved this supervisor while you were editing. Reload it and apply "
            "your change again."
        )

    changes = payload.model_dump(exclude_unset=True)
    changes.pop("expected_version", None)
    supervised = changes.pop("supervised", None)
    dependencies = changes.pop("dependencies", None)
    quality = changes.pop("quality_gates", None)
    escalations = changes.pop("escalations", None)
    notifications = changes.pop("notifications", None)

    for field, value in changes.items():
        if field in _SCALAR_FIELDS:
            setattr(supervisor, field, value)

    for column, role in (
        ("approver_membership_id", "approver"),
        ("escalation_membership_id", "escalation contact"),
    ):
        if changes.get(column) is not None:
            await _require_member(session, changes[column], role)

    #  Dependencies name positions in the supervised list, so the list has to be written first.
    if supervised is not None:
        await _replace_supervised(session, supervisor, supervised)
    if dependencies is not None:
        await _replace_dependencies(session, supervisor, dependencies)
    if quality is not None:
        await _replace(session, SupervisorQualityGate, supervisor, quality)
    if escalations is not None:
        await _replace(session, SupervisorEscalation, supervisor, escalations)
    if notifications is not None:
        await _replace(session, SupervisorNotification, supervisor, notifications)

    cleared = publish.clear_results(
        list(
            (
                await session.execute(
                    select(SupervisorSimulation).where(
                        SupervisorSimulation.supervisor_id == supervisor.id
                    )
                )
            )
            .scalars()
            .all()
        )
    )

    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.updated",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        #  Which fields, never their values. A Supervisor carries a company's escalation policy.
        detail={
            "fields": sorted(changes),
            "simulation_results_cleared": cleared,
            "replaced": sorted(
                name
                for name, sent in (
                    ("supervised", supervised),
                    ("dependencies", dependencies),
                    ("quality_gates", quality),
                    ("escalations", escalations),
                    ("notifications", notifications),
                )
                if sent is not None
            ),
        },
    )
    return supervisor


async def set_schedule(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    payload: SupervisorScheduleWrite,
) -> SupervisorSchedule:
    """When it runs. `schedule` in the workspace, and a role that confers it — Manager or above.

    Setting a schedule is not editing a design: it decides when something starts happening, and
    §14 has a verb for exactly that.
    """
    supervisor = await get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.SCHEDULE)

    if supervisor.version != payload.expected_version:
        raise Conflict("Somebody else changed this supervisor. Reload it and try again.")

    existing = (
        await session.execute(
            select(SupervisorSchedule).where(
                SupervisorSchedule.supervisor_id == supervisor_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = SupervisorSchedule(
            tenant_id=context.tenant_id,
            supervisor_id=supervisor_id,
            created_by_membership_id=context.membership_id,
            timezone=payload.timezone,
            frequency=payload.frequency,
            at_time=payload.at_time,
        )
        session.add(existing)

    for field in (
        "auto_run",
        "timezone",
        "frequency",
        "interval",
        "at_time",
        "weekdays",
        "monthday",
        "dst_policy",
        "ambiguous_policy",
        "skip_dates",
        "weekdays_only",
        "missed_run_policy",
        "overlap_policy",
    ):
        setattr(existing, field, getattr(payload, field))

    #  Validated by the Job's own pure module, so a Supervisor schedule cannot be accepted where
    #  the identical Job schedule would have been refused.
    from uboss.modules.jobs import recurrence

    recurrence.validate(recurrence.from_row(existing))

    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.schedule_set",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        detail={"auto_run": existing.auto_run, "frequency": existing.frequency},
    )
    return existing


async def archive(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    expected_version: int,
) -> Supervisor:
    supervisor = await get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.EDIT_DRAFT)

    if supervisor.version != expected_version:
        raise Conflict("Somebody else changed this supervisor. Reload it and try again.")
    if supervisor.archived_at is not None:
        return supervisor

    supervisor.archived_at = _now()
    supervisor.status = SupervisorStatus.ARCHIVED
    supervisor.published_version_id = None
    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.archived",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        detail={"name": supervisor.name},
    )
    return supervisor


# ---------------------------------------------------------------------------- internals


async def get(session: AsyncSession, supervisor_id: uuid.UUID) -> Supervisor:
    supervisor = (
        await session.execute(select(Supervisor).where(Supervisor.id == supervisor_id))
    ).scalar_one_or_none()
    if supervisor is None:
        raise NotFound("No such supervisor.")
    return supervisor


async def _require_member(
    session: AsyncSession, membership_id: uuid.UUID, role: str
) -> None:
    member = (
        await session.execute(select(Membership).where(Membership.id == membership_id))
    ).scalar_one_or_none()
    if member is None:
        raise ValidationFailed(f"That {role} is not a member of this workspace.")


async def _replace_supervised(
    session: AsyncSession, supervisor: Supervisor, rows: list[dict[str, Any]]
) -> None:
    """Scope 1, replaced wholesale.

    The dependency rows point at these by id, so they go first and anything left dangling is
    removed by the cascade rather than by a second pass here.
    """
    positions = [row["position"] for row in rows]
    if len(set(positions)) != len(positions):
        raise ValidationFailed("Two supervised rows share a position. Renumber them.")

    await session.execute(
        delete(SupervisorDependency).where(
            SupervisorDependency.supervisor_id == supervisor.id
        )
    )
    await session.execute(
        delete(SupervisorSupervised).where(
            SupervisorSupervised.supervisor_id == supervisor.id
        )
    )
    for row in rows:
        session.add(
            SupervisorSupervised(
                tenant_id=supervisor.tenant_id, supervisor_id=supervisor.id, **row
            )
        )
    await session.flush()


async def _replace_dependencies(
    session: AsyncSession, supervisor: Supervisor, rows: list[dict[str, Any]]
) -> None:
    """Positions in, row ids out.

    The API speaks positions because that is what a screen has; the database speaks ids because
    that is what a foreign key needs. Translating here means a caller cannot name a row belonging
    to another Supervisor.
    """
    by_position = {
        row.position: row.id
        for row in (
            await session.execute(
                select(SupervisorSupervised).where(
                    SupervisorSupervised.supervisor_id == supervisor.id
                )
            )
        )
        .scalars()
        .all()
    }
    await session.execute(
        delete(SupervisorDependency).where(
            SupervisorDependency.supervisor_id == supervisor.id
        )
    )
    for row in rows:
        try:
            downstream = by_position[row["supervised_position"]]
            upstream = by_position[row["depends_on_position"]]
        except KeyError as missing:
            raise ValidationFailed(
                f"A dependency names position {missing.args[0]}, which is not in the supervised "
                "list."
            ) from missing
        session.add(
            SupervisorDependency(
                tenant_id=supervisor.tenant_id,
                supervisor_id=supervisor.id,
                supervised_id=downstream,
                depends_on_id=upstream,
            )
        )
    await session.flush()


async def _replace(
    session: AsyncSession, model: Any, supervisor: Supervisor, rows: list[dict[str, Any]]
) -> None:
    """The three plain position-ordered collections, replaced wholesale."""
    positions = [row["position"] for row in rows]
    if len(set(positions)) != len(positions):
        raise ValidationFailed(
            f"Two {model.__tablename__.replace('supervisor_', '').replace('_', ' ')} rows share "
            "a position. Renumber them."
        )
    await session.execute(delete(model).where(model.supervisor_id == supervisor.id))
    for row in rows:
        session.add(
            model(tenant_id=supervisor.tenant_id, supervisor_id=supervisor.id, **row)
        )


async def _describe(
    session: AsyncSession, supervisor: Supervisor, role: Any
) -> SupervisorRead:
    """One Supervisor in full, so a form renders from one request."""
    supervised = sorted(
        await _rows(session, SupervisorSupervised, supervisor.id), key=lambda r: r.position
    )
    handlers = await _rows(session, SupervisorHandler, supervisor.id)
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
    schedule = (
        await session.execute(
            select(SupervisorSchedule).where(
                SupervisorSchedule.supervisor_id == supervisor.id
            )
        )
    ).scalar_one_or_none()

    wanted = {supervisor.owner_membership_id, supervisor.approver_membership_id}
    wanted |= {row.membership_id for row in supervised}
    wanted |= {row.membership_id for row in handlers}
    wanted |= {row.escalate_to_membership_id for row in escalations}
    wanted |= {row.recipient_membership_id for row in notifications}
    wanted.add(supervisor.escalation_membership_id)
    names = await _names(session, [value for value in wanted if value is not None])

    agent_names = await _agent_names(
        session, [row.agent_id for row in supervised if row.agent_id]
    )

    org_node_name = None
    if supervisor.org_node_id is not None:
        org_node_name = (
            await session.execute(
                select(OrgUnit.name).where(OrgUnit.id == supervisor.org_node_id)
            )
        ).scalar_one_or_none()
    objective_name = None
    if supervisor.objective_id is not None:
        objective_name = (
            await session.execute(
                select(Objective.title).where(Objective.id == supervisor.objective_id)
            )
        ).scalar_one_or_none()

    return SupervisorRead(
        id=supervisor.id,
        version=supervisor.version,
        status=SupervisorStatus(supervisor.status),
        is_editable=supervisor.is_editable,
        name=supervisor.name,
        kind=SupervisorKind(supervisor.kind),
        owner_membership_id=supervisor.owner_membership_id,
        owner_name=names.get(supervisor.owner_membership_id),
        org_node_id=supervisor.org_node_id,
        org_node_name=org_node_name,
        objective_id=supervisor.objective_id,
        objective_name=objective_name,
        purpose=supervisor.purpose,
        trigger=supervisor.trigger,
        routing_policy=supervisor.routing_policy,
        max_concurrency=supervisor.max_concurrency,
        cost_cap_minor_units=supervisor.cost_cap_minor_units,
        cost_cap_currency=supervisor.cost_cap_currency,
        token_cap=supervisor.token_cap,
        sla_minutes=supervisor.sla_minutes,
        deadline_minutes=supervisor.deadline_minutes,
        max_retries=supervisor.max_retries,
        retry_backoff_seconds=supervisor.retry_backoff_seconds,
        approver_membership_id=supervisor.approver_membership_id,
        approver_name=names.get(supervisor.approver_membership_id),
        approver_label=supervisor.approver_label,
        escalation_membership_id=supervisor.escalation_membership_id,
        escalation_name=names.get(supervisor.escalation_membership_id),
        escalation_label=supervisor.escalation_label,
        supervised=[
            SupervisedRead(
                id=row.id,
                position=row.position,
                membership_id=row.membership_id,
                person_name=names.get(row.membership_id),
                agent_id=row.agent_id,
                agent_name=agent_names.get(row.agent_id) if row.agent_id else None,
                agent_version_id=row.agent_version_id,
            )
            for row in supervised
        ],
        handlers=[
            HandlerRead(
                id=row.id,
                membership_id=row.membership_id,
                person_name=names.get(row.membership_id),
                role=HandlerRole(row.role),
                granted_by_membership_id=row.granted_by_membership_id,
                granted_at=row.granted_at,
            )
            for row in handlers
        ],
        dependencies=[
            DependencyRead(
                id=row.id,
                supervised_id=row.supervised_id,
                depends_on_id=row.depends_on_id,
            )
            for row in dependencies
        ],
        quality_gates=[
            QualityGateRead(
                id=row.id,
                position=row.position,
                name=row.name,
                condition=row.condition,
                evidence=row.evidence,
                on_failure=OnFailure(row.on_failure),
            )
            for row in quality
        ],
        escalations=[
            EscalationRead(
                id=row.id,
                position=row.position,
                situation=row.situation,
                required_action=row.required_action,
                escalate_to_membership_id=row.escalate_to_membership_id,
                escalate_to_name=names.get(row.escalate_to_membership_id),
                escalate_to_label=row.escalate_to_label,
                after_minutes=row.after_minutes,
            )
            for row in escalations
        ],
        notifications=[
            NotificationRead(
                id=row.id,
                position=row.position,
                event=row.event,
                channel=row.channel,
                to_handlers=row.to_handlers,
                recipient_membership_id=row.recipient_membership_id,
                recipient_name=names.get(row.recipient_membership_id),
                recipient_label=row.recipient_label,
            )
            for row in notifications
        ],
        schedule=(
            SupervisorScheduleRead(
                id=schedule.id,
                auto_run=schedule.auto_run,
                timezone=schedule.timezone,
                frequency=schedule.frequency,
                interval=schedule.interval,
                at_time=schedule.at_time,
                weekdays=list(schedule.weekdays),
                monthday=schedule.monthday,
                dst_policy=schedule.dst_policy,
                ambiguous_policy=schedule.ambiguous_policy,
                skip_dates=list(schedule.skip_dates),
                weekdays_only=schedule.weekdays_only,
                missed_run_policy=schedule.missed_run_policy,
                overlap_policy=schedule.overlap_policy,
                version=schedule.version,
            )
            if schedule is not None
            else None
        ),
        my_role=role,
        #  What the role permits, so the screen disables what it must rather than working the
        #  answer out itself. The server still refuses either way.
        my_actions=sorted(str(action) for action in roles.PERMITS[role]) if role else [],
        created_at=supervisor.created_at,
        updated_at=supervisor.updated_at,
    )


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
    session: AsyncSession, membership_ids: list[uuid.UUID]
) -> dict[uuid.UUID | None, str | None]:
    if not membership_ids:
        return {}
    rows = (
        await session.execute(
            select(Membership.id, Membership.display_name).where(
                Membership.id.in_(membership_ids)
            )
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def _agent_names(
    session: AsyncSession, agent_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not agent_ids:
        return {}
    rows = (
        await session.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
    ).all()
    return {row[0]: row[1] for row in rows}
