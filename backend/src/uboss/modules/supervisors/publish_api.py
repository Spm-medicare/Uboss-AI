"""Publishing a Supervisor over HTTP — the simulations, the gate, and the frozen version.

Every route here goes through `guard.authorise_handler`, so both boundaries apply: the workspace
verb *and* a handler role that confers it. A workspace administrator who is not a handler on this
Supervisor cannot publish it, which is the point of scope 2 existing.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.identity.models import Membership
from uboss.modules.supervisors import publish as publish_service
from uboss.modules.supervisors.models import SimulationStatus, SupervisorKind, SupervisorStatus

router = APIRouter(prefix="/supervisors/{supervisor_id}", tags=["supervisors"])


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimulationInput(_Payload):
    """One failure scenario.

    `run_by` and `run_at` are deliberately absent — they are stamped by the server from the caller
    and the clock. A result somebody could backdate or attribute to a colleague is not evidence.
    """

    name: str = Field(min_length=1, max_length=200)
    what_fails: str = Field(min_length=1, max_length=4000)
    expected_response: str = Field(min_length=1, max_length=4000)
    status: SimulationStatus = SimulationStatus.NOT_RUN
    #: Required by the schema for any status but `Not Run`.
    observed: str | None = Field(default=None, max_length=4000)


class SimulationsUpdate(_Payload):
    expected_version: int
    simulations: list[SimulationInput] = Field(max_length=30)


class SimulationRead(BaseModel):
    id: uuid.UUID
    position: int
    name: str
    what_fails: str
    expected_response: str
    status: SimulationStatus
    observed: str | None
    run_by_membership_id: uuid.UUID | None
    run_by_name: str | None
    run_at: str | None


class SimulationList(BaseModel):
    simulations: list[SimulationRead]
    passed: int
    total: int


class SupervisorGate(BaseModel):
    """The one gate `PLAN.md` names. `reason` says what would clear it, not merely that it is
    closed — a screen saying "blocked" alone sends somebody hunting."""

    gate: str
    name: str
    passed: bool
    reason: str


class SupervisorWarning(BaseModel):
    """Worth saying, and not a gate. Shown, never hidden, never in the way."""

    code: str
    message: str


class SupervisorPublishSummary(BaseModel):
    supervisor_id: uuid.UUID
    name: str
    kind: SupervisorKind
    status: SupervisorStatus
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

    gates: list[SupervisorGate]
    warnings: list[SupervisorWarning]
    next_action: str
    can_submit: bool
    can_approve: bool
    version: int


class SupervisorVersionCard(BaseModel):
    id: uuid.UUID
    version_no: int
    name: str
    published_by_name: str | None
    approved_by_name: str | None
    published_at: str


class SupervisorVersionList(BaseModel):
    versions: list[SupervisorVersionCard]
    is_empty: bool


class SupervisorPublishRequest(_Payload):
    expected_version: int


async def _simulation_list(session: SessionDep, supervisor_id: uuid.UUID) -> SimulationList:
    from sqlalchemy import select

    from uboss.modules.supervisors.models import SupervisorSimulation

    rows = sorted(
        (
            await session.execute(
                select(SupervisorSimulation).where(
                    SupervisorSimulation.supervisor_id == supervisor_id
                )
            )
        )
        .scalars()
        .all(),
        key=lambda row: row.position,
    )
    runners = {row.run_by_membership_id for row in rows if row.run_by_membership_id}
    names: dict[uuid.UUID, str] = {}
    if runners:
        names = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(Membership.id, Membership.display_name).where(
                        Membership.id.in_(runners)
                    )
                )
            ).all()
        }

    return SimulationList(
        simulations=[
            SimulationRead(
                id=row.id,
                position=row.position,
                name=row.name,
                what_fails=row.what_fails,
                expected_response=row.expected_response,
                status=SimulationStatus(row.status),
                observed=row.observed,
                run_by_membership_id=row.run_by_membership_id,
                run_by_name=(
                    names.get(row.run_by_membership_id) if row.run_by_membership_id else None
                ),
                run_at=row.run_at.isoformat() if row.run_at else None,
            )
            for row in rows
        ],
        passed=sum(1 for row in rows if row.status == SimulationStatus.PASS),
        total=len(rows),
    )


@router.get("/simulations", summary="The failure scenarios")
async def read_simulations(
    supervisor_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> SimulationList:
    from uboss.core.permissions import Action
    from uboss.modules.supervisors import guard, service

    supervisor = await service.get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.VIEW)
    return await _simulation_list(session, supervisor_id)


@router.put("/simulations", summary="Record the failure scenarios and what was observed")
async def write_simulations(
    supervisor_id: uuid.UUID,
    body: SimulationsUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SimulationList:
    """Who ran it and when are stamped by the server, never accepted from the caller."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="supervisor.simulations",
        payload={"supervisor_id": str(supervisor_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return SimulationList.model_validate(execution.replay_body)

        await publish_service.record_simulations(
            session,
            context,
            supervisor_id,
            [entry.model_dump(mode="json") for entry in body.simulations],
            expected_version=body.expected_version,
        )
        result = await _simulation_list(session, supervisor_id)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.get("/publish", summary="What publishing this would mean")
async def publish_summary(
    supervisor_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> SupervisorPublishSummary:
    found = await publish_service.summary(session, context, supervisor_id)
    return SupervisorPublishSummary(
        supervisor_id=found.supervisor_id,
        name=found.name,
        kind=SupervisorKind(found.kind),
        status=SupervisorStatus(found.status),
        owner_name=found.owner_name,
        approver_name=found.approver_name,
        submitted_by_name=found.submitted_by_name,
        supervised_count=found.supervised_count,
        handler_count=found.handler_count,
        dependency_count=found.dependency_count,
        quality_gate_count=found.quality_gate_count,
        escalation_count=found.escalation_count,
        notification_count=found.notification_count,
        has_schedule=found.has_schedule,
        schedule_auto_run=found.schedule_auto_run,
        simulations_passed=found.simulations_passed,
        simulations_total=found.simulations_total,
        gates=[
            SupervisorGate(
                gate=gate.gate, name=gate.name, passed=gate.passed, reason=gate.reason
            )
            for gate in found.gates
        ],
        warnings=[
            SupervisorWarning(code=warning.code, message=warning.message)
            for warning in found.warnings
        ],
        next_action=found.next_action,
        can_submit=found.can_submit,
        can_approve=found.can_approve,
        version=found.version,
    )


def _transition(operation: str):  # type: ignore[no-untyped-def]
    """Submit, withdraw and publish differ only in which service call they make."""

    async def route(
        supervisor_id: uuid.UUID,
        body: SupervisorPublishRequest,
        context: CurrentContext,
        session: SessionDep,
        idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    ) -> dict[str, str]:
        async with idempotency.execute(
            session,
            tenant_id=context.tenant_id,
            key=idempotency_key,
            operation=f"supervisor.{operation}",
            payload={"supervisor_id": str(supervisor_id), **body.model_dump()},
        ) as execution:
            if execution.is_replay:
                return cast(dict[str, str], execution.replay_body)

            if operation == "publish":
                version = await publish_service.publish(
                    session, context, supervisor_id, body.expected_version
                )
                result = {
                    "version_id": str(version.id),
                    "version_no": str(version.version_no),
                    "supervisor_id": str(supervisor_id),
                }
                execution.complete_json(
                    status_code=status.HTTP_201_CREATED, body=result
                )
                return result

            call = (
                publish_service.submit if operation == "submit" else publish_service.withdraw
            )
            supervisor = await call(
                session, context, supervisor_id, body.expected_version
            )
            result = {
                "id": str(supervisor.id),
                "version": str(supervisor.version),
                "status": supervisor.status,
            }
            execution.complete_json(status_code=status.HTTP_200_OK, body=result)
            return result

    return route


router.add_api_route(
    "/submit",
    _transition("submit"),
    methods=["POST"],
    summary="Send for approval",
    response_model=dict[str, str],
)
router.add_api_route(
    "/withdraw",
    _transition("withdraw"),
    methods=["POST"],
    summary="Take it back out of the queue",
    response_model=dict[str, str],
)
router.add_api_route(
    "/publish",
    _transition("publish"),
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    summary="Approve and publish",
    response_model=dict[str, str],
)


@router.get("/versions", summary="What has been published")
async def versions(
    supervisor_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> SupervisorVersionList:
    from sqlalchemy import select

    rows = await publish_service.versions(session, context, supervisor_id)
    people = {row.published_by_membership_id for row in rows} | {
        row.approved_by_membership_id for row in rows
    }
    wanted = [value for value in people if value is not None]
    names: dict[uuid.UUID, str] = {}
    if wanted:
        names = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(Membership.id, Membership.display_name).where(
                        Membership.id.in_(wanted)
                    )
                )
            ).all()
        }

    return SupervisorVersionList(
        versions=[
            SupervisorVersionCard(
                id=row.id,
                version_no=row.version_no,
                name=row.name,
                published_by_name=(
                    names.get(row.published_by_membership_id)
                    if row.published_by_membership_id
                    else None
                ),
                approved_by_name=(
                    names.get(row.approved_by_membership_id)
                    if row.approved_by_membership_id
                    else None
                ),
                published_at=row.published_at.isoformat(),
            )
            for row in rows
        ],
        is_empty=not rows,
    )
