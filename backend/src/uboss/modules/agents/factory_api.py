"""The Skill Factory's routes — under `/skills`, because a private skill is a skill.

`PLAN.md` §39: *"Skill Registry is internal to Agent Builder and is not a sidebar module."* That is
a rule about the interface, not about the API: these hang off the same `/skills` prefix the registry
search and the resolver already use, because what they create is found by that search and gated by
that resolver. A separate `/skill-drafts` prefix would suggest two kinds of skill, and the whole
design is that there is one.

Every mutating route takes an `Idempotency-Key` and every state transition takes an
`expected_version`. Approving additionally requires a recently proved password — it is a
`publish`-class decision, and `HIGH_RISK_ACTIONS` already says so.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.core.permissions import Action
from uboss.modules.agents import factory, factory_publish
from uboss.modules.agents.factory_schemas import (
    DraftCreate,
    DraftListRead,
    DraftRead,
    DraftSummaryRead,
    DraftUpdate,
    SkillTestResultWrite,
    SkillTestWrite,
    SkillVersionRead,
)
from uboss.modules.agents.models import SkillTestKind
from uboss.modules.identity import guard

router = APIRouter(prefix="/skills/drafts", tags=["skills"])


@router.get("", summary="This workspace's own skills")
async def list_drafts(session: SessionDep, context: CurrentContext) -> DraftListRead:
    """Every private skill, whatever state it is in — including archived ones.

    Archived rows are listed and labelled rather than hidden: *"we never had one"* and *"we retired
    it"* are different answers, and somebody about to write a new skill needs the second one.
    """
    await guard.authorise(session, context, Action.VIEW)
    return await factory.list_drafts(session, context)


@router.post("", status_code=201, summary="Start a private skill draft")
async def create_draft(
    body: DraftCreate,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """The other end of the resolver's *Create* route."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.draft_create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        skill = await factory.create(
            session,
            context,
            name=body.name,
            purpose=body.purpose,
            department=body.department,
            industry=body.industry,
            archetype_id=body.archetype_id,
        )
        result = {"id": str(skill.id), "version": str(skill.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.get("/{skill_id}", summary="One private skill, in full")
async def read_draft(
    skill_id: uuid.UUID, session: SessionDep, context: CurrentContext
) -> DraftRead:
    await guard.authorise(session, context, Action.VIEW)
    return await factory.read(session, context, skill_id)


@router.put("/{skill_id}", summary="Save the draft")
async def save_draft(
    skill_id: uuid.UUID,
    body: DraftUpdate,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> DraftRead:
    """Saving clears every test result — see `factory.update`."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.draft_save",
        payload={"skill_id": str(skill_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return DraftRead.model_validate(execution.replay_body)

        await factory.update(
            session,
            context,
            skill_id,
            expected_version=body.expected_version,
            changes=body.model_dump(exclude={"expected_version", "rules"}, exclude_unset=True),
            rules=(
                [rule.model_dump() for rule in body.rules] if body.rules is not None else None
            ),
        )
        result = await factory.read(session, context, skill_id)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.put("/{skill_id}/tests/{kind}", summary="Write one of the six tests")
async def write_test(
    skill_id: uuid.UUID,
    kind: SkillTestKind,
    body: SkillTestWrite,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> DraftRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.test_write",
        payload={"skill_id": str(skill_id), "kind": kind.value, **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return DraftRead.model_validate(execution.replay_body)

        await factory.set_test(
            session,
            context,
            skill_id,
            kind=kind.value,
            sample_situation=body.sample_situation,
            expected_result=body.expected_result,
        )
        result = await factory.read(session, context, skill_id)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/{skill_id}/tests/{kind}/result", summary="Record what a test did")
async def record_result(
    skill_id: uuid.UUID,
    kind: SkillTestKind,
    body: SkillTestResultWrite,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> DraftRead:
    """A person's own account of running it — there is no sandbox runtime for a skill yet."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.test_result",
        payload={"skill_id": str(skill_id), "kind": kind.value, **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return DraftRead.model_validate(execution.replay_body)

        await factory.record_result(
            session,
            context,
            skill_id,
            kind=kind.value,
            status=body.status.value,
            observed=body.observed,
        )
        result = await factory.read(session, context, skill_id)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.get("/{skill_id}/summary", summary="What this draft is waiting for")
async def read_summary(
    skill_id: uuid.UUID, session: SessionDep, context: CurrentContext
) -> DraftSummaryRead:
    """`can_submit` and `can_approve` are answered here, so the screen does not answer them
    twice."""
    await guard.authorise(session, context, Action.VIEW)
    return DraftSummaryRead.of(await factory_publish.summary(session, context, skill_id))


@router.put("/{skill_id}/approver", summary="Name who approves it")
async def set_approver(
    skill_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    approver_membership_id: Annotated[uuid.UUID, Body(embed=True)],
    expected_version: Annotated[int, Body(embed=True)] = 1,
) -> DraftSummaryRead:
    """A person, never a role — `can_approve` compares the named approver to the signed-in one."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.approver_named",
        payload={
            "skill_id": str(skill_id),
            "approver_membership_id": str(approver_membership_id),
            "expected_version": expected_version,
        },
    ) as execution:
        if execution.is_replay:
            return DraftSummaryRead.model_validate(execution.replay_body)

        await factory_publish.set_approver(
            session,
            context,
            skill_id,
            approver_membership_id,
            expected_version=expected_version,
        )
        result = DraftSummaryRead.of(await factory_publish.summary(session, context, skill_id))
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/{skill_id}/submit", summary="Send it for approval")
async def submit(
    skill_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True)] = 1,
) -> DraftSummaryRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.submit",
        payload={"skill_id": str(skill_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return DraftSummaryRead.model_validate(execution.replay_body)

        await factory_publish.submit(
            session, context, skill_id, expected_version=expected_version
        )
        result = DraftSummaryRead.of(await factory_publish.summary(session, context, skill_id))
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/{skill_id}/withdraw", summary="Take it back for more work")
async def withdraw(
    skill_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True)] = 1,
) -> DraftSummaryRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.withdraw",
        payload={"skill_id": str(skill_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return DraftSummaryRead.model_validate(execution.replay_body)

        await factory_publish.withdraw(
            session, context, skill_id, expected_version=expected_version
        )
        result = DraftSummaryRead.of(await factory_publish.summary(session, context, skill_id))
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/{skill_id}/approve", summary="Approve it and freeze the version")
async def approve(
    skill_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True)] = 1,
) -> SkillVersionRead:
    """§39: *"Skills cannot self-publish."* Four checks, and a proved password.

    Step-up is checked inside `factory_publish.approve` rather than by a route dependency, so the
    same rule holds for any future caller — an import, a bulk tool — that does not come through
    this route.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.approve",
        payload={"skill_id": str(skill_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return SkillVersionRead.model_validate(execution.replay_body)

        version = await factory_publish.approve(
            session, context, skill_id, expected_version=expected_version
        )
        result = SkillVersionRead(
            id=version.id,
            skill_id=version.skill_id,
            version_no=version.version_no,
            name=version.name,
            published_at=version.published_at,
        )
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/{skill_id}/archive", summary="Take it out of use")
async def archive(
    skill_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True)] = 1,
) -> DraftSummaryRead:
    """Archived, never deleted. A skill a resolution selected is part of why something happened."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.archive",
        payload={"skill_id": str(skill_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return DraftSummaryRead.model_validate(execution.replay_body)

        await factory_publish.archive(
            session, context, skill_id, expected_version=expected_version
        )
        result = DraftSummaryRead.of(await factory_publish.summary(session, context, skill_id))
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result
