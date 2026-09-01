"""The privacy lifecycle: the register, the notice, the consent and the request.

`docs/security/PRIVACY_COMPLIANCE.md` §2 to §5. These tests are about the refusals, because the
refusals are the product: a privacy module that records whatever anybody types is a filing cabinet,
and what makes it a control is what it will not accept.

The five that matter most, in the order they would bite:

* A consent cannot be recorded against wording nobody approved.
* A consent cannot be recorded where consent is not the basis — §3: *"the system must not
  manufacture consent to hide another basis."*
* A notice cannot be approved by its author, and its words freeze when it takes effect.
* A rights request cannot be decided by the person who made it, or without identifying them, or
  without a reason.
* An erasure cannot be fulfilled over a live legal hold — §5: *"an erasure request never silently
  destroys records that law requires to be retained."*
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.privacy import requests as rights
from uboss.modules.privacy import service as privacy
from uboss.modules.privacy.models import (
    ConsentRecord,
    ConsentState,
    NoticeState,
    PrivacyNoticeVersion,
    ProcessingBasis,
    ProcessingRole,
    RequestDecision,
    RequestKind,
    RequestState,
)

pytestmark = pytest.mark.anyio


async def _context(
    session: AsyncSession,
    workspace: Workspace,
    *,
    membership_id: uuid.UUID | None = None,
    administer: bool = True,
) -> SecurityContext:
    """A signed-in person, with `administer` unless a test is about not having it."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    if administer:
        await _grant_administer(session, workspace)
    membership = await session.get(Membership, membership_id or workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = datetime.now(UTC)
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        email=f"{membership.id.hex[:6]}@test",
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        org_node_id=membership.org_node_id,
        policy_grants=ceiling,
        step_up_at=now,
        step_up_expires_at=now + timedelta(minutes=10),
    )


async def _grant_administer(session: AsyncSession, workspace: Workspace) -> None:
    """Give this workspace's role `administer`.

    `two_workspaces` grants view, comment, edit_draft and publish — the Builder's set. Privacy work
    is workspace configuration, so every function here that handles somebody else's request or
    changes the register needs `administer`, and the fixture is deliberately not generous.
    """
    await session.execute(
        text(
            "INSERT INTO role_permissions (tenant_id, role_id, action) "
            "VALUES (:t, :r, 'administer') ON CONFLICT DO NOTHING"
        ),
        {"t": workspace.tenant_id, "r": workspace.role_id},
    )
    await session.flush()


async def _activity(
    session: AsyncSession,
    context: SecurityContext,
    *,
    basis: ProcessingBasis = ProcessingBasis.CONSENT,
):
    return await privacy.create_activity(
        session,
        context,
        name="Workforce attendance",
        purpose="Record who was on shift, to pay them and to answer a labour inspection.",
        accountable_role=ProcessingRole.DATA_FIDUCIARY,
        basis=basis,
        principal_category="Employees and contractors",
        data_categories="Name, employee number, shift times.",
        retention_summary="Seven years from the end of the financial year.",
    )


async def _notice_version(
    session: AsyncSession,
    context: SecurityContext,
    *,
    basis: ProcessingBasis = ProcessingBasis.CONSENT,
) -> PrivacyNoticeVersion:
    notice = await privacy.create_notice(session, context, name="Attendance notice")
    return await privacy.draft_version(
        session,
        context,
        notice.id,
        body="We record when you were on shift.",
        data_items="Name, employee number, shift times.",
        purpose="To pay you and to answer a labour inspection.",
        basis=basis,
        rights_route="Write to privacy@example.test or use the Privacy Center.",
        privacy_contact="privacy@example.test",
    )


# ── §2 the register ────────────────────────────────────────────────────────────────────────


async def test_the_register_records_the_basis_and_never_assumes_one(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§3: *"the system must not manufacture consent to hide another basis."*

    `basis` is a required argument with no default, so an activity cannot come into existence
    claiming consent nobody gave. And when it changes, the audit row says so by value — a purpose
    that quietly moved from consent to legitimate use is the change a regulator asks about.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        activity = await _activity(session, context, basis=ProcessingBasis.LEGITIMATE_USE)

        assert activity.basis == ProcessingBasis.LEGITIMATE_USE
        assert activity.accountable_role == ProcessingRole.DATA_FIDUCIARY
        #  Nothing about compliance. §9 forbids the badge; the row carries evidence and a review
        #  date instead.
        assert not hasattr(activity, "compliant")
        await session.rollback()


async def test_a_purpose_cannot_be_emptied(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """An activity with no purpose answers the register's first question with silence."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        activity = await _activity(session, context)

        with pytest.raises(ValidationFailed):
            await privacy.update_activity(
                session,
                context,
                activity.id,
                expected_version=activity.version,
                changes={"purpose": "   "},
            )
        await session.rollback()


# ── §3 notices ─────────────────────────────────────────────────────────────────────────────


async def test_a_notice_cannot_be_approved_by_its_author(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§3 calls it *"independent review/approval"*, and this is what that means.

    Refused in words here, and refused again by migration 0044's constraint: a service check is
    one code path and the constraint is all of them.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        version = await _notice_version(session, context)

        with pytest.raises(ValidationFailed) as refused:
            await privacy.make_effective(session, context, version.id)
        assert "somebody other than the person who wrote it" in str(refused.value)
        await session.rollback()


async def test_making_a_notice_effective_retires_the_one_before_it(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """Two effective versions in one language and nobody could say what a person was told."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        first = await _notice_version(session, author)
        reviewer = await _context(session, left, membership_id=colleague)
        await privacy.make_effective(session, reviewer, first.id)

        second = await privacy.draft_version(
            session,
            author,
            first.notice_id,
            body="We record when you were on shift, and for how long we keep it.",
            data_items="Name, employee number, shift times.",
            purpose="To pay you and to answer a labour inspection.",
            basis=ProcessingBasis.CONSENT,
            rights_route="Use the Privacy Center.",
            privacy_contact="privacy@example.test",
        )
        await privacy.make_effective(session, reviewer, second.id)

        assert second.state == NoticeState.EFFECTIVE
        assert second.version_no == 2
        assert first.state == NoticeState.RETIRED
        assert first.retired_at is not None
        await session.rollback()


async def test_the_words_of_an_effective_notice_cannot_be_changed(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """Somebody reading a consent in three years has to be able to read what was agreed to.

    Held by a trigger, not by a service: *"we updated the wording"* is the failure that makes a
    consent record unusable, and it would arrive through whichever path nobody checked.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        version = await _notice_version(session, author)
        reviewer = await _context(session, left, membership_id=colleague)
        await privacy.make_effective(session, reviewer, version.id)
        await session.flush()

        version.body = "Something else entirely."
        with pytest.raises(DatabaseError) as refused:
            await session.flush()
        assert "cannot be changed" in str(refused.value)
        await session.rollback()


# ── §3 consent ─────────────────────────────────────────────────────────────────────────────


async def test_consent_cannot_be_recorded_against_a_draft(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A consent to wording nobody approved is a consent to nothing."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        version = await _notice_version(session, context)

        with pytest.raises(ValidationFailed) as refused:
            await privacy.grant_consent(
                session,
                context,
                notice_version_id=version.id,
                purpose="Attendance",
                channel="screen",
                evidence="Ticked the box on the attendance screen.",
            )
        assert "not in force" in str(refused.value)
        await session.rollback()


async def test_consent_is_refused_where_another_basis_applies(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """§3: *"the system must not manufacture consent to hide another basis."*

    The subtle harm is to the person: asking somebody to consent to processing that will happen
    anyway tells them they have a choice they do not have, and makes the consent they *do* give
    meaningless.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        version = await _notice_version(session, author, basis=ProcessingBasis.LEGAL_OBLIGATION)
        reviewer = await _context(session, left, membership_id=colleague)
        await privacy.make_effective(session, reviewer, version.id)

        with pytest.raises(ValidationFailed) as refused:
            await privacy.grant_consent(
                session,
                author,
                notice_version_id=version.id,
                purpose="Attendance",
                channel="screen",
                evidence="Ticked a box.",
            )
        assert "legal obligation" in str(refused.value)
        await session.rollback()


async def test_a_consent_and_its_withdrawal_are_two_rows_and_neither_can_be_edited(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """§3: *"withdrawal … creates immutable evidence."*

    The withdrawal points at the grant instead of overwriting it, so the history is readable: what
    was agreed, when, and when it was taken back. A boolean would have answered only the last of the
    three.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        version = await _notice_version(session, author)
        reviewer = await _context(session, left, membership_id=colleague)
        await privacy.make_effective(session, reviewer, version.id)

        grant = await privacy.grant_consent(
            session,
            author,
            notice_version_id=version.id,
            purpose="Attendance",
            channel="screen",
            evidence="Ticked the box on the attendance screen on 1 September.",
        )
        withdrawal = await privacy.withdraw_consent(
            session, author, grant.id, channel="screen", evidence="Used the Privacy Center."
        )

        assert withdrawal.state == ConsentState.WITHDRAWN
        assert withdrawal.withdraws_id == grant.id
        assert withdrawal.id != grant.id

        history = await privacy.consent_history(session, author)
        assert [row.state for row in history] == [
            ConsentState.WITHDRAWN,
            ConsentState.GRANTED,
        ], "newest first, and both survive"

        #  And the evidence cannot be rewritten.
        grant.evidence = "Something more convenient."
        with pytest.raises(DatabaseError):
            await session.flush()
        await session.rollback()


async def test_a_consent_cannot_be_withdrawn_twice(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """Two withdrawals of one grant would make the history unreadable."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        version = await _notice_version(session, author)
        reviewer = await _context(session, left, membership_id=colleague)
        await privacy.make_effective(session, reviewer, version.id)
        grant = await privacy.grant_consent(
            session,
            author,
            notice_version_id=version.id,
            purpose="Attendance",
            channel="screen",
            evidence="Ticked the box.",
        )
        await privacy.withdraw_consent(
            session, author, grant.id, channel="screen", evidence="Privacy Center."
        )

        with pytest.raises(ValidationFailed):
            await privacy.withdraw_consent(
                session, author, grant.id, channel="email", evidence="Asked again."
            )
        await session.rollback()


# ── §5 legal holds ─────────────────────────────────────────────────────────────────────────


async def test_a_hold_is_released_only_with_a_reason(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A hold released with no explanation is a deletion nobody authorised, discovered later."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        hold = await privacy.place_hold(
            session,
            context,
            name="Labour inspection 2026",
            scope="Attendance records for the Chennai plant, 2024 to 2026.",
            reason="Records are under inspection and must be preserved.",
            authority="Labour Commissioner notice dated 12 August 2026.",
        )

        with pytest.raises(ValidationFailed):
            await privacy.release_hold(
                session, context, hold.id, expected_version=hold.version, reason="  "
            )

        released = await privacy.release_hold(
            session,
            context,
            hold.id,
            expected_version=hold.version,
            reason="Inspection closed; letter dated 20 September 2026.",
        )
        assert released.released_at is not None
        assert released.is_active is False
        await session.rollback()


# ── §4 the request lifecycle ───────────────────────────────────────────────────────────────


async def test_a_request_runs_through_the_whole_of_section_four(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """The happy path, arrow by arrow, and the trail it leaves.

    The person asks; somebody else identifies them, acknowledges, searches, reviews exemptions,
    decides with a reason, records what was sent, and closes it. Every step is a row nobody can
    edit — which is what makes the decision explainable a year later.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        person = await _context(session, left)
        officer = await _context(session, left, membership_id=colleague)

        request = await rights.submit(
            session,
            person,
            kind=RequestKind.ACCESS,
            details="Please send me everything you hold about my shifts.",
            due_at=datetime.now(UTC) + timedelta(days=30),
        )
        assert request.reference.startswith("DPR-")
        assert request.state == RequestState.SUBMITTED

        await rights.record_identity_check(
            session,
            officer,
            request.id,
            expected_version=request.version,
            how="Signed in as the account holder; employee number matched the HR record.",
        )
        await rights.acknowledge(
            session,
            officer,
            request.id,
            expected_version=request.version,
            assigned_to_membership_id=colleague,
        )
        await rights.record_discovery(
            session,
            officer,
            request.id,
            expected_version=request.version,
            found="Searched attendance, files and the notification log. 214 rows, 2 files.",
        )
        await rights.review_exemptions(
            session,
            officer,
            request.id,
            expected_version=request.version,
            note="No legal hold applies. No third-party data in the export.",
        )
        await rights.decide(
            session,
            officer,
            request.id,
            expected_version=request.version,
            decision=RequestDecision.FULFIL,
            reason="Everything held about the requester's shifts is included.",
        )
        await rights.record_delivery(
            session,
            officer,
            request.id,
            expected_version=request.version,
            note="Sent as a password-protected export via a link valid for 48 hours.",
        )
        closed = await rights.close(
            session, officer, request.id, expected_version=request.version
        )

        assert closed.state == RequestState.CLOSED
        assert closed.decision == RequestDecision.FULFIL
        assert closed.decided_by_membership_id == colleague
        assert closed.delivered_at is not None

        trail = await rights.trail(session, officer, request.id)
        assert [step.kind for step in trail] == [
            "submitted",
            "identity_checked",
            "acknowledged",
            "discovery_recorded",
            "exemption_reviewed",
            "decided",
            "delivered",
            "closed",
        ]
        #  And the trail cannot be tidied up afterwards.
        trail[0].detail = "something else"
        with pytest.raises(DatabaseError):
            await session.flush()
        await session.rollback()


async def test_the_person_who_asked_cannot_decide_their_own_request(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """§4: *"Requestor cannot approve their own administrative decision."*

    The workspace owner submitting their own access request and approving it would be the whole
    control defeated by one person holding two hats — which is why the constraint is on the table as
    well as here.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        person = await _context(session, left)
        officer = await _context(session, left, membership_id=colleague)

        request = await rights.submit(
            session, person, kind=RequestKind.ACCESS, details="Everything, please."
        )
        await rights.record_identity_check(
            session, officer, request.id, expected_version=request.version, how="Signed in."
        )

        with pytest.raises(PermissionDenied) as refused:
            await rights.decide(
                session,
                person,
                request.id,
                expected_version=request.version,
                decision=RequestDecision.FULFIL,
                reason="Looks fine to me.",
            )
        assert "not yours to make" in str(refused.value)
        await session.rollback()


async def test_a_request_cannot_be_decided_before_the_person_is_identified(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """Answering an access request unverified means answering whoever asked."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        person = await _context(session, left)
        officer = await _context(session, left, membership_id=colleague)
        request = await rights.submit(
            session, person, kind=RequestKind.ACCESS, details="Everything, please."
        )

        with pytest.raises(ValidationFailed) as refused:
            await rights.decide(
                session,
                officer,
                request.id,
                expected_version=request.version,
                decision=RequestDecision.FULFIL,
                reason="Sending it now.",
            )
        assert "Identify the person first" in str(refused.value)
        await session.rollback()


async def test_a_decision_without_a_reason_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """The reason is for the person, not for the file.

    A rejection somebody cannot understand is a rejection they cannot challenge, and §4 requires it
    on every rejection and partial response.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        person = await _context(session, left)
        officer = await _context(session, left, membership_id=colleague)
        request = await rights.submit(
            session, person, kind=RequestKind.ERASURE, details="Delete my shift history."
        )
        await rights.record_identity_check(
            session, officer, request.id, expected_version=request.version, how="Signed in."
        )

        with pytest.raises(ValidationFailed):
            await rights.decide(
                session,
                officer,
                request.id,
                expected_version=request.version,
                decision=RequestDecision.REJECT,
                reason="   ",
            )
        await session.rollback()


async def test_an_erasure_is_not_fulfilled_over_a_live_legal_hold(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """§5: *"an erasure request never silently destroys records that law requires to be retained."*

    The refusal names the hold and offers the two honest ways forward — a partial fulfilment that
    says what is being withheld, or an authorised release of the hold. It does not offer a way to
    proceed quietly, which is the point.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        person = await _context(session, left)
        officer = await _context(session, left, membership_id=colleague)
        hold = await privacy.place_hold(
            session,
            officer,
            name="Labour inspection 2026",
            scope="Attendance records for the Chennai plant.",
            reason="Under inspection.",
            authority="Labour Commissioner notice dated 12 August 2026.",
        )

        request = await rights.submit(
            session, person, kind=RequestKind.ERASURE, details="Delete my shift history."
        )
        await rights.record_identity_check(
            session, officer, request.id, expected_version=request.version, how="Signed in."
        )
        await rights.review_exemptions(
            session,
            officer,
            request.id,
            expected_version=request.version,
            note="The 2026 inspection hold covers these records.",
            legal_hold_id=hold.id,
        )

        with pytest.raises(ValidationFailed) as refused:
            await rights.decide(
                session,
                officer,
                request.id,
                expected_version=request.version,
                decision=RequestDecision.FULFIL,
                reason="Deleting everything.",
            )
        assert "Labour inspection 2026" in str(refused.value)

        #  A partial fulfilment that says what is withheld is allowed, which is the honest route.
        partial = await rights.decide(
            session,
            officer,
            request.id,
            expected_version=request.version,
            decision=RequestDecision.PARTIALLY_FULFIL,
            reason=(
                "Personal contact details erased. Attendance rows for 2024 to 2026 retained under "
                "the Labour Commissioner's inspection notice."
            ),
        )
        assert partial.state == RequestState.PARTIALLY_FULFILLED
        await session.rollback()


async def test_a_stale_read_cannot_change_a_request(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """Two people handling one request must not overwrite each other."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        person = await _context(session, left)
        officer = await _context(session, left, membership_id=colleague)
        request = await rights.submit(
            session, person, kind=RequestKind.ACCESS, details="Everything."
        )

        with pytest.raises(Conflict):
            await rights.record_identity_check(
                session,
                officer,
                request.id,
                expected_version=request.version + 5,
                how="Signed in.",
            )
        await session.rollback()


async def test_a_person_sees_their_own_request_and_its_trail(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """§4's shape is a process somebody can be shown.

    A trail only administrators can read is a process the person has to take on trust — so the
    requester may read their own, and may escalate it.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        person = await _context(session, left)
        request = await rights.submit(
            session, person, kind=RequestKind.GRIEVANCE, details="Nobody answered my last request."
        )

        mine = await rights.list_requests(session, person, mine_only=True)
        assert [row.id for row in mine] == [request.id]
        assert len(await rights.trail(session, person, request.id)) == 1

        escalated = await rights.escalate(
            session,
            person,
            request.id,
            expected_version=request.version,
            reason="Two weeks with no reply.",
        )
        assert escalated.state == RequestState.ESCALATED
        await session.rollback()


async def test_another_workspace_sees_none_of_this(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The boundary, asserted from the other side.

    Both boundaries hold: every query names `tenant_id`, and row-level security is enforced on the
    application role this test uses.
    """
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        mine = await _context(session, left)
        request = await rights.submit(
            session, mine, kind=RequestKind.ACCESS, details="Mine alone."
        )
        await _activity(session, mine)
        await session.commit()
        request_id = request.id

    async with build_sessionmaker(app_engine)() as session:
        theirs = await _context(session, right)
        with pytest.raises(NotFound):
            await rights.trail(session, theirs, request_id)
        assert await privacy.list_activities(session, theirs) == []
        assert await rights.list_requests(session, theirs) == []
        await session.rollback()

    #  Nothing to clean up by hand: `request_actions` and `consent_records` refuse DELETE, and the
    #  `two_workspaces` teardown is what lifts those triggers when it removes the tenant.


async def test_consent_and_request_evidence_survive_the_person_leaving(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """A person can leave; what they were told and what they agreed to cannot leave with them.

    `principal_email` sits beside the membership for exactly this: the membership goes null when
    somebody is deleted, and the evidence stays readable.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        reviewer = await _context(session, left, membership_id=colleague)
        version = await _notice_version(session, author)
        await privacy.make_effective(session, reviewer, version.id)

        record = await privacy.grant_consent(
            session,
            author,
            notice_version_id=version.id,
            purpose="Attendance",
            channel="screen",
            evidence="Ticked the box.",
            membership_id=colleague,
            principal_email="second@test",
        )

        assert record.principal_email == "second@test"
        stored = (
            await session.execute(
                select(ConsentRecord).where(ConsentRecord.id == record.id)
            )
        ).scalar_one()
        assert stored.recorded_by_membership_id == left.membership_id, (
            "who recorded it, not who agreed to it"
        )
        await session.rollback()
