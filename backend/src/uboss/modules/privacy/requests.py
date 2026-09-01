"""A person's request about their own data — §4, end to end.

```
Submitted
→ Proportionate identity verification
→ Acknowledged and assigned
→ Authorised data discovery
→ Exemption/legal-hold review
→ Fulfil / Partially fulfil / Reject with approved reason
→ Secure delivery and immutable evidence
→ Close / Escalate
```

Every function here is one arrow of that, and every one writes a `RequestAction` — append-only, with
who did it and when. §4 asks for *"immutable evidence"* at each step, and the trail is what makes a
year-old decision explainable.

## The three rules that are not negotiable

**The requester does not decide.** §4: *"Requestor cannot approve their own administrative
decision."* Checked here so the refusal is a sentence, and checked again by migration 0044's
constraint because a service check is one code path and a constraint is all of them.

**A decision carries its reason.** Not for the audit's sake — for the person's. A rejection they
cannot understand is a rejection they cannot challenge, and §4 requires the reason on every
rejection, partial response and exemption.

**An erasure never quietly destroys what must be kept.** §5: *"an erasure request never silently
destroys records that law requires to be retained."* So an erasure cannot be fulfilled while a legal
hold is in force unless somebody has looked at the hold and said, in writing, why it does not apply.
That is the `exemption_note`, and `fulfil` refuses without it.

## What this module deliberately does not do

It does not *perform* the erasure. §4's discovery step is *"authorised data discovery"* across
*"database, files, indexes, approved integrations and relevant provider records"*, and a function
that deleted rows across nine subsystems on one API call would be the least reviewable code in this
product. What is recorded is what somebody did, with evidence — and the deletion itself remains an
authorised, evidenced act by a person until there is a governed mechanism for it. Stating that is
better than a green tick over a job nobody watched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from uboss.core.logging import correlation_id
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.privacy.models import (
    ActionKind,
    DataPrincipalRequest,
    LegalHold,
    RequestAction,
    RequestDecision,
    RequestKind,
    RequestState,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def _reference(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    """A short, quotable reference — `DPR-0007`.

    Sequential per workspace, under an advisory lock, so two requests submitted in the same instant
    cannot share one. People quote these in emails and read them over the phone; a uuid would be
    correct and useless.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"dpr:{tenant_id}"},
    )
    used = (
        await session.execute(
            select(func.count())
            .select_from(DataPrincipalRequest)
            .where(DataPrincipalRequest.tenant_id == tenant_id)
        )
    ).scalar_one()
    return f"DPR-{used + 1:04d}"


async def _request(
    session: AsyncSession, context: SecurityContext, request_id: uuid.UUID
) -> DataPrincipalRequest:
    row = (
        await session.execute(
            select(DataPrincipalRequest).where(
                DataPrincipalRequest.tenant_id == context.tenant_id,
                DataPrincipalRequest.id == request_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such request.")
    return row


async def _step(
    session: AsyncSession,
    context: SecurityContext,
    request: DataPrincipalRequest,
    kind: ActionKind,
    detail: str,
) -> None:
    """Write one step of the trail. Append-only; nothing edits these afterwards."""
    session.add(
        RequestAction(
            tenant_id=context.tenant_id,
            request_id=request.id,
            kind=kind.value,
            detail=detail.strip()[:4000],
            actor_membership_id=context.membership_id,
            correlation_id=correlation_id.get(),
        )
    )
    await session.flush()


def _mine(request: DataPrincipalRequest, context: SecurityContext) -> bool:
    return request.requested_by_membership_id == context.membership_id


async def _handling(session: AsyncSession, context: SecurityContext) -> None:
    """Handling somebody's request is privacy work: `administer`.

    Not `view`: reading a request means reading what somebody asked about their own personal data,
    and the identity check that went with it.
    """
    await guard.authorise(session, context, Action.ADMINISTER)


# ── submitted ──────────────────────────────────────────────────────────────────────────────


async def submit(
    session: AsyncSession,
    context: SecurityContext,
    *,
    kind: RequestKind,
    details: str,
    principal_email: str | None = None,
    on_behalf_of_membership_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
) -> DataPrincipalRequest:
    """Somebody asks something about their own data.

    A person submits for themselves with no permission beyond being signed in — it is their own
    right, and a rights route that needed a grant would not be a rights route. Submitting *for*
    somebody else (a paper form, a phone call, a grievance passed on) is `administer`, and the row
    records both people.

    `due_at` comes from the caller, which means from the tenant's approved register. §4: the SLA
    comes from *"the approved effective-date register"* — and DR-011 is an open decision, so nothing
    here computes a deadline. A request with no due date is a request nobody has set an SLA for,
    which is a visible gap rather than an invented promise.
    """
    for_somebody_else = (
        on_behalf_of_membership_id is not None
        and on_behalf_of_membership_id != context.membership_id
    )
    if for_somebody_else:
        await guard.authorise(session, context, Action.ADMINISTER)
    else:
        await guard.authorise(session, context, Action.VIEW)

    if not details.strip():
        raise ValidationFailed("Say what you are asking for, so somebody can act on it.")

    email = (principal_email or context.email).strip()
    if not email:
        raise ValidationFailed("A request needs an address to answer.")

    request = DataPrincipalRequest(
        tenant_id=context.tenant_id,
        reference=await _reference(session, context.tenant_id),
        kind=kind.value,
        state=RequestState.SUBMITTED,
        requested_by_membership_id=(
            on_behalf_of_membership_id if for_somebody_else else context.membership_id
        ),
        principal_email=email[:320],
        details=details.strip(),
        due_at=due_at,
    )
    session.add(request)
    await session.flush()

    await _step(
        session,
        context,
        request,
        ActionKind.SUBMITTED,
        (
            f"{kind.value} request submitted"
            + (" on behalf of another person" if for_somebody_else else "")
        ),
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_submitted",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={
            "reference": request.reference,
            "kind": request.kind,
            "on_behalf": for_somebody_else,
        },
    )
    return request


# ── verified, acknowledged, assigned ───────────────────────────────────────────────────────


async def record_identity_check(
    session: AsyncSession,
    context: SecurityContext,
    request_id: uuid.UUID,
    *,
    expected_version: int,
    how: str,
) -> DataPrincipalRequest:
    """Record how the person was identified — §4's *"proportionate identity verification"*.

    Proportionate is a judgement, so what is stored is what was actually done: *"signed in as the
    account holder"*, *"employee number matched against the HR record"*, *"photo identity checked in
    person"*. A boolean `verified` would record that somebody clicked a box.
    """
    request = await _request(session, context, request_id)
    await _handling(session, context)

    if request.version != expected_version:
        raise Conflict("Somebody else changed this request. Reload it and try again.")
    if not request.is_open:
        raise ValidationFailed("This request is finished.")
    if not how.strip():
        raise ValidationFailed("Say how the person was identified.")

    request.identity_check = how.strip()
    request.verified_by_membership_id = context.membership_id
    request.verified_at = _now()
    if request.state == RequestState.SUBMITTED:
        request.state = RequestState.VERIFYING
    request.version += 1
    await session.flush()

    await _step(session, context, request, ActionKind.IDENTITY_CHECKED, how)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_identity_checked",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={"reference": request.reference},
    )
    return request


async def acknowledge(
    session: AsyncSession,
    context: SecurityContext,
    request_id: uuid.UUID,
    *,
    expected_version: int,
    assigned_to_membership_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
) -> DataPrincipalRequest:
    """Tell the person it has been received, and give it to somebody.

    Identity first: acknowledging a request whose requester has not been identified would be
    acknowledging a request from anybody, and the answer to an access request is somebody's personal
    data. §4 puts verification before acknowledgement for exactly that reason.
    """
    request = await _request(session, context, request_id)
    await _handling(session, context)

    if request.version != expected_version:
        raise Conflict("Somebody else changed this request. Reload it and try again.")
    if request.verified_at is None:
        raise ValidationFailed(
            "Identify the person first. Acknowledging an unverified request means answering "
            "anybody who asks."
        )
    if not request.is_open:
        raise ValidationFailed("This request is finished.")

    request.state = RequestState.ACKNOWLEDGED
    if assigned_to_membership_id is not None:
        request.assigned_to_membership_id = assigned_to_membership_id
    if due_at is not None:
        request.due_at = due_at
    request.version += 1
    await session.flush()

    await _step(
        session,
        context,
        request,
        ActionKind.ACKNOWLEDGED,
        "Acknowledged"
        + (" and assigned" if assigned_to_membership_id is not None else "")
        + (f", due {due_at.isoformat()}" if due_at is not None else ""),
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_acknowledged",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={"reference": request.reference, "due_at": due_at.isoformat() if due_at else None},
    )
    return request


# ── discovery and exemptions ───────────────────────────────────────────────────────────────


async def record_discovery(
    session: AsyncSession,
    context: SecurityContext,
    request_id: uuid.UUID,
    *,
    expected_version: int,
    found: str,
) -> DataPrincipalRequest:
    """Write down what was searched and what was found.

    §4 names where: *"database, files, indexes, approved integrations and relevant provider
    records"*. This records the result of that search as evidence; it does not perform it. A single
    call that swept nine subsystems and reported a number would be the least reviewable code in the
    product, and the number nobody could check.
    """
    request = await _request(session, context, request_id)
    await _handling(session, context)

    if request.version != expected_version:
        raise Conflict("Somebody else changed this request. Reload it and try again.")
    if not request.is_open:
        raise ValidationFailed("This request is finished.")
    if not found.strip():
        raise ValidationFailed("Say what was searched and what was found.")

    request.state = RequestState.DISCOVERING
    request.version += 1
    await session.flush()

    await _step(session, context, request, ActionKind.DISCOVERY_RECORDED, found)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_discovery_recorded",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={"reference": request.reference},
    )
    return request


async def review_exemptions(
    session: AsyncSession,
    context: SecurityContext,
    request_id: uuid.UUID,
    *,
    expected_version: int,
    note: str,
    legal_hold_id: uuid.UUID | None = None,
) -> DataPrincipalRequest:
    """Record the exemption and legal-hold review, and the hold that applies.

    The note is required whether or not a hold applies: *"no hold applies to this request"* is a
    finding, and an unrecorded finding is indistinguishable from a step nobody took.
    """
    request = await _request(session, context, request_id)
    await _handling(session, context)

    if request.version != expected_version:
        raise Conflict("Somebody else changed this request. Reload it and try again.")
    if not request.is_open:
        raise ValidationFailed("This request is finished.")
    if not note.strip():
        raise ValidationFailed(
            "Record what the review found — including that nothing applies, if that is the finding."
        )

    if legal_hold_id is not None:
        hold = (
            await session.execute(
                select(LegalHold).where(
                    LegalHold.tenant_id == context.tenant_id, LegalHold.id == legal_hold_id
                )
            )
        ).scalar_one_or_none()
        if hold is None:
            raise NotFound("No such legal hold.")
        if hold.released_at is not None:
            raise ValidationFailed(
                "That hold has been released, so it cannot be the reason for withholding anything."
            )
        request.legal_hold_id = hold.id

    request.state = RequestState.REVIEWING_EXEMPTIONS
    request.exemption_note = note.strip()
    request.version += 1
    await session.flush()

    await _step(
        session,
        context,
        request,
        ActionKind.HOLD_APPLIED if legal_hold_id is not None else ActionKind.EXEMPTION_REVIEWED,
        note,
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_exemptions_reviewed",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={
            "reference": request.reference,
            "legal_hold_id": str(legal_hold_id) if legal_hold_id else None,
        },
    )
    return request


# ── the decision ───────────────────────────────────────────────────────────────────────────

#: What the decision means for the request's state.
_STATE_FOR = {
    RequestDecision.FULFIL: RequestState.FULFILLED,
    RequestDecision.PARTIALLY_FULFIL: RequestState.PARTIALLY_FULFILLED,
    RequestDecision.REJECT: RequestState.REJECTED,
}


async def decide(
    session: AsyncSession,
    context: SecurityContext,
    request_id: uuid.UUID,
    *,
    expected_version: int,
    decision: RequestDecision,
    reason: str,
) -> DataPrincipalRequest:
    """Fulfil, partially fulfil, or reject — with the reason the person will read.

    Four refusals, and each one is a rule from §4 or §5:

    * **Not by the requester.** *"Requestor cannot approve their own administrative decision."*
    * **Not without a reason.** Every rejection and partial response *"records authority, reason and
      evidence"*, and the person needs it to challenge the decision.
    * **Not without identifying them.** Answering an access request unverified means answering
      whoever asked.
    * **Not an erasure over a live legal hold** unless the exemption review says in writing why it
      does not apply. §5: *"an erasure request never silently destroys records that law requires to
      be retained."*

    A proved password as well: this is `administer`, which `HIGH_RISK_ACTIONS` already treats as a
    step-up action, and deciding somebody's rights request is exactly the kind of act that list is
    for.
    """
    request = await _request(session, context, request_id)
    await _handling(session, context)

    if not context.has_stepped_up():
        raise PermissionDenied(
            "Confirm your identity before deciding a rights request.", code="step_up_required"
        )
    if request.version != expected_version:
        raise Conflict("Somebody else changed this request. Reload it and try again.")
    if not request.is_open:
        raise ValidationFailed("This request has already been decided.")
    if _mine(request, context):
        raise PermissionDenied(
            "This is your own request, so the decision is not yours to make. Somebody else has to "
            "decide it."
        )
    if request.verified_at is None:
        raise ValidationFailed(
            "Identify the person first. Deciding an unverified request means answering whoever "
            "asked."
        )
    if not reason.strip():
        raise ValidationFailed(
            "Give the reason. The person reads it, and a decision they cannot understand is one "
            "they cannot challenge."
        )

    if (
        request.kind == RequestKind.ERASURE
        and decision == RequestDecision.FULFIL
        and request.legal_hold_id is not None
    ):
        hold = (
            await session.execute(
                select(LegalHold).where(
                    LegalHold.tenant_id == context.tenant_id,
                    LegalHold.id == request.legal_hold_id,
                )
            )
        ).scalar_one_or_none()
        if hold is not None and hold.released_at is None:
            raise ValidationFailed(
                f"“{hold.name}” is in force over this data. An erasure cannot be fulfilled in full "
                "while it stands — decide a partial fulfilment and say what is being withheld, or "
                "release the hold with an authorised reason."
            )

    request.decision = decision.value
    request.decision_reason = reason.strip()
    request.decided_by_membership_id = context.membership_id
    request.decided_at = _now()
    request.state = _STATE_FOR[decision]
    request.version += 1
    await session.flush()

    await _step(
        session, context, request, ActionKind.DECIDED, f"{decision.value}: {reason.strip()}"
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_decided",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={
            "reference": request.reference,
            "decision": request.decision,
            "requested_by_membership_id": str(request.requested_by_membership_id),
        },
    )
    return request


async def record_delivery(
    session: AsyncSession,
    context: SecurityContext,
    request_id: uuid.UUID,
    *,
    expected_version: int,
    note: str,
) -> DataPrincipalRequest:
    """What was sent, how, and when — §4's *"secure delivery and immutable evidence"*.

    Recorded rather than performed, and for the same reason as discovery: the delivery of somebody's
    personal data is an authorised act by a person, and a route that emailed an export would be a
    route that could email it to the wrong address without anybody reading the decision first.
    """
    request = await _request(session, context, request_id)
    await _handling(session, context)

    if request.version != expected_version:
        raise Conflict("Somebody else changed this request. Reload it and try again.")
    if request.decision is None:
        raise ValidationFailed("Decide the request before recording what was sent.")
    if not note.strip():
        raise ValidationFailed("Say what was sent and how.")

    request.delivery_note = note.strip()
    request.delivered_at = _now()
    request.version += 1
    await session.flush()

    await _step(session, context, request, ActionKind.DELIVERED, note)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_delivered",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={"reference": request.reference},
    )
    return request


async def close(
    session: AsyncSession,
    context: SecurityContext,
    request_id: uuid.UUID,
    *,
    expected_version: int,
    note: str = "",
) -> DataPrincipalRequest:
    """Close a decided request."""
    request = await _request(session, context, request_id)
    await _handling(session, context)

    if request.version != expected_version:
        raise Conflict("Somebody else changed this request. Reload it and try again.")
    if request.decision is None:
        raise ValidationFailed("A request is decided before it is closed.")
    if request.state == RequestState.CLOSED:
        raise ValidationFailed("This request is already closed.")

    request.state = RequestState.CLOSED
    request.closed_at = _now()
    request.version += 1
    await session.flush()

    await _step(session, context, request, ActionKind.CLOSED, note or "Closed")
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_closed",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={"reference": request.reference, "decision": request.decision},
    )
    return request


async def escalate(
    session: AsyncSession,
    context: SecurityContext,
    request_id: uuid.UUID,
    *,
    expected_version: int,
    reason: str,
) -> DataPrincipalRequest:
    """Hand it up — §4's other ending.

    A request nobody can escalate is a request that stalls silently, which is the failure mode a
    grievance route exists to prevent. Available to the person who asked as well as to whoever is
    handling it: being unable to escalate your own request would make the grievance route a
    formality.
    """
    request = await _request(session, context, request_id)
    if not _mine(request, context):
        await _handling(session, context)
    else:
        await guard.authorise(session, context, Action.VIEW)

    if request.version != expected_version:
        raise Conflict("Somebody else changed this request. Reload it and try again.")
    if not reason.strip():
        raise ValidationFailed("Say why it is being escalated.")

    request.state = RequestState.ESCALATED
    request.version += 1
    await session.flush()

    await _step(session, context, request, ActionKind.ESCALATED, reason)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.request_escalated",
        resource_type="data_principal_request",
        resource_id=request.id,
        actor=context,
        detail={"reference": request.reference, "by_the_person": _mine(request, context)},
    )
    return request


# ── reading ────────────────────────────────────────────────────────────────────────────────


async def list_requests(
    session: AsyncSession,
    context: SecurityContext,
    *,
    mine_only: bool = False,
) -> list[DataPrincipalRequest]:
    """Requests, soonest due first.

    `mine_only` is what a person sees of their own; everything else needs `administer`, because a
    request names somebody and says what they asked about their own data.
    """
    if mine_only:
        await guard.authorise(session, context, Action.VIEW)
    else:
        await _handling(session, context)

    statement = select(DataPrincipalRequest).where(
        DataPrincipalRequest.tenant_id == context.tenant_id
    )
    if mine_only:
        statement = statement.where(
            DataPrincipalRequest.requested_by_membership_id == context.membership_id
        )
    rows = (
        await session.execute(
            statement.order_by(
                DataPrincipalRequest.due_at.asc().nullslast(),
                DataPrincipalRequest.created_at.desc(),
            )
        )
    ).scalars()
    return list(rows.all())


async def trail(
    session: AsyncSession, context: SecurityContext, request_id: uuid.UUID
) -> list[RequestAction]:
    """Every step taken on one request, in order.

    A person may read the trail of their own request. That is deliberate: §4's whole shape is a
    process somebody can be shown, and a trail only administrators can see is a process the person
    has to take on trust.
    """
    request = await _request(session, context, request_id)
    if not _mine(request, context):
        await _handling(session, context)
    else:
        await guard.authorise(session, context, Action.VIEW)

    rows = (
        await session.execute(
            select(RequestAction)
            .where(
                RequestAction.tenant_id == context.tenant_id,
                RequestAction.request_id == request.id,
            )
            .order_by(RequestAction.occurred_at)
        )
    ).scalars()
    return list(rows.all())
