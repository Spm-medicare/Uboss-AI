"""The register, the notices, the consent evidence and the holds.

`docs/security/PRIVACY_COMPLIANCE.md` §2, §3 and §5. Four things, and one rule runs through all of
them: **the product records what somebody decided; it never decides for them.**

§1 of that contract and §19.1 of the plan both say it, and it is worth spelling out what it means
here in code:

* No basis is defaulted. An activity that came into existence claiming consent would be claiming
  consent nobody gave.
* No statutory period is computed. A retention summary is a sentence somebody wrote; a request's due
  date is a date somebody set from the approved register — DR-011 is still open, and a product that
  invented a deadline would be making a legal claim in a `timedelta`.
* No compliance claim anywhere. §9: *"No UI may show a generic 'DPDP/GDPR compliant' badge. Show
  control status, evidence, gap, owner and review date."* Which is why `ProcessingActivity` has
  `review_due` and `evidence_note` and no `compliant` column.

## Permissions

The register, the notices and the holds are workspace configuration: `administer`, which is one of
`HIGH_RISK_ACTIONS`, so a route that changes them can require a proved password without inventing a
new rule.

A person's own consent is their own act and needs nothing beyond being signed in. Recording somebody
else's consent — an import, a paper form — is `administer`, because it is an assertion about another
person.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.privacy.models import (
    ConsentRecord,
    ConsentState,
    LegalHold,
    NoticeState,
    PrivacyNotice,
    PrivacyNoticeVersion,
    ProcessingActivity,
    ProcessingBasis,
    ProcessingRole,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned[:limit] if cleaned else None


# ── §2 the processing inventory ────────────────────────────────────────────────────────────


async def list_activities(
    session: AsyncSession, context: SecurityContext, *, include_archived: bool = False
) -> list[ProcessingActivity]:
    """The register, most recently reviewed first.

    Sorted by `review_due` rather than by name: the register's whole purpose is to be reviewed, and
    the row nobody has looked at since last year is the one somebody needs to see.
    """
    await guard.authorise(session, context, Action.VIEW)
    statement = select(ProcessingActivity).where(
        ProcessingActivity.tenant_id == context.tenant_id
    )
    if not include_archived:
        statement = statement.where(ProcessingActivity.archived_at.is_(None))
    rows = (
        await session.execute(
            statement.order_by(
                ProcessingActivity.review_due.asc().nullslast(), ProcessingActivity.name
            )
        )
    ).scalars()
    return list(rows.all())


async def create_activity(
    session: AsyncSession,
    context: SecurityContext,
    *,
    name: str,
    purpose: str,
    accountable_role: ProcessingRole,
    basis: ProcessingBasis,
    principal_category: str,
    data_categories: str,
    source: str | None = None,
    recipients: str | None = None,
    ai_access: bool = False,
    region: str | None = None,
    transfer_rule: str | None = None,
    retention_summary: str | None = None,
    deletion_path: str | None = None,
    owner_membership_id: uuid.UUID | None = None,
    effective_from: date | None = None,
    review_due: date | None = None,
    evidence_note: str | None = None,
) -> ProcessingActivity:
    """Add one processing activity to the register.

    Six things are required, and they are the six without which the row answers nothing: what it is,
    what it is *for*, who is accountable, on what basis, about whom, and which data. The rest —
    region, transfer rule, retention, deletion path, owner, review date — is filled in as the
    register matures, and a row missing them is visibly incomplete rather than silently wrong.

    Written as named parameters rather than a `**kwargs` bag. The bag needed a `type: ignore` on
    every line that read from it, which is the compiler pointing out that nobody knew what was in
    it.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    if not purpose.strip():
        raise ValidationFailed(
            "Say what this processing is for. A specific purpose — “business operations” is not "
            "one."
        )

    activity = ProcessingActivity(
        tenant_id=context.tenant_id,
        name=name.strip()[:200],
        purpose=purpose.strip(),
        accountable_role=accountable_role.value,
        basis=basis.value,
        principal_category=principal_category.strip()[:200],
        data_categories=data_categories.strip(),
        source=_text(source, 4000),
        recipients=_text(recipients, 4000),
        ai_access=ai_access,
        region=_text(region, 120),
        transfer_rule=_text(transfer_rule, 4000),
        retention_summary=_text(retention_summary, 4000),
        deletion_path=_text(deletion_path, 4000),
        owner_membership_id=owner_membership_id,
        effective_from=effective_from,
        review_due=review_due,
        evidence_note=_text(evidence_note, 4000),
    )
    session.add(activity)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.activity_recorded",
        resource_type="processing_activity",
        resource_id=activity.id,
        actor=context,
        detail={
            "name": activity.name,
            "basis": activity.basis,
            "role": activity.accountable_role,
        },
    )
    return activity


#: What may be changed on a register entry, and the length each is trimmed to.
ACTIVITY_FIELDS: dict[str, int] = {
    "name": 200,
    "purpose": 8000,
    "principal_category": 200,
    "data_categories": 8000,
    "source": 4000,
    "recipients": 4000,
    "region": 120,
    "transfer_rule": 4000,
    "retention_summary": 4000,
    "deletion_path": 4000,
    "evidence_note": 4000,
}


async def update_activity(
    session: AsyncSession,
    context: SecurityContext,
    activity_id: uuid.UUID,
    *,
    expected_version: int,
    changes: dict[str, object],
) -> ProcessingActivity:
    """Correct a register entry.

    A register is corrected rather than frozen — it describes what is happening now, and what was
    happening before is in the audit trail. Changing the **basis** is the one edit worth noticing,
    so it is recorded by name: a purpose that quietly moved from consent to legitimate use is the
    change a regulator asks about.
    """
    activity = await _activity(session, context, activity_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if activity.version != expected_version:
        raise Conflict("Somebody else changed this entry. Reload it and try again.")

    changed: list[str] = []
    for field, limit in ACTIVITY_FIELDS.items():
        if field not in changes:
            continue
        sent = changes[field]
        value = _text(sent if sent is None or isinstance(sent, str) else str(sent), limit)
        if field in ("name", "purpose", "principal_category", "data_categories") and not value:
            raise ValidationFailed(f"“{field.replace('_', ' ')}” cannot be emptied.")
        if getattr(activity, field) != value:
            setattr(activity, field, value)
            changed.append(field)

    for field, enum_type in (("accountable_role", ProcessingRole), ("basis", ProcessingBasis)):
        if changes.get(field):
            chosen = enum_type(str(changes[field])).value
            if getattr(activity, field) != chosen:
                setattr(activity, field, chosen)
                changed.append(field)

    for field in ("effective_from", "review_due"):
        if field in changes and getattr(activity, field) != changes[field]:
            setattr(activity, field, changes[field])
            changed.append(field)

    if "ai_access" in changes and activity.ai_access != bool(changes["ai_access"]):
        activity.ai_access = bool(changes["ai_access"])
        changed.append("ai_access")

    if changed:
        activity.version += 1
        await session.flush()
        await audit.record(
            session,
            tenant_id=context.tenant_id,
            action="privacy.activity_corrected",
            resource_type="processing_activity",
            resource_id=activity.id,
            actor=context,
            #  Field names, and the basis by value when it moved — the one change worth reading
            #  without opening the row.
            detail={
                "fields": changed,
                **({"basis": activity.basis} if "basis" in changed else {}),
            },
        )
    return activity


async def archive_activity(
    session: AsyncSession,
    context: SecurityContext,
    activity_id: uuid.UUID,
    *,
    expected_version: int,
) -> ProcessingActivity:
    """Stop describing an activity that has stopped, and keep the row.

    Never deleted: consent records point at it, and a consent whose purpose disappeared is a consent
    nobody can explain.
    """
    activity = await _activity(session, context, activity_id)
    await guard.authorise(session, context, Action.ADMINISTER)
    if activity.version != expected_version:
        raise Conflict("Somebody else changed this entry. Reload it and try again.")
    if activity.archived_at is not None:
        raise ValidationFailed("This entry is already archived.")

    activity.archived_at = _now()
    activity.version += 1
    await session.flush()
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.activity_archived",
        resource_type="processing_activity",
        resource_id=activity.id,
        actor=context,
        detail={},
    )
    return activity


async def _activity(
    session: AsyncSession, context: SecurityContext, activity_id: uuid.UUID
) -> ProcessingActivity:
    row = (
        await session.execute(
            select(ProcessingActivity).where(
                ProcessingActivity.tenant_id == context.tenant_id,
                ProcessingActivity.id == activity_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such register entry.")
    return row


# ── §3 notices ─────────────────────────────────────────────────────────────────────────────


async def create_notice(
    session: AsyncSession,
    context: SecurityContext,
    *,
    name: str,
    processing_activity_id: uuid.UUID | None = None,
) -> PrivacyNotice:
    """Start a notice. Its wording arrives as a version."""
    await guard.authorise(session, context, Action.ADMINISTER)
    if not name.strip():
        raise ValidationFailed("Give the notice a name.")

    notice = PrivacyNotice(
        tenant_id=context.tenant_id,
        name=name.strip()[:200],
        processing_activity_id=processing_activity_id,
    )
    session.add(notice)
    await session.flush()
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.notice_created",
        resource_type="privacy_notice",
        resource_id=notice.id,
        actor=context,
        detail={"name": notice.name},
    )
    return notice


async def draft_version(
    session: AsyncSession,
    context: SecurityContext,
    notice_id: uuid.UUID,
    *,
    language: str = "en",
    body: str,
    data_items: str,
    purpose: str,
    basis: ProcessingBasis,
    rights_route: str,
    privacy_contact: str,
    recipients: str | None = None,
    retention_summary: str | None = None,
) -> PrivacyNoticeVersion:
    """Write a new version of a notice.

    Every required field here is one §3 itemises: what data, what purpose, on what basis, who
    receives it, how long it is kept, how to exercise rights and who to contact. They are separate
    columns rather than one document because each is a question a reviewer checks separately — and a
    blob is what nobody reviews.

    A new version always starts as a draft, whatever state the last one is in. The version number
    is assigned by the database under an advisory lock, per language.
    """
    notice = await _notice(session, context, notice_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    for label, value in (
        ("what data it covers", data_items),
        ("what it is for", purpose),
        ("how to exercise rights", rights_route),
        ("who to contact", privacy_contact),
        ("the notice itself", body),
    ):
        if not value.strip():
            raise ValidationFailed(f"A notice has to say {label}.")

    version = PrivacyNoticeVersion(
        tenant_id=context.tenant_id,
        notice_id=notice.id,
        language=language.strip()[:16] or "en",
        state=NoticeState.DRAFT,
        body=body.strip(),
        data_items=data_items.strip(),
        purpose=purpose.strip(),
        basis=basis.value,
        recipients=_text(recipients, 4000),
        retention_summary=_text(retention_summary, 4000),
        rights_route=rights_route.strip(),
        privacy_contact=privacy_contact.strip()[:300],
        author_membership_id=context.membership_id,
    )
    session.add(version)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.notice_drafted",
        resource_type="privacy_notice",
        resource_id=notice.id,
        actor=context,
        detail={"version_id": str(version.id), "language": version.language},
    )
    return version


async def send_for_review(
    session: AsyncSession, context: SecurityContext, version_id: uuid.UUID
) -> PrivacyNoticeVersion:
    """Hand a draft to somebody else to read."""
    version = await _version(session, context, version_id)
    await guard.authorise(session, context, Action.ADMINISTER)
    if version.state != NoticeState.DRAFT:
        raise ValidationFailed("Only a draft can be sent for review.")

    version.state = NoticeState.IN_REVIEW
    await session.flush()
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.notice_sent_for_review",
        resource_type="privacy_notice",
        resource_id=version.notice_id,
        actor=context,
        detail={"version_id": str(version.id)},
    )
    return version


async def make_effective(
    session: AsyncSession,
    context: SecurityContext,
    version_id: uuid.UUID,
    *,
    effective_from: datetime | None = None,
) -> PrivacyNoticeVersion:
    """Approve a notice and put it in force.

    **Not by its author.** §3 calls the step *"independent review/approval"*, and the table refuses
    a reviewer who is also the author — so this is checked here to give a sentence rather than a
    constraint violation, and checked there because a service check is one code path.

    Whatever version was effective in the same language is retired at the same moment. Two effective
    versions of one notice in one language would mean nobody could say what a person was told.

    Once in force, the wording is frozen: migration 0044's trigger refuses any change to the words
    of a version that has been effective. A correction is a new version, which is what a notice
    history is *for*.
    """
    version = await _version(session, context, version_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if not context.has_stepped_up():
        raise ValidationFailed("Confirm your identity before putting a notice in force.")
    if version.state not in (NoticeState.DRAFT, NoticeState.IN_REVIEW):
        raise ValidationFailed("This version is already in force, or retired.")
    if version.author_membership_id == context.membership_id:
        raise ValidationFailed(
            "A notice has to be reviewed by somebody other than the person who wrote it. "
            "Ask a colleague to approve this one."
        )

    when = effective_from or _now()

    current = (
        await session.execute(
            select(PrivacyNoticeVersion).where(
                PrivacyNoticeVersion.tenant_id == context.tenant_id,
                PrivacyNoticeVersion.notice_id == version.notice_id,
                PrivacyNoticeVersion.language == version.language,
                PrivacyNoticeVersion.state == NoticeState.EFFECTIVE,
            )
        )
    ).scalars()
    for previous in current.all():
        previous.state = NoticeState.RETIRED
        previous.retired_at = when

    version.state = NoticeState.EFFECTIVE
    version.reviewed_by_membership_id = context.membership_id
    version.reviewed_at = _now()
    version.effective_from = when
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.notice_made_effective",
        resource_type="privacy_notice",
        resource_id=version.notice_id,
        actor=context,
        detail={
            "version_id": str(version.id),
            "version_no": version.version_no,
            "language": version.language,
            "author_membership_id": str(version.author_membership_id),
        },
    )
    return version


async def effective_notice(
    session: AsyncSession,
    context: SecurityContext,
    notice_id: uuid.UUID,
    *,
    language: str = "en",
) -> PrivacyNoticeVersion | None:
    """The version in force now, or `None`.

    `None` is a real answer and the caller must handle it: a workspace that has not put a notice in
    force has not put one in force, and a screen that showed a draft instead would be showing
    somebody wording nobody approved.
    """
    await guard.authorise(session, context, Action.VIEW)
    return (
        await session.execute(
            select(PrivacyNoticeVersion).where(
                PrivacyNoticeVersion.tenant_id == context.tenant_id,
                PrivacyNoticeVersion.notice_id == notice_id,
                PrivacyNoticeVersion.language == language,
                PrivacyNoticeVersion.state == NoticeState.EFFECTIVE,
            )
        )
    ).scalar_one_or_none()


async def _notice(
    session: AsyncSession, context: SecurityContext, notice_id: uuid.UUID
) -> PrivacyNotice:
    row = (
        await session.execute(
            select(PrivacyNotice).where(
                PrivacyNotice.tenant_id == context.tenant_id, PrivacyNotice.id == notice_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such notice.")
    return row


async def _version(
    session: AsyncSession, context: SecurityContext, version_id: uuid.UUID
) -> PrivacyNoticeVersion:
    row = (
        await session.execute(
            select(PrivacyNoticeVersion).where(
                PrivacyNoticeVersion.tenant_id == context.tenant_id,
                PrivacyNoticeVersion.id == version_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such notice version.")
    return row


# ── §3 consent ─────────────────────────────────────────────────────────────────────────────


async def grant_consent(
    session: AsyncSession,
    context: SecurityContext,
    *,
    notice_version_id: uuid.UUID,
    purpose: str,
    channel: str,
    evidence: str,
    membership_id: uuid.UUID | None = None,
    principal_email: str | None = None,
    processing_activity_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> ConsentRecord:
    """Record a consent — with what proves it.

    **Only against an effective notice.** A consent recorded against a draft is a consent to wording
    nobody approved, and the whole point of the version is to be able to say later exactly what the
    person agreed to.

    **Only where consent is the basis.** §3: *"Consent is recorded only when it is the approved
    basis"* and *"the system must not manufacture consent to hide another basis."* If the notice
    version says the basis is a legitimate use, asking somebody to consent to it would misrepresent
    their own rights to them — so it is refused, and the refusal says which basis applies.

    Recording your own consent needs nothing beyond being signed in. Recording somebody else's — an
    import, a paper form — is `administer`, because it is an assertion about another person.
    """
    version = await _version(session, context, notice_version_id)

    for_somebody_else = membership_id is not None and membership_id != context.membership_id
    if for_somebody_else or (membership_id is None and principal_email is not None):
        await guard.authorise(session, context, Action.ADMINISTER)
    else:
        await guard.authorise(session, context, Action.VIEW)

    if version.state != NoticeState.EFFECTIVE:
        raise ValidationFailed(
            "This version of the notice is not in force, so a consent cannot be recorded against "
            "it. Put it in force first."
        )
    if version.basis != ProcessingBasis.CONSENT:
        raise ValidationFailed(
            f"This notice records “{version.basis.replace('_', ' ')}” as its basis, not consent. "
            "Asking for consent where another basis applies misrepresents the person's rights."
        )
    if not evidence.strip():
        raise ValidationFailed(
            "Record what proves this consent — how it was given and what was shown. A consent "
            "nobody can reconstruct cannot be relied on."
        )

    who = membership_id if membership_id is not None else context.membership_id
    record = ConsentRecord(
        tenant_id=context.tenant_id,
        membership_id=who,
        principal_email=_text(principal_email, 320),
        processing_activity_id=processing_activity_id,
        notice_version_id=version.id,
        purpose=purpose.strip() or version.purpose,
        state=ConsentState.GRANTED,
        channel=channel.strip()[:60] or "screen",
        evidence=evidence.strip(),
        language=version.language,
        expires_at=expires_at,
        recorded_by_membership_id=context.membership_id,
    )
    session.add(record)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.consent_granted",
        resource_type="consent_record",
        resource_id=record.id,
        actor=context,
        detail={
            "notice_version_id": str(version.id),
            "for_somebody_else": for_somebody_else,
            #  The purpose, not the evidence: the evidence can describe what somebody was shown,
            #  and copying it into a second table is a second place it has to be governed.
            "purpose": record.purpose[:200],
        },
    )
    return record


async def withdraw_consent(
    session: AsyncSession,
    context: SecurityContext,
    consent_id: uuid.UUID,
    *,
    channel: str,
    evidence: str,
) -> ConsentRecord:
    """Withdraw a consent, as easily as it was given — §3's own requirement.

    A **new row** pointing at the grant, never an edit of it: the grant is evidence, the withdrawal
    is evidence, and the history between them is part of both. Migration 0044 refuses an edit either
    way.

    A person withdraws their own consent with no permission beyond being signed in. Withdrawing on
    somebody's behalf is `administer` — and the row records who did it, because *"withdrawal is as
    discoverable as grant"* cuts both ways.
    """
    grant = (
        await session.execute(
            select(ConsentRecord).where(
                ConsentRecord.tenant_id == context.tenant_id, ConsentRecord.id == consent_id
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise NotFound("No such consent record.")

    if grant.membership_id != context.membership_id:
        await guard.authorise(session, context, Action.ADMINISTER)
    else:
        await guard.authorise(session, context, Action.VIEW)

    if grant.state != ConsentState.GRANTED:
        raise ValidationFailed("That record is a withdrawal, not a consent.")

    already = (
        await session.execute(
            select(ConsentRecord.id).where(
                ConsentRecord.tenant_id == context.tenant_id,
                ConsentRecord.withdraws_id == grant.id,
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        raise ValidationFailed("This consent has already been withdrawn.")

    if not evidence.strip():
        raise ValidationFailed("Record how the withdrawal was made.")

    record = ConsentRecord(
        tenant_id=context.tenant_id,
        membership_id=grant.membership_id,
        principal_email=grant.principal_email,
        processing_activity_id=grant.processing_activity_id,
        notice_version_id=grant.notice_version_id,
        purpose=grant.purpose,
        state=ConsentState.WITHDRAWN,
        channel=channel.strip()[:60] or "screen",
        evidence=evidence.strip(),
        language=grant.language,
        withdraws_id=grant.id,
        recorded_by_membership_id=context.membership_id,
    )
    session.add(record)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.consent_withdrawn",
        resource_type="consent_record",
        resource_id=record.id,
        actor=context,
        detail={
            "withdraws_id": str(grant.id),
            "by_the_person": grant.membership_id == context.membership_id,
        },
    )
    return record


async def consent_history(
    session: AsyncSession,
    context: SecurityContext,
    *,
    membership_id: uuid.UUID | None = None,
) -> list[ConsentRecord]:
    """Every consent event for one person, newest first.

    Reading your own needs nothing; reading somebody else's is `administer`. The list is the history
    rather than the current state, because *"do they consent"* is a question you answer by reading
    the events — and a single flag would be the answer that hides the withdrawal.
    """
    who = membership_id or context.membership_id
    if who != context.membership_id:
        await guard.authorise(session, context, Action.ADMINISTER)
    else:
        await guard.authorise(session, context, Action.VIEW)

    rows = (
        await session.execute(
            select(ConsentRecord)
            .where(
                ConsentRecord.tenant_id == context.tenant_id,
                ConsentRecord.membership_id == who,
            )
            .order_by(ConsentRecord.occurred_at.desc())
        )
    ).scalars()
    return list(rows.all())


# ── §5 legal holds ─────────────────────────────────────────────────────────────────────────


async def place_hold(
    session: AsyncSession,
    context: SecurityContext,
    *,
    name: str,
    scope: str,
    reason: str,
    authority: str,
) -> LegalHold:
    """Record that something must be kept, and why.

    Four required fields, and none of them is optional for a reason: a hold with no authority is
    somebody's opinion, and a hold with no scope cannot be applied to a request. §5: *"conflicting
    legal retention duties require an authorised decision"* — this is where that decision lives.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    for label, value in (
        ("a name", name),
        ("what it covers", scope),
        ("why", reason),
        ("on whose authority", authority),
    ):
        if not value.strip():
            raise ValidationFailed(f"A legal hold needs {label}.")

    hold = LegalHold(
        tenant_id=context.tenant_id,
        name=name.strip()[:200],
        scope=scope.strip(),
        reason=reason.strip(),
        authority=authority.strip()[:300],
        placed_by_membership_id=context.membership_id,
    )
    session.add(hold)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.hold_placed",
        resource_type="legal_hold",
        resource_id=hold.id,
        actor=context,
        detail={"name": hold.name, "authority": hold.authority},
    )
    return hold


async def release_hold(
    session: AsyncSession,
    context: SecurityContext,
    hold_id: uuid.UUID,
    *,
    expected_version: int,
    reason: str,
) -> LegalHold:
    """End a hold, with a reason.

    The reason is required by the table as well. A hold that was released with no explanation is a
    deletion nobody authorised, discovered later.
    """
    hold = (
        await session.execute(
            select(LegalHold).where(
                LegalHold.tenant_id == context.tenant_id, LegalHold.id == hold_id
            )
        )
    ).scalar_one_or_none()
    if hold is None:
        raise NotFound("No such legal hold.")

    await guard.authorise(session, context, Action.ADMINISTER)
    if hold.version != expected_version:
        raise Conflict("Somebody else changed this hold. Reload it and try again.")
    if hold.released_at is not None:
        raise ValidationFailed("This hold has already been released.")
    if not reason.strip():
        raise ValidationFailed("Say why the hold is being released.")

    hold.released_at = _now()
    hold.released_by_membership_id = context.membership_id
    hold.release_reason = reason.strip()
    hold.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.hold_released",
        resource_type="legal_hold",
        resource_id=hold.id,
        actor=context,
        detail={"reason": hold.release_reason[:300]},
    )
    return hold


async def active_holds(session: AsyncSession, context: SecurityContext) -> list[LegalHold]:
    """Every hold still in force. Read before an erasure is fulfilled."""
    await guard.authorise(session, context, Action.VIEW)
    rows = (
        await session.execute(
            select(LegalHold)
            .where(
                LegalHold.tenant_id == context.tenant_id,
                LegalHold.released_at.is_(None),
            )
            .order_by(LegalHold.placed_at.desc())
        )
    ).scalars()
    return list(rows.all())
