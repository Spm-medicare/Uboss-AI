"""A private skill, from the gap the resolver found to the version it can select.

`PLAN.md` §39's flow, and these tests follow it in order:

    → Create private Skill Draft → Sandbox tests → Human approval → Versioned active Skill

The two that matter most are at the end. **Nothing approves itself** — §39 says it about skills as
well as agents, and it is the one rule a Factory makes possible to break. And **a draft cannot be
approved into uselessness**: every field the submit gate demands is a field one of the resolver's
gates reads, so a skill published without its `source_ids` would be refused by every resolution for
the rest of its life. That gate is tested here because it is the difference between a skill and a
row.
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
from uboss.core.permissions import Action
from uboss.db.base import build_sessionmaker
from uboss.modules.agents import factory, factory_publish
from uboss.modules.agents.models import (
    Skill,
    SkillStatus,
    SkillTest,
    SkillTestKind,
    SkillVersion,
)
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for

pytestmark = pytest.mark.anyio

#  `colleague` comes from `tests/conftest.py`: a second person in the left workspace, created on
#  the owner connection because `uboss_app` cannot write to `users` — migration 0006 took that
#  privilege away. Separation of duty needs two people, so this file needs the fixture.

#: Everything `factory.REQUIRED` asks for, so a test that is about approval is not also about
#: filling a form in. Each value is the kind of sentence the field actually wants.
COMPLETE = {
    "purpose": "Check a supplier invoice against its purchase order before it reaches payment.",
    "positive_trigger": "A supplier invoice arrives and a purchase order exists for it.",
    "exclusions": "Not for credit notes, and not for invoices with no purchase order at all.",
    "minimum_inputs": "The invoice, the purchase order number and the goods receipt.",
    "primary_if": "The invoice total is within tolerance of the purchase order",
    "primary_then": "Mark it matched and pass it to payment preparation",
    "output": "A matched-or-queried decision with the three figures it compared.",
    "validation_gate": "A second person checks any invoice queried for more than 5% variance.",
    "source_ids": "SOP-FIN-014; the purchase-to-pay policy, clause 6.",
}


async def _context(
    session: AsyncSession, workspace: Workspace, *, membership_id: uuid.UUID | None = None
) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, membership_id or workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = datetime.now(UTC)
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        email="person@test",
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        org_node_id=membership.org_node_id,
        policy_grants=ceiling,
        step_up_at=now,
        step_up_expires_at=now + timedelta(minutes=10),
    )


async def _ready(
    session: AsyncSession,
    workspace: Workspace,
    context: SecurityContext,
    *,
    name: str = "Invoice to purchase-order match",
) -> Skill:
    """A draft with everything the submit gate wants: fields, one rule, six passing tests."""
    skill = await factory.create(session, context, name=name)
    await factory.update(
        session,
        context,
        skill.id,
        expected_version=skill.version,
        changes=dict(COMPLETE),
        rules=[
            {
                "condition_type": "primary decision",
                "if_clause": "The totals agree within tolerance",
                "then_clause": "Mark matched",
                "failure_state": "QUERIED — variance outside tolerance",
            }
        ],
    )
    for kind in SkillTestKind:
        await factory.set_test(
            session,
            context,
            skill.id,
            kind=kind.value,
            sample_situation=f"The {kind.value.replace('_', ' ')} situation.",
            expected_result="What should happen.",
        )
        await factory.record_result(
            session,
            context,
            skill.id,
            kind=kind.value,
            status="pass",
            observed="It did what it should.",
        )
    return skill


# ── creating ──────────────────────────────────────────────────────────────────────────────


async def test_a_draft_starts_from_a_name_alone(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A form demanding ten fields before it saves anything sends people to a text file.

    The gates are checked when they matter — at submission — and `factory.REQUIRED` says why each
    one is there. Starting is cheap on purpose.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        skill = await factory.create(session, context, name="  Invoice matcher  ")

        assert skill.name == "Invoice matcher", "trimmed"
        assert skill.status == SkillStatus.DRAFT
        assert skill.tenant_id == left.tenant_id, "private to this workspace"
        assert skill.catalogue_id is None, "not one of the 400"
        assert skill.owner_membership_id == left.membership_id
        assert skill.is_editable is True
        await session.rollback()


async def test_a_catalogue_skill_cannot_be_edited_by_a_tenant(
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """The 400 are shared. One organisation editing them would edit them for everybody.

    Refused as *not found* rather than as *not yours*: a message that distinguishes the two tells
    an outsider which ids are real. The read policy still returns catalogue rows to search — this
    is the write path, and it is a different question.
    """
    left, _right = two_workspaces

    #  One catalogue row, written on the owner connection — which is the only thing that can write
    #  one. The seed import owns the real 400 and does not run in the test database, and a test
    #  that skipped itself when they were absent would be a security test nobody notices switching
    #  off.
    async with build_sessionmaker(owner_engine)() as session:
        catalogue_id = (
            await session.execute(
                text(
                    "INSERT INTO skills (catalogue_id, name, layer, status) "
                    "VALUES ('U-999', 'A shared catalogue skill', 'Universal Department', "
                    "'published') RETURNING id"
                )
            )
        ).scalar_one()
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        with pytest.raises(NotFound):
            await factory.update(
                session,
                context,
                catalogue_id,
                expected_version=1,
                changes={"purpose": "Something else"},
            )
        await session.rollback()

    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(text("DELETE FROM skills WHERE id = :id"), {"id": catalogue_id})
        await session.commit()


# ── the tests, and what a save costs ──────────────────────────────────────────────────────


async def test_saving_the_draft_clears_every_test_result(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A pass recorded against yesterday's rules says nothing about today's.

    Choosing which edits "do not count" is exactly the judgement that lets a stale pass through, so
    none of them do. The Agent's tests and the Supervisor's simulations already work this way.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        skill = await _ready(session, left, context)

        summary = await factory_publish.summary(session, context, skill.id)
        assert summary.tests_passed == 6

        await factory.update(
            session,
            context,
            skill.id,
            expected_version=skill.version,
            changes={"primary_then": "Mark matched and notify the buyer"},
        )

        after = await factory_publish.summary(session, context, skill.id)
        assert after.tests_passed == 0, "the design changed, so the results are gone"
        assert any(gap.field.startswith("test.") for gap in after.gaps)
        await session.rollback()


async def test_a_result_needs_an_observation(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A pass nobody can check is not evidence, and a fail nobody can act on is not either.

    There is no sandbox runtime for a skill yet, so a result is a person's account of running it.
    That is acceptable — recorded with their name and the time — and it is only acceptable if it
    says what happened.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        skill = await factory.create(session, context, name="Invoice matcher")
        await factory.set_test(
            session,
            context,
            skill.id,
            kind="golden",
            sample_situation="An ordinary invoice.",
            expected_result="Matched.",
        )

        with pytest.raises(ValidationFailed):
            await factory.record_result(
                session, context, skill.id, kind="golden", status="pass", observed="   "
            )

        #  And the row itself refuses one, if a future caller ever skips the service.
        test = (
            await session.execute(
                select(SkillTest).where(SkillTest.skill_id == skill.id)
            )
        ).scalar_one()
        test.status = "pass"
        test.actual_result = None
        with pytest.raises(DatabaseError):
            await session.flush()
        await session.rollback()


async def test_rewriting_a_test_clears_its_own_result(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Yesterday's outcome does not belong to today's question."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        skill = await factory.create(session, context, name="Invoice matcher")
        await factory.set_test(
            session, context, skill.id, kind="negative", sample_situation="A credit note.",
            expected_result="Declined.",
        )
        await factory.record_result(
            session, context, skill.id, kind="negative", status="pass", observed="Declined it."
        )

        await factory.set_test(
            session, context, skill.id, kind="negative", sample_situation="A credit note with a "
            "purchase order.", expected_result="Declined, with the reason.",
        )

        test = (
            await session.execute(select(SkillTest).where(SkillTest.skill_id == skill.id))
        ).scalar_one()
        assert test.status == "not_run"
        assert test.actual_result is None
        assert test.run_at is None
        await session.rollback()


# ── the submit gate ───────────────────────────────────────────────────────────────────────


async def test_an_incomplete_draft_cannot_be_sent(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """And the refusal names the field and what it is for.

    Every entry in `factory.REQUIRED` is read by one of the resolver's gates. A skill missing one
    can be approved and then never selected, which is worse than a refusal because nobody finds out
    for months.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        skill = await factory.create(session, context, name="Half a skill")
        await factory_publish.set_approver(
            session, context, skill.id, colleague, expected_version=skill.version
        )

        summary = await factory_publish.summary(session, context, skill.id)
        assert summary.can_submit is False
        #  Nine fields plus the rules plus six tests.
        assert len(summary.gaps) >= 10
        assert any(gap.field == "source_ids" for gap in summary.gaps)

        with pytest.raises(ValidationFailed):
            await factory_publish.submit(
                session, context, skill.id, expected_version=skill.version
            )
        await session.rollback()


async def test_a_skill_with_no_evidence_source_is_refused_and_told_why(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The gate that saves a skill from being approved into uselessness.

    `source_ids` is what the resolver's `evidence` gate reads — E06 *"UNVERIFIED — no trace"*. A
    skill published without one passes review and is then refused by every resolution afterwards.
    The refusal says so, in the sentence somebody needs to act on it.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        skill = await _ready(session, left, context)
        await factory_publish.set_approver(
            session, context, skill.id, colleague, expected_version=skill.version
        )
        #  Everything else is answered; only the trace is missing.
        await factory.update(
            session,
            context,
            skill.id,
            expected_version=skill.version,
            changes={"source_ids": None},
        )

        summary = await factory_publish.summary(session, context, skill.id)
        gap = next(gap for gap in summary.gaps if gap.field == "source_ids")
        assert "evidence gate" in gap.remedy
        assert "refused by every resolution" in gap.remedy
        await session.rollback()


async def test_a_complete_draft_can_be_sent_and_taken_back(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The happy path, and the way back from it.

    Withdrawing is available to whoever may edit — work does not stop because somebody is away.
    What is refused is *approving*, which is a different act.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        skill = await _ready(session, left, context)
        await factory_publish.set_approver(
            session, context, skill.id, colleague, expected_version=skill.version
        )

        summary = await factory_publish.summary(session, context, skill.id)
        assert summary.gaps == []
        assert summary.can_submit is True

        await factory_publish.submit(session, context, skill.id, expected_version=skill.version)
        assert skill.status == SkillStatus.READY_TO_PUBLISH
        assert skill.submitted_by_membership_id == left.membership_id
        assert skill.submitted_at is not None

        #  The design holds still while it waits.
        with pytest.raises(ValidationFailed):
            await factory.update(
                session,
                context,
                skill.id,
                expected_version=skill.version,
                changes={"purpose": "Something else"},
            )

        await factory_publish.withdraw(session, context, skill.id, expected_version=skill.version)
        assert skill.status == SkillStatus.DRAFT
        assert skill.submitted_by_membership_id is None
        await session.rollback()


# ── nothing approves itself ───────────────────────────────────────────────────────────────


async def test_the_person_who_sent_it_cannot_approve_it(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§39: *"No Skill or Agent can approve/promote itself."*

    The check that makes the rule real. Somebody who names themselves as approver and submits their
    own skill has arranged a review with nobody in it — so the refusal is on the *approve*, where
    the decision would be, rather than on naming an approver, which is an ordinary act.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        skill = await _ready(session, left, context)
        await factory_publish.set_approver(
            session, context, skill.id, left.membership_id, expected_version=skill.version
        )
        await factory_publish.submit(session, context, skill.id, expected_version=skill.version)

        summary = await factory_publish.summary(session, context, skill.id)
        assert summary.can_approve is False

        with pytest.raises(PermissionDenied) as refused:
            await factory_publish.approve(
                session, context, skill.id, expected_version=skill.version
            )
        assert "not yours to make" in str(refused.value)
        await session.rollback()


async def test_somebody_it_was_not_sent_to_cannot_approve_it(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Holding `publish` is not the same as being asked.

    The author is the one trying here, and they hold exactly the same role as the approver — so
    what refuses them is *who the draft was sent to*, not their permissions. That check runs before
    the self-approval check, and this test pins the order: a person who is not the approver hears
    that first, which is the more useful of the two sentences.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        skill = await _ready(session, left, author)
        await factory_publish.set_approver(
            session, author, skill.id, colleague, expected_version=skill.version
        )
        await factory_publish.submit(session, author, skill.id, expected_version=skill.version)

        assert Action.PUBLISH in author.granted_actions, "so this is not about permissions"

        with pytest.raises(PermissionDenied) as refused:
            await factory_publish.approve(
                session, author, skill.id, expected_version=skill.version
            )
        assert "sent to somebody else" in str(refused.value)
        await session.rollback()


async def test_approval_freezes_a_version_and_activates_the_skill(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """*"→ Versioned active Skill."*

    The snapshot is assembled from rows, not from the request, and it holds the six test results —
    because *"approved with all six passing"* is the claim the row exists to support.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        skill = await _ready(session, left, author)
        await factory_publish.set_approver(
            session, author, skill.id, colleague, expected_version=skill.version
        )
        await factory_publish.submit(session, author, skill.id, expected_version=skill.version)

        approver = await _context(session, left, membership_id=colleague)
        version = await factory_publish.approve(
            session, approver, skill.id, expected_version=skill.version
        )

        assert version.version_no == 1
        assert version.approved_by_membership_id == colleague
        assert version.published_by_membership_id == left.membership_id
        assert skill.status == SkillStatus.PUBLISHED
        assert skill.published_version_id == version.id
        assert skill.approved_by_membership_id == colleague
        assert skill.approved_at is not None

        snapshot = version.snapshot
        assert snapshot["source_ids"] == COMPLETE["source_ids"]
        assert len(snapshot["rules"]) == 1
        assert len(snapshot["tests"]) == 6
        assert {test["status"] for test in snapshot["tests"]} == {"pass"}

        #  And it is not editable any more.
        assert skill.is_editable is False
        await session.rollback()


async def test_a_frozen_version_cannot_be_rewritten(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """*"Published versions are immutable."* Two independent refusals, as everywhere else.

    The trigger stops a change written by mistake; the withheld privilege stops one written on
    purpose. This runs as the application role, so it meets whichever refuses first.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        skill = await _ready(session, left, author)
        await factory_publish.set_approver(
            session, author, skill.id, colleague, expected_version=skill.version
        )
        await factory_publish.submit(session, author, skill.id, expected_version=skill.version)
        approver = await _context(session, left, membership_id=colleague)
        version = await factory_publish.approve(
            session, approver, skill.id, expected_version=skill.version
        )
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        frozen = await session.get(SkillVersion, version.id)
        assert frozen is not None
        frozen.name = "Renamed after the fact"
        with pytest.raises(DatabaseError):
            await session.flush()
        await session.rollback()


async def test_a_stale_read_cannot_be_approved(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """An approver approves what they read. If it moved, they read something else."""
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        skill = await _ready(session, left, author)
        await factory_publish.set_approver(
            session, author, skill.id, colleague, expected_version=skill.version
        )
        await factory_publish.submit(session, author, skill.id, expected_version=skill.version)

        approver = await _context(session, left, membership_id=colleague)
        with pytest.raises(Conflict):
            await factory_publish.approve(
                session, approver, skill.id, expected_version=skill.version - 1
            )
        await session.rollback()


async def test_another_workspace_cannot_reach_this_skill(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The boundary, asserted from the other side rather than from mine.

    Both boundaries hold here: the query names `tenant_id`, and row-level security is enforced on
    the application role this test uses.
    """
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        skill = await factory.create(session, context, name="Ours alone")
        await session.commit()
        skill_id = skill.id

    async with build_sessionmaker(app_engine)() as session:
        theirs = await _context(session, right)
        with pytest.raises(NotFound):
            await factory.read(session, theirs, skill_id)
        with pytest.raises(NotFound):
            await factory_publish.summary(session, theirs, skill_id)
        listed = await factory.list_drafts(session, theirs)
        assert skill_id not in {card.id for card in listed.drafts}
        await session.rollback()

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        row = await session.get(Skill, skill_id)
        if row is not None:
            await session.delete(row)
            await session.commit()
