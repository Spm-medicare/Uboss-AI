"""The privacy routes — the register, the notices, consent, holds and rights requests.

Two audiences under one prefix. A **person** reaches `/privacy/consents` and `/privacy/requests` for
their own; an **administrator** reaches the register, the notices, the holds and everybody's
requests. The service decides which is which — every function checks its own permission, and none of
these routes decides on its own.

Every mutating route carries an `Idempotency-Key`, and every state transition an `expected_version`.
Two routes additionally need a proved password, and both are in the service rather than in a route
dependency so a future caller cannot skip them: putting a notice in force, and deciding somebody's
rights request.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.identity.models import Membership
from uboss.modules.privacy import requests as rights
from uboss.modules.privacy import service as privacy
from uboss.modules.privacy.models import (
    ConsentRecord,
    ConsentState,
    DataPrincipalRequest,
    LegalHold,
    NoticeState,
    PrivacyNotice,
    PrivacyNoticeVersion,
    ProcessingBasis,
    ProcessingRole,
    RequestAction,
    RequestDecision,
    RequestKind,
    RequestState,
)
from uboss.modules.privacy.schemas import (
    Acknowledge,
    ActionRead,
    ActivityCreate,
    ActivityRead,
    ActivityUpdate,
    CloseRequest,
    ConsentGrant,
    ConsentRead,
    ConsentWithdraw,
    Decide,
    DeliveryNote,
    DiscoveryNote,
    EscalateRequest,
    ExemptionReview,
    HoldCreate,
    HoldRead,
    HoldRelease,
    IdentityCheck,
    NoticeCreate,
    NoticeRead,
    NoticeVersionRead,
    NoticeVersionWrite,
    RequestDetail,
    RequestRead,
    RequestSubmit,
)

router = APIRouter(prefix="/privacy", tags=["privacy"])


async def _names(
    session: AsyncSession, ids: set[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    """Display names for a set of memberships, in one query.

    One query rather than one per row: a register of forty activities would otherwise be forty
    round trips for the owner column alone.
    """
    wanted = {one for one in ids if one is not None}
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(Membership.id, Membership.display_name).where(Membership.id.in_(wanted))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


# ── §2 the register ────────────────────────────────────────────────────────────────────────


@router.get("/activities", summary="The processing register")
async def list_activities(
    session: SessionDep,
    context: CurrentContext,
    include_archived: Annotated[bool, Query()] = False,
) -> list[ActivityRead]:
    """§2's inventory, soonest review first."""
    rows = await privacy.list_activities(session, context, include_archived=include_archived)
    names = await _names(session, {row.owner_membership_id for row in rows})
    return [
        ActivityRead(
            id=row.id,
            name=row.name,
            purpose=row.purpose,
            accountable_role=ProcessingRole(row.accountable_role),
            basis=ProcessingBasis(row.basis),
            principal_category=row.principal_category,
            data_categories=row.data_categories,
            source=row.source,
            recipients=row.recipients,
            ai_access=row.ai_access,
            region=row.region,
            transfer_rule=row.transfer_rule,
            retention_summary=row.retention_summary,
            deletion_path=row.deletion_path,
            owner_name=names.get(row.owner_membership_id) if row.owner_membership_id else None,
            effective_from=row.effective_from,
            review_due=row.review_due,
            evidence_note=row.evidence_note,
            archived_at=row.archived_at,
            version=row.version,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.post("/activities", status_code=201, summary="Record a processing activity")
async def create_activity(
    body: ActivityCreate,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.activity_create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        activity = await privacy.create_activity(
            session,
            context,
            name=body.name,
            purpose=body.purpose,
            accountable_role=body.accountable_role,
            basis=body.basis,
            principal_category=body.principal_category,
            data_categories=body.data_categories,
            source=body.source,
            recipients=body.recipients,
            ai_access=body.ai_access,
            region=body.region,
            transfer_rule=body.transfer_rule,
            retention_summary=body.retention_summary,
            deletion_path=body.deletion_path,
            owner_membership_id=body.owner_membership_id,
            effective_from=body.effective_from,
            review_due=body.review_due,
            evidence_note=body.evidence_note,
        )
        result = {"id": str(activity.id), "version": str(activity.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.patch("/activities/{activity_id}", summary="Correct a register entry")
async def update_activity(
    activity_id: uuid.UUID,
    body: ActivityUpdate,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.activity_update",
        payload={"activity_id": str(activity_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        activity = await privacy.update_activity(
            session,
            context,
            activity_id,
            expected_version=body.expected_version,
            changes=body.model_dump(exclude={"expected_version"}, exclude_unset=True),
        )
        result = {"id": str(activity.id), "version": str(activity.version)}
        execution.complete_json(status_code=status.HTTP_200_OK, body=result)
        return result


@router.post("/activities/{activity_id}/archive", summary="Archive a register entry")
async def archive_activity(
    activity_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Query()] = 1,
) -> dict[str, str]:
    """Archived, never deleted: consent records point at it."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.activity_archive",
        payload={"activity_id": str(activity_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        activity = await privacy.archive_activity(
            session, context, activity_id, expected_version=expected_version
        )
        result = {"id": str(activity.id), "version": str(activity.version)}
        execution.complete_json(status_code=status.HTTP_200_OK, body=result)
        return result


# ── §3 notices ─────────────────────────────────────────────────────────────────────────────


async def _version_read(
    session: AsyncSession, version: PrivacyNoticeVersion
) -> NoticeVersionRead:
    names = await _names(
        session, {version.author_membership_id, version.reviewed_by_membership_id}
    )
    return NoticeVersionRead(
        id=version.id,
        notice_id=version.notice_id,
        version_no=version.version_no,
        language=version.language,
        state=NoticeState(version.state),
        body=version.body,
        data_items=version.data_items,
        purpose=version.purpose,
        basis=ProcessingBasis(version.basis),
        recipients=version.recipients,
        retention_summary=version.retention_summary,
        rights_route=version.rights_route,
        privacy_contact=version.privacy_contact,
        author_name=(
            names.get(version.author_membership_id) if version.author_membership_id else None
        ),
        reviewed_by_name=(
            names.get(version.reviewed_by_membership_id)
            if version.reviewed_by_membership_id
            else None
        ),
        effective_from=version.effective_from,
        retired_at=version.retired_at,
        created_at=version.created_at,
    )


@router.get("/notices", summary="Privacy notices and their versions")
async def list_notices(session: SessionDep, context: CurrentContext) -> list[NoticeRead]:
    """Every notice with every version — the history is the point of a versioned notice."""
    await privacy.list_activities(session, context)  # the same `view` check, one place
    notices = list(
        (
            await session.execute(
                select(PrivacyNotice)
                .where(
                    PrivacyNotice.tenant_id == context.tenant_id,
                    PrivacyNotice.archived_at.is_(None),
                )
                .order_by(PrivacyNotice.name)
            )
        )
        .scalars()
        .all()
    )
    versions = list(
        (
            await session.execute(
                select(PrivacyNoticeVersion)
                .where(PrivacyNoticeVersion.tenant_id == context.tenant_id)
                .order_by(
                    PrivacyNoticeVersion.language, PrivacyNoticeVersion.version_no.desc()
                )
            )
        )
        .scalars()
        .all()
    )

    read: list[NoticeRead] = []
    for notice in notices:
        read.append(
            NoticeRead(
                id=notice.id,
                name=notice.name,
                processing_activity_id=notice.processing_activity_id,
                version=notice.version,
                versions=[
                    await _version_read(session, version)
                    for version in versions
                    if version.notice_id == notice.id
                ],
            )
        )
    return read


@router.post("/notices", status_code=201, summary="Start a privacy notice")
async def create_notice(
    body: NoticeCreate,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.notice_create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        notice = await privacy.create_notice(
            session,
            context,
            name=body.name,
            processing_activity_id=body.processing_activity_id,
        )
        result = {"id": str(notice.id)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.post("/notices/{notice_id}/versions", status_code=201, summary="Write a new version")
async def draft_version(
    notice_id: uuid.UUID,
    body: NoticeVersionWrite,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> NoticeVersionRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.notice_version",
        payload={"notice_id": str(notice_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return NoticeVersionRead.model_validate(execution.replay_body)

        version = await privacy.draft_version(
            session,
            context,
            notice_id,
            language=body.language,
            body=body.body,
            data_items=body.data_items,
            purpose=body.purpose,
            basis=body.basis,
            rights_route=body.rights_route,
            privacy_contact=body.privacy_contact,
            recipients=body.recipients,
            retention_summary=body.retention_summary,
        )
        result = await _version_read(session, version)
        execution.complete_json(
            status_code=status.HTTP_201_CREATED, body=result.model_dump(mode="json")
        )
        return result


@router.post("/notice-versions/{version_id}/review", summary="Send a draft for review")
async def send_for_review(
    version_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> NoticeVersionRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.notice_review",
        payload={"version_id": str(version_id)},
    ) as execution:
        if execution.is_replay:
            return NoticeVersionRead.model_validate(execution.replay_body)

        version = await privacy.send_for_review(session, context, version_id)
        result = await _version_read(session, version)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/notice-versions/{version_id}/effective", summary="Put a notice in force")
async def make_effective(
    version_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> NoticeVersionRead:
    """Approved by somebody other than its author, with a proved password.

    Both checks are in the service, so an import or a future bulk tool meets the same rule.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.notice_effective",
        payload={"version_id": str(version_id)},
    ) as execution:
        if execution.is_replay:
            return NoticeVersionRead.model_validate(execution.replay_body)

        version = await privacy.make_effective(session, context, version_id)
        result = await _version_read(session, version)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.get("/notices/{notice_id}/effective", summary="The version in force now")
async def effective_version(
    notice_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    language: Annotated[str, Query(max_length=16)] = "en",
) -> NoticeVersionRead | None:
    """`null` when nothing is in force. A workspace that has not approved a notice has not."""
    version = await privacy.effective_notice(session, context, notice_id, language=language)
    return await _version_read(session, version) if version is not None else None


# ── §3 consent ─────────────────────────────────────────────────────────────────────────────


async def _consent_read(session: AsyncSession, row: ConsentRecord) -> ConsentRead:
    names = await _names(session, {row.recorded_by_membership_id})
    return ConsentRead(
        id=row.id,
        state=ConsentState(row.state),
        purpose=row.purpose,
        channel=row.channel,
        evidence=row.evidence,
        language=row.language,
        notice_version_id=row.notice_version_id,
        withdraws_id=row.withdraws_id,
        expires_at=row.expires_at,
        occurred_at=row.occurred_at,
        recorded_by_name=(
            names.get(row.recorded_by_membership_id) if row.recorded_by_membership_id else None
        ),
    )


@router.get("/consents", summary="One person's consent history")
async def consent_history(
    session: SessionDep,
    context: CurrentContext,
    membership_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ConsentRead]:
    """Your own by default. Somebody else's needs `administer`.

    The history rather than a current state: *"do they consent"* is answered by reading the events,
    and one flag would be the answer that hides the withdrawal.
    """
    rows = await privacy.consent_history(session, context, membership_id=membership_id)
    return [await _consent_read(session, row) for row in rows]


@router.post("/consents", status_code=201, summary="Record a consent")
async def grant_consent(
    body: ConsentGrant,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ConsentRead:
    """Only against a notice in force, and only where consent is the basis."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.consent_grant",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return ConsentRead.model_validate(execution.replay_body)

        record = await privacy.grant_consent(
            session,
            context,
            notice_version_id=body.notice_version_id,
            purpose=body.purpose,
            channel=body.channel,
            evidence=body.evidence,
            membership_id=body.membership_id,
            principal_email=body.principal_email,
            processing_activity_id=body.processing_activity_id,
            expires_at=body.expires_at,
        )
        result = await _consent_read(session, record)
        execution.complete_json(
            status_code=status.HTTP_201_CREATED, body=result.model_dump(mode="json")
        )
        return result


@router.post("/consents/{consent_id}/withdraw", summary="Withdraw a consent")
async def withdraw_consent(
    consent_id: uuid.UUID,
    body: ConsentWithdraw,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ConsentRead:
    """A new row pointing at the grant — §3's *"immutable evidence"*, both ways."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.consent_withdraw",
        payload={"consent_id": str(consent_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return ConsentRead.model_validate(execution.replay_body)

        record = await privacy.withdraw_consent(
            session, context, consent_id, channel=body.channel, evidence=body.evidence
        )
        result = await _consent_read(session, record)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


# ── §5 legal holds ─────────────────────────────────────────────────────────────────────────


async def _hold_read(session: AsyncSession, row: LegalHold) -> HoldRead:
    names = await _names(session, {row.placed_by_membership_id, row.released_by_membership_id})
    return HoldRead(
        id=row.id,
        name=row.name,
        scope=row.scope,
        reason=row.reason,
        authority=row.authority,
        placed_by_name=(
            names.get(row.placed_by_membership_id) if row.placed_by_membership_id else None
        ),
        placed_at=row.placed_at,
        released_at=row.released_at,
        released_by_name=(
            names.get(row.released_by_membership_id) if row.released_by_membership_id else None
        ),
        release_reason=row.release_reason,
        version=row.version,
    )


@router.get("/holds", summary="Legal holds in force")
async def list_holds(session: SessionDep, context: CurrentContext) -> list[HoldRead]:
    rows = await privacy.active_holds(session, context)
    return [await _hold_read(session, row) for row in rows]


@router.post("/holds", status_code=201, summary="Place a legal hold")
async def place_hold(
    body: HoldCreate,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> HoldRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.hold_place",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return HoldRead.model_validate(execution.replay_body)

        hold = await privacy.place_hold(
            session,
            context,
            name=body.name,
            scope=body.scope,
            reason=body.reason,
            authority=body.authority,
        )
        result = await _hold_read(session, hold)
        execution.complete_json(
            status_code=status.HTTP_201_CREATED, body=result.model_dump(mode="json")
        )
        return result


@router.post("/holds/{hold_id}/release", summary="Release a legal hold")
async def release_hold(
    hold_id: uuid.UUID,
    body: HoldRelease,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> HoldRead:
    """With a reason. A hold released with no explanation is an unauthorised deletion."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.hold_release",
        payload={"hold_id": str(hold_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return HoldRead.model_validate(execution.replay_body)

        hold = await privacy.release_hold(
            session, context, hold_id, expected_version=body.expected_version, reason=body.reason
        )
        result = await _hold_read(session, hold)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


# ── §4 rights requests ─────────────────────────────────────────────────────────────────────


async def _request_read(
    session: AsyncSession, row: DataPrincipalRequest
) -> RequestRead:
    names = await _names(
        session,
        {
            row.requested_by_membership_id,
            row.assigned_to_membership_id,
            row.decided_by_membership_id,
        },
    )
    return RequestRead(
        id=row.id,
        reference=row.reference,
        kind=RequestKind(row.kind),
        state=RequestState(row.state),
        principal_email=row.principal_email,
        details=row.details,
        requested_by_name=(
            names.get(row.requested_by_membership_id)
            if row.requested_by_membership_id
            else None
        ),
        identity_check=row.identity_check,
        verified_at=row.verified_at,
        assigned_to_name=(
            names.get(row.assigned_to_membership_id) if row.assigned_to_membership_id else None
        ),
        due_at=row.due_at,
        decision=RequestDecision(row.decision) if row.decision else None,
        decision_reason=row.decision_reason,
        decided_by_name=(
            names.get(row.decided_by_membership_id) if row.decided_by_membership_id else None
        ),
        decided_at=row.decided_at,
        legal_hold_id=row.legal_hold_id,
        exemption_note=row.exemption_note,
        delivery_note=row.delivery_note,
        delivered_at=row.delivered_at,
        closed_at=row.closed_at,
        version=row.version,
        created_at=row.created_at,
    )


async def _trail_read(session: AsyncSession, steps: list[RequestAction]) -> list[ActionRead]:
    names = await _names(session, {step.actor_membership_id for step in steps})
    return [
        ActionRead(
            id=step.id,
            kind=step.kind,
            detail=step.detail,
            actor_name=(
                names.get(step.actor_membership_id) if step.actor_membership_id else None
            ),
            occurred_at=step.occurred_at,
        )
        for step in steps
    ]


@router.get("/requests", summary="Rights requests")
async def list_requests(
    session: SessionDep,
    context: CurrentContext,
    mine: Annotated[bool, Query(description="Only my own requests.")] = False,
) -> list[RequestRead]:
    """`mine=true` is what a person sees of their own; everything else needs `administer`."""
    rows = await rights.list_requests(session, context, mine_only=mine)
    return [await _request_read(session, row) for row in rows]


@router.post("/requests", status_code=201, summary="Make a request about your own data")
async def submit_request(
    body: RequestSubmit,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    """Your own needs nothing beyond being signed in. Somebody else's needs `administer`."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_submit",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)

        request = await rights.submit(
            session,
            context,
            kind=body.kind,
            details=body.details,
            principal_email=body.principal_email,
            on_behalf_of_membership_id=body.on_behalf_of_membership_id,
            due_at=body.due_at,
        )
        result = await _request_read(session, request)
        execution.complete_json(
            status_code=status.HTTP_201_CREATED, body=result.model_dump(mode="json")
        )
        return result


@router.get("/requests/{request_id}", summary="One request, with its trail")
async def read_request(
    request_id: uuid.UUID, session: SessionDep, context: CurrentContext
) -> RequestDetail:
    """A person may read their own — §4's process is one somebody can be shown."""
    steps = await rights.trail(session, context, request_id)
    row = (
        await session.execute(
            select(DataPrincipalRequest).where(
                DataPrincipalRequest.tenant_id == context.tenant_id,
                DataPrincipalRequest.id == request_id,
            )
        )
    ).scalar_one()
    base = await _request_read(session, row)
    return RequestDetail(**base.model_dump(), trail=await _trail_read(session, steps))


@router.post("/requests/{request_id}/identity", summary="Record the identity check")
async def record_identity(
    request_id: uuid.UUID,
    body: IdentityCheck,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_identity",
        payload={"request_id": str(request_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)
        row = await rights.record_identity_check(
            session, context, request_id, expected_version=body.expected_version, how=body.how
        )
        result = await _request_read(session, row)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/requests/{request_id}/acknowledge", summary="Acknowledge and assign")
async def acknowledge(
    request_id: uuid.UUID,
    body: Acknowledge,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_acknowledge",
        payload={"request_id": str(request_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)
        row = await rights.acknowledge(
            session,
            context,
            request_id,
            expected_version=body.expected_version,
            assigned_to_membership_id=body.assigned_to_membership_id,
            due_at=body.due_at,
        )
        result = await _request_read(session, row)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/requests/{request_id}/discovery", summary="Record what was searched and found")
async def record_discovery(
    request_id: uuid.UUID,
    body: DiscoveryNote,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_discovery",
        payload={"request_id": str(request_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)
        row = await rights.record_discovery(
            session, context, request_id, expected_version=body.expected_version, found=body.found
        )
        result = await _request_read(session, row)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/requests/{request_id}/exemptions", summary="Record the exemption review")
async def review_exemptions(
    request_id: uuid.UUID,
    body: ExemptionReview,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_exemptions",
        payload={"request_id": str(request_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)
        row = await rights.review_exemptions(
            session,
            context,
            request_id,
            expected_version=body.expected_version,
            note=body.note,
            legal_hold_id=body.legal_hold_id,
        )
        result = await _request_read(session, row)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/requests/{request_id}/decision", summary="Decide the request")
async def decide(
    request_id: uuid.UUID,
    body: Decide,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    """Not by the requester, not unverified, not without a reason, and not over a live hold."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_decide",
        payload={"request_id": str(request_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)
        row = await rights.decide(
            session,
            context,
            request_id,
            expected_version=body.expected_version,
            decision=body.decision,
            reason=body.reason,
        )
        result = await _request_read(session, row)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/requests/{request_id}/delivery", summary="Record what was sent")
async def record_delivery(
    request_id: uuid.UUID,
    body: DeliveryNote,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_delivery",
        payload={"request_id": str(request_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)
        row = await rights.record_delivery(
            session, context, request_id, expected_version=body.expected_version, note=body.note
        )
        result = await _request_read(session, row)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/requests/{request_id}/close", summary="Close a decided request")
async def close_request(
    request_id: uuid.UUID,
    body: CloseRequest,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_close",
        payload={"request_id": str(request_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)
        row = await rights.close(
            session, context, request_id, expected_version=body.expected_version, note=body.note
        )
        result = await _request_read(session, row)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result


@router.post("/requests/{request_id}/escalate", summary="Escalate a request")
async def escalate_request(
    request_id: uuid.UUID,
    body: EscalateRequest,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> RequestRead:
    """Available to the person who asked as well — a grievance route they cannot use is a form."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="privacy.request_escalate",
        payload={"request_id": str(request_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return RequestRead.model_validate(execution.replay_body)
        row = await rights.escalate(
            session, context, request_id, expected_version=body.expected_version, reason=body.reason
        )
        result = await _request_read(session, row)
        execution.complete_json(
            status_code=status.HTTP_200_OK, body=result.model_dump(mode="json")
        )
        return result
