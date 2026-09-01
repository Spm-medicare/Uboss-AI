"""Retention, breach cases and the processor register — §5, §6 and §7.

Same shape as the rest of the privacy suite: the refusals are the product. Three of them decide
whether these tables are controls or filing:

* **A disposal is approved by somebody who did not prepare it.** The one control in §5 that cannot
  be recovered after the fact — once personal data is gone, an unreviewed approval is unreviewable
  for ever.
* **A breach notification names the person who decided it.** §6: an Agent *"may draft; it cannot
  decide legal notification or send without authorised approval."*
* **A processor is not active without a contract on record.** §7's *"before personal data is sent"*.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.privacy import retention
from uboss.modules.privacy.retention_models import (
    BreachSeverity,
    BreachState,
    Disposal,
    ProcessorRole,
    ProcessorState,
    RunState,
)

pytestmark = pytest.mark.anyio


async def _context(
    session: AsyncSession,
    workspace: Workspace,
    *,
    membership_id: uuid.UUID | None = None,
) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    await session.execute(
        text(
            "INSERT INTO role_permissions (tenant_id, role_id, action) "
            "VALUES (:t, :r, 'administer') ON CONFLICT DO NOTHING"
        ),
        {"t": workspace.tenant_id, "r": workspace.role_id},
    )
    await session.flush()
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


async def _policy(session: AsyncSession, context: SecurityContext):
    return await retention.create_policy(
        session,
        context,
        name="Attendance records",
        data_category="Attendance and shift times",
        trigger="Seven years after the end of the financial year the shift falls in.",
        disposal=Disposal.DELETE,
        period_days=2557,
        backup_behaviour=(
            "Backups roll off on their own 35-day cycle; nothing is restored in order to delete."
        ),
    )


# ── §5 retention ───────────────────────────────────────────────────────────────────────────


async def test_a_policy_never_invents_a_period(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`period_days` is optional and has no default.

    §5 scopes a policy by category, purpose, jurisdiction and lifecycle state, and every one of
    those is somebody's decision. *"Decided case by case"* is a real answer, and a number nobody
    chose would be this product deciding how long an organisation keeps personal data.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        undecided = await retention.create_policy(
            session,
            context,
            name="Grievance correspondence",
            data_category="Grievance letters",
            trigger="When the grievance is closed.",
            disposal=Disposal.REVIEW,
        )

        assert undecided.period_days is None, "not a guess, and not a zero"
        assert undecided.disposal == Disposal.REVIEW
        assert undecided.approval_required is True, "approval is the default, not the exception"
        await session.rollback()


async def test_a_preview_needs_evidence_behind_its_numbers(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A count with nothing behind it is a number, not a preview.

    This module does not perform the search — the counts come from whoever did — so the evidence is
    the only thing that makes them checkable.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        policy = await _policy(session, context)

        with pytest.raises(ValidationFailed):
            await retention.prepare_run(
                session, context, policy.id, candidates=214, excluded=3, evidence="  "
            )

        run = await retention.prepare_run(
            session,
            context,
            policy.id,
            candidates=214,
            excluded=3,
            evidence="Searched attendance rows before FY2019. 3 excluded under the 2026 hold.",
        )
        assert run.state == RunState.PREVIEW
        assert run.candidates == 214
        #  Nothing claimed about disposal yet. A zero here would say it deleted nothing when it has
        #  not been asked to delete anything.
        assert run.disposed is None
        await session.rollback()


async def test_the_person_who_prepared_a_disposal_cannot_approve_it(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """The control in §5 that cannot be recovered after the fact.

    Once personal data is gone, an approval nobody reviewed stays unreviewed for ever — so the
    refusal is here in words and in migration 0045's constraint, and the approval needs a proved
    password on top.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        preparer = await _context(session, left)
        policy = await _policy(session, preparer)
        run = await retention.prepare_run(
            session,
            preparer,
            policy.id,
            candidates=10,
            excluded=0,
            evidence="Ten rows past their period.",
        )

        with pytest.raises(PermissionDenied) as refused:
            await retention.approve_run(session, preparer, run.id)
        assert "not yours to give" in str(refused.value)

        approver = await _context(session, left, membership_id=colleague)
        approved = await retention.approve_run(session, approver, run.id)
        assert approved.state == RunState.APPROVED
        assert approved.approved_by_membership_id == colleague
        await session.rollback()


async def test_a_disposal_cannot_report_more_than_the_preview_found(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], colleague: uuid.UUID
) -> None:
    """The one arithmetic check worth refusing on.

    More disposed than there were candidates means something happened that nobody previewed — which
    is the shape of an accident nobody would otherwise notice until the data was asked for.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        preparer = await _context(session, left)
        approver = await _context(session, left, membership_id=colleague)
        policy = await _policy(session, preparer)
        run = await retention.prepare_run(
            session, preparer, policy.id, candidates=10, excluded=0, evidence="Ten rows."
        )
        await retention.approve_run(session, approver, run.id)

        with pytest.raises(ValidationFailed) as refused:
            await retention.record_execution(
                session,
                approver,
                run.id,
                disposed=12,
                failed=0,
                reconciled=12,
                evidence="Deleted twelve.",
            )
        assert "nobody previewed" in str(refused.value)

        done = await retention.record_execution(
            session,
            approver,
            run.id,
            disposed=10,
            failed=0,
            reconciled=10,
            evidence="Deleted ten rows; counts reconciled against the attendance table.",
        )
        assert done.state == RunState.EXECUTED
        assert done.executed_at is not None
        #  The preview's evidence survives the execution's — the approval stands on it.
        assert "Ten rows." in done.evidence
        assert "reconciled against" in done.evidence
        await session.rollback()


async def test_a_disposal_is_recorded_only_against_an_approved_run(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A preview is a plan. Recording a disposal against one would skip the approval entirely."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        policy = await _policy(session, context)
        run = await retention.prepare_run(
            session, context, policy.id, candidates=5, excluded=0, evidence="Five rows."
        )

        with pytest.raises(ValidationFailed):
            await retention.record_execution(
                session, context, run.id, disposed=5, failed=0, reconciled=5, evidence="Gone."
            )
        await session.rollback()


async def test_a_retention_run_cannot_be_deleted(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The row is the record that a deletion happened.

    A record of a deletion that can itself be deleted is not a record. `UPDATE` is allowed — the run
    moves through its states — and `DELETE` never is, by trigger and by withheld privilege.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        policy = await _policy(session, context)
        run = await retention.prepare_run(
            session, context, policy.id, candidates=1, excluded=0, evidence="One row."
        )
        await session.flush()

        await session.delete(run)
        with pytest.raises(DatabaseError):
            await session.flush()
        await session.rollback()


# ── §6 breach cases ────────────────────────────────────────────────────────────────────────


async def test_a_case_opens_on_suspicion_and_starts_unknown(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§6: *"Any suspected personal-data impact opens a restricted breach case."*

    Suspected — so the bar is low, the severity starts at `unknown`, and `awareness_at` is when
    somebody realised rather than when it happened. Statutory clocks run from that, which is why it
    is its own field and why nothing computes a deadline from it.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        case = await retention.open_case(
            session,
            context,
            summary="Attendance export emailed to the wrong supplier address.",
            detected_at=datetime.now(UTC) - timedelta(hours=20),
        )

        assert case.reference.startswith("PDB-")
        assert case.severity == BreachSeverity.UNKNOWN
        assert case.state == BreachState.OPEN
        assert case.awareness_at is not None
        #  Nothing decided about notification yet, and null says exactly that.
        assert case.authority_notification_required is None
        assert case.principal_notification_required is None
        await session.rollback()


async def test_a_notification_cannot_be_recorded_before_anybody_decided_one_was_needed(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§6: an Agent *"cannot decide legal notification or send without authorised approval."*

    The product cannot either. A notification recorded with no decision behind it is a notification
    nobody authorised — and the refusal says whose decision it is.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        case = await retention.open_case(session, context, summary="Export sent in error.")

        with pytest.raises(ValidationFailed) as refused:
            await retention.record_notification(
                session,
                context,
                case.id,
                expected_version=case.version,
                audience="authority",
                evidence="Filed on the portal.",
            )
        assert "Privacy or Legal" in str(refused.value)
        await session.rollback()


async def test_the_notification_decision_is_a_persons_and_carries_its_reasoning(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """And the decision *not* to notify is the one that will be questioned.

    Which is why the reason is required either way, and why the decision needs a proved password.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        case = await retention.open_case(session, context, summary="Export sent in error.")

        with pytest.raises(ValidationFailed):
            await retention.decide_notification(
                session,
                context,
                case.id,
                expected_version=case.version,
                authority_required=False,
                principals_required=False,
                reason="   ",
            )

        decided = await retention.decide_notification(
            session,
            context,
            case.id,
            expected_version=case.version,
            authority_required=True,
            principals_required=True,
            reason=(
                "Names and shift times of 41 people reached one external address. Counsel advises "
                "the Board and the affected people are notified."
            ),
        )
        assert decided.notification_decided_by_membership_id == left.membership_id
        assert decided.notification_decided_at is not None
        assert decided.state == BreachState.ASSESSING

        recorded = await retention.record_notification(
            session,
            context,
            case.id,
            expected_version=decided.version,
            audience="authority",
            evidence="Filed on the Board's portal, acknowledgement reference 88213.",
        )
        assert recorded.authority_notified_at is not None
        assert recorded.state == BreachState.NOTIFYING
        await session.rollback()


async def test_a_notification_against_a_decision_not_to_notify_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """If the record says no notification was needed, sending one is a change of decision.

    Recording it as though the decision had been different would leave a case whose trail
    contradicts itself — which is the worst thing a breach file can do.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        case = await retention.open_case(session, context, summary="Two rows visible internally.")
        await retention.decide_notification(
            session,
            context,
            case.id,
            expected_version=case.version,
            authority_required=False,
            principals_required=False,
            reason="Internal only, no personal data left the workspace. Counsel agrees.",
        )

        with pytest.raises(ValidationFailed) as refused:
            await retention.record_notification(
                session,
                context,
                case.id,
                expected_version=case.version,
                audience="principals",
                evidence="Emailed everybody anyway.",
            )
        assert "Change the decision first" in str(refused.value)
        await session.rollback()


async def test_a_case_is_closed_with_a_reason_and_leaves_a_trail(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Every step, in order, and none of them editable afterwards."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        case = await retention.open_case(session, context, summary="Export sent in error.")
        await retention.update_case(
            session,
            context,
            case.id,
            expected_version=case.version,
            changes={"containment": "Recalled the message; supplier confirmed deletion.",
                     "severity": BreachSeverity.MEDIUM.value},
            note="Supplier confirmed deletion in writing within two hours.",
        )

        with pytest.raises(ValidationFailed):
            await retention.close_case(
                session, context, case.id, expected_version=case.version, reason="  "
            )

        closed = await retention.close_case(
            session,
            context,
            case.id,
            expected_version=case.version,
            reason="Contained, notified, and the export step now checks the recipient domain.",
        )
        assert closed.state == BreachState.CLOSED
        assert closed.closed_by_membership_id == left.membership_id

        trail = await retention.case_trail(session, context, case.id)
        assert [step.kind for step in trail] == ["opened", "assessed", "closed"]
        trail[0].detail = "something else"
        with pytest.raises(DatabaseError):
            await session.flush()
        await session.rollback()


async def test_a_case_cannot_be_closed_through_the_ordinary_update(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Closing needs a reason, so it needs its own step. The update path says so rather than
    quietly accepting a state change that would skip the constraint."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        case = await retention.open_case(session, context, summary="Something happened.")

        with pytest.raises(ValidationFailed) as refused:
            await retention.update_case(
                session,
                context,
                case.id,
                expected_version=case.version,
                changes={"state": BreachState.CLOSED.value},
                note="Done.",
            )
        assert "closing step" in str(refused.value)
        await session.rollback()


# ── §7 processors ──────────────────────────────────────────────────────────────────────────


async def test_a_processor_is_proposed_before_it_is_anything_else(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§7: review, contract and customer notice *"before personal data is sent"*.

    A new row cannot arrive active, which is what makes the state a workflow rather than a label.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        processor = await retention.register_processor(
            session,
            context,
            name="Example Mail",
            service="Transactional email delivery",
            purpose="Sending invitations, reset links and digests.",
            processing_role=ProcessorRole.SUBPROCESSOR,
            data_categories="Name and work email address.",
            region="India",
        )

        assert processor.state == ProcessorState.PROPOSED
        assert processor.is_active is False
        assert processor.contract_version is None
        await session.rollback()


async def test_a_processor_is_not_active_without_a_contract_on_record(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A provider marked active with no contract is personal data leaving under no agreement.

    Refused in words here; migration 0045's `ck_processors_active_was_reviewed` refuses it for every
    other path.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        processor = await retention.register_processor(
            session,
            context,
            name="Example Mail",
            service="Email delivery",
            purpose="Invitations and digests.",
            processing_role=ProcessorRole.SUBPROCESSOR,
            data_categories="Name and work email.",
        )

        with pytest.raises(ValidationFailed) as refused:
            await retention.approve_processor(
                session,
                context,
                processor.id,
                expected_version=processor.version,
                contract_version="   ",
                security_review="Reviewed.",
            )
        assert "under what agreement" in str(refused.value)

        approved = await retention.approve_processor(
            session,
            context,
            processor.id,
            expected_version=processor.version,
            contract_version="DPA v3.1, signed 14 August 2026",
            security_review="SOC 2 report reviewed; sub-processor list checked; India region only.",
        )
        assert approved.state == ProcessorState.ACTIVE
        assert approved.is_active is True
        assert approved.reviewed_by_membership_id == left.membership_id

        #  And the table refuses the same thing from any other path.
        approved.contract_version = None
        with pytest.raises(DatabaseError):
            await session.flush()
        await session.rollback()


async def test_retiring_a_processor_requires_the_exit_evidence(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§7: *"export, deletion confirmation and credential/key revocation evidence."*

    A provider marked retired with nothing recorded may still hold the data, which is the state
    everybody assumes is finished and nobody checked.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        processor = await retention.register_processor(
            session,
            context,
            name="Example Mail",
            service="Email delivery",
            purpose="Invitations.",
            processing_role=ProcessorRole.SUBPROCESSOR,
            data_categories="Name and work email.",
        )

        with pytest.raises(ValidationFailed) as refused:
            await retention.retire_processor(
                session,
                context,
                processor.id,
                expected_version=processor.version,
                exit_evidence="  ",
            )
        assert "may still hold the data" in str(refused.value)

        retired = await retention.retire_processor(
            session,
            context,
            processor.id,
            expected_version=processor.version,
            exit_evidence=(
                "Export taken 20 September; deletion confirmed in writing 22 September; API keys "
                "revoked and rotated the same day."
            ),
        )
        assert retired.state == ProcessorState.RETIRED
        assert retired.is_active is False
        await session.rollback()


async def test_a_stale_read_cannot_change_any_of_these(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two people working one incident must not overwrite each other."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        case = await retention.open_case(session, context, summary="Something happened.")

        with pytest.raises(Conflict):
            await retention.update_case(
                session,
                context,
                case.id,
                expected_version=case.version + 3,
                changes={"impact": "Unclear."},
                note="Updating.",
            )
        await session.rollback()


async def test_another_workspace_sees_none_of_it(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Both boundaries: the queries name `tenant_id`, and row-level security is on."""
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        mine = await _context(session, left)
        await _policy(session, mine)
        await retention.open_case(session, mine, summary="Ours alone.")
        await retention.register_processor(
            session,
            mine,
            name="Ours alone",
            service="Something",
            purpose="Something",
            processing_role=ProcessorRole.PROCESSOR,
            data_categories="Something",
        )
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        theirs = await _context(session, right)
        assert await retention.list_policies(session, theirs) == []
        assert await retention.list_cases(session, theirs) == []
        assert await retention.list_processors(session, theirs) == []
        await session.rollback()
