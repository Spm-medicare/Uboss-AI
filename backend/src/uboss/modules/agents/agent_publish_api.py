"""Publishing an Agent over HTTP — the tests, the two gates, and the frozen version.

The same routes as the Job's publish, plus one the Job does not have: `PUT /tests`, which is
Form 4 section C. §9 makes tests a publish gate, so recording them is part of preparing a design
rather than a separate feature.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.core.permissions import Action
from uboss.modules.agents import agent_publish as publish_service
from uboss.modules.agents.agent_models import AgentTest, SandboxTestKind, SandboxTestStatus
from uboss.modules.agents.agent_publish_schemas import (
    STATUS_LABELS,
    TEST_LABELS,
    AgentPublishGate,
    AgentPublishRequest,
    AgentPublishSummary,
    AgentPublishWarning,
    AgentVersionCard,
    AgentVersionList,
    SandboxTestList,
    SandboxTestRead,
    SandboxTestsUpdate,
)
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership

router = APIRouter(prefix="/agents/{agent_id}", tags=["agents"])


def _card(test: AgentTest, run_by_name: str | None) -> SandboxTestRead:
    return SandboxTestRead(
        id=test.id,
        kind=SandboxTestKind(test.kind),
        label=TEST_LABELS[test.kind],
        sample_situation=test.sample_situation,
        expected_result=test.expected_result,
        status=SandboxTestStatus(test.status),
        status_label=STATUS_LABELS[test.status],
        actual_result=test.actual_result,
        run_by_membership_id=test.run_by_membership_id,
        run_by_name=run_by_name,
        run_at=test.run_at,
    )


async def _test_list(
    session: SessionDep, agent_id: uuid.UUID
) -> SandboxTestList:
    from sqlalchemy import select

    rows = list(
        (await session.execute(select(AgentTest).where(AgentTest.agent_id == agent_id)))
        .scalars()
        .all()
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

    ordered = sorted(rows, key=lambda row: list(SandboxTestKind).index(SandboxTestKind(row.kind)))
    present = {row.kind for row in rows}
    return SandboxTestList(
        tests=[
            _card(row, names.get(row.run_by_membership_id) if row.run_by_membership_id else None)
            for row in ordered
        ],
        missing=[kind for kind in SandboxTestKind if kind not in present],
        passed=sum(1 for row in rows if row.status == SandboxTestStatus.PASS),
        total=len(SandboxTestKind),
    )


@router.get("/tests", summary="Form 4 section C — the five sandbox tests")
async def read_tests(
    agent_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> SandboxTestList:
    """`missing` and a `Not Run` status are different answers, so both are reported."""
    await guard.authorise(session, context, Action.VIEW)
    return await _test_list(session, agent_id)


@router.put("/tests", summary="Record the five tests and what was observed")
async def write_tests(
    agent_id: uuid.UUID,
    body: SandboxTestsUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SandboxTestList:
    """Who ran it and when are stamped by the server, never accepted from the caller."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="agent.tests",
        payload={"agent_id": str(agent_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return SandboxTestList.model_validate(execution.replay_body)

        await publish_service.record_tests(
            session,
            context,
            agent_id,
            [entry.model_dump(mode="json") for entry in body.tests],
            expected_version=body.expected_version,
        )
        result = await _test_list(session, agent_id)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.get("/publish", summary="What publishing this would mean")
async def publish_summary(
    agent_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> AgentPublishSummary:
    """§9's two gates, every warning, and the one next action worth taking."""
    found = await publish_service.summary(session, context, agent_id)
    return AgentPublishSummary(
        agent_id=found.agent_id,
        name=found.name,
        status=found.status,
        owner_name=found.owner_name,
        approver_name=found.approver_name,
        submitted_by_name=found.submitted_by_name,
        job_name=found.job_name,
        job_version_no=found.job_version_no,
        step_count=found.step_count,
        skill_count=found.skill_count,
        tool_count=found.tool_count,
        granted_tool_count=found.granted_tool_count,
        io_input_count=found.io_input_count,
        io_output_count=found.io_output_count,
        knowledge_count=found.knowledge_count,
        personal_data_sources=found.personal_data_sources,
        shared_with_count=found.shared_with_count,
        tests_passed=found.tests_passed,
        tests_total=found.tests_total,
        gates=[
            AgentPublishGate(gate=gate.gate, name=gate.name, passed=gate.passed, reason=gate.reason)
            for gate in found.gates
        ],
        warnings=[
            AgentPublishWarning(code=warning.code, message=warning.message)
            for warning in found.warnings
        ],
        next_action=found.next_action,
        can_submit=found.can_submit,
        can_approve=found.can_approve,
        version=found.version,
    )


@router.post("/submit", summary="Send for approval")
async def submit(
    agent_id: uuid.UUID,
    body: AgentPublishRequest,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Both gates are checked here too.

    Sending something into an approval queue that cannot be approved wastes the approver's time
    and teaches people to ignore the queue.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="agent.submit",
        payload={"agent_id": str(agent_id), **body.model_dump()},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        agent = await publish_service.submit(
            session, context, agent_id, body.expected_version
        )
        result = {"id": str(agent.id), "version": str(agent.version), "status": agent.status}
        execution.complete_json(status_code=status.HTTP_200_OK, body=result)
        return result


@router.post("/withdraw", summary="Take it back out of the queue")
async def withdraw(
    agent_id: uuid.UUID,
    body: AgentPublishRequest,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """The submitter is cleared, so the next submission is judged on its own."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="agent.withdraw",
        payload={"agent_id": str(agent_id), **body.model_dump()},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        agent = await publish_service.withdraw(
            session, context, agent_id, body.expected_version
        )
        result = {"id": str(agent.id), "version": str(agent.version), "status": agent.status}
        execution.complete_json(status_code=status.HTTP_200_OK, body=result)
        return result


@router.post("/publish", summary="Approve and publish")
async def publish(
    agent_id: uuid.UUID,
    body: AgentPublishRequest,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Approve it, and freeze the design that was approved.

    The gates are re-checked here, not only at submission: a test result can be cleared by an edit
    between the two, and a publish that trusted the earlier check would approve a design nobody
    tested.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="agent.publish",
        payload={"agent_id": str(agent_id), **body.model_dump()},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        version = await publish_service.publish(
            session, context, agent_id, body.expected_version
        )
        result = {
            "version_id": str(version.id),
            "version_no": str(version.version_no),
            "agent_id": str(agent_id),
        }
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.get("/versions", summary="What has been published")
async def versions(
    agent_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> AgentVersionList:
    """Newest first. Gapless numbers — version 3 with no version 2 would be unaccountable."""
    from sqlalchemy import select

    rows = await publish_service.versions(session, context, agent_id)
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

    return AgentVersionList(
        versions=[
            AgentVersionCard(
                id=row.id,
                version_no=row.version_no,
                name=row.name,
                job_version_id=row.job_version_id,
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
                published_at=row.published_at,
            )
            for row in rows
        ],
        is_empty=not rows,
    )
