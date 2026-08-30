"""Publishing an Agent — the two gates §9 names, and the version they guard.

    Tests and permission review are publish gates.

Gate 5's exit test says *an Agent publishes only after its tests pass*, and that is the first thing
proved here — not by reading the summary, which is only a report, but by trying to publish and
being refused.

The second thing is subtler and matters more: **a test result belongs to a design**. Recording
five passes and then editing the agent must not leave a publishable thing behind, and the test that
proves it is the one that would have caught the whole feature being wrong.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.agents import agent_publish as publish
from uboss.modules.agents import agent_service as service
from uboss.modules.agents.agent_models import (
    AgentStatus,
    AgentTest,
    AgentVersion,
    SandboxTestKind,
    SandboxTestStatus,
    Situation,
)
from uboss.modules.agents.agent_schemas import (
    AgentCreate,
    AgentStepInput,
    AgentUpdate,
    EscalationRuleInput,
    ToolInput,
)
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for

pytestmark = pytest.mark.anyio


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


async def _grant(session: AsyncSession, workspace: Workspace, *actions: str) -> None:
    for action in actions:
        await session.execute(
            text(
                "INSERT INTO role_permissions (tenant_id, role_id, action) "
                "VALUES (:t, :r, :a) ON CONFLICT DO NOTHING"
            ),
            {"t": workspace.tenant_id, "r": workspace.role_id, "a": action},
        )
    await session.flush()


def _five_passes() -> list[dict[str, object]]:
    """All five of Form 4 section C, each with an observation."""
    return [
        {
            "kind": kind,
            "sample_situation": f"A {kind.value.replace('_', ' ')} situation",
            "expected_result": "The agent does the documented thing",
            "status": SandboxTestStatus.PASS,
            "actual_result": "It did the documented thing",
        }
        for kind in SandboxTestKind
    ]


async def _ready_agent(
    session: AsyncSession,
    context: SecurityContext,
    workspace: Workspace,
    *,
    approver_membership_id: uuid.UUID,
    with_tool: bool = False,
):
    """A draft that would pass both gates, minus whatever the caller wants to break."""
    agent = await service.create(session, context, AgentCreate(name="Invoice agent"))
    await service.update(
        session,
        context,
        agent.id,
        AgentUpdate(
            expected_version=agent.version,
            main_approver_membership_id=approver_membership_id,
            escalation_label="Department Head",
            prohibited_actions="Never approve a payment.",
            steps=[
                AgentStepInput(
                    position=1,
                    agent_action="Match the invoice to the purchase order",
                    must_never_do="Never change a vendor bank account",
                )
            ],
            escalation_rules=[
                EscalationRuleInput(
                    situation=situation, required_action="Stop and report"
                )
                for situation in Situation
            ],
            tools=(
                [ToolInput(position=1, tool="ERP", scopes=["Read"])] if with_tool else []
            ),
        ),
    )
    return agent


# ------------------------------------------------------------------ the tests gate


async def test_an_agent_cannot_publish_until_all_five_tests_pass(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Gate 5's exit test, proved by being refused rather than by reading a summary."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "publish")
        context = await _context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague
        )

        #  Nothing recorded at all.
        with pytest.raises(ValidationFailed) as refused:
            await service.read(session, context, agent.id)
            read = await service.read(session, context, agent.id)
            await publish.submit(session, context, agent.id, read.version)
        assert "have not been written" in str(refused.value)

        #  Four of five pass; the fifth is blocked.
        read = await service.read(session, context, agent.id)
        partial = _five_passes()
        partial[-1]["status"] = SandboxTestStatus.BLOCKED
        partial[-1]["actual_result"] = "The sandbox had no failing system to try"
        await publish.record_tests(
            session, context, agent.id, partial, expected_version=read.version
        )

        read = await service.read(session, context, agent.id)
        with pytest.raises(ValidationFailed) as still_refused:
            await publish.submit(session, context, agent.id, read.version)
        assert "system failure is blocked" in str(still_refused.value)
        await session.rollback()


async def test_a_result_must_say_what_actually_happened(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A `Fail` with no observation is a claim nobody can act on; a `Pass` with none is one
    nobody can check. Held by the schema rather than by whichever service writes the row."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague
        )
        read = await service.read(session, context, agent.id)

        with pytest.raises(IntegrityError):
            await publish.record_tests(
                session,
                context,
                agent.id,
                [
                    {
                        "kind": SandboxTestKind.NORMAL_CASE,
                        "status": SandboxTestStatus.PASS,
                        "actual_result": None,
                    }
                ],
                expected_version=read.version,
            )
        await session.rollback()


async def test_who_ran_a_test_and_when_is_stamped_by_the_server(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A result somebody could backdate or attribute to a colleague is not evidence.

    There is no field on the input for either, which is why this is a property of the contract
    rather than a check against a hostile payload.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague
        )
        read = await service.read(session, context, agent.id)
        written = await publish.record_tests(
            session, context, agent.id, _five_passes(), expected_version=read.version
        )

        assert all(test.run_by_membership_id == context.membership_id for test in written)
        assert all(test.run_at is not None for test in written)
        await session.rollback()


async def test_editing_the_design_clears_every_recorded_result(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The test that matters most here.

    A pass recorded against yesterday's steps says nothing about today's. Without this, somebody
    tests an agent, changes what it does, and publishes it on the strength of the old result — and
    every gate above would have reported green.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague
        )
        read = await service.read(session, context, agent.id)
        await publish.record_tests(
            session, context, agent.id, _five_passes(), expected_version=read.version
        )

        found = await publish.summary(session, context, agent.id)
        assert found.tests_passed == 5
        assert all(gate.passed for gate in found.gates)

        #  Change what the agent does.
        read = await service.read(session, context, agent.id)
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=read.version,
                steps=[
                    AgentStepInput(
                        position=1, agent_action="Post the invoice to the ledger directly"
                    )
                ],
            ),
        )

        after = await publish.summary(session, context, agent.id)
        assert after.tests_passed == 0
        assert not after.gates[0].passed

        #  The tests themselves survive — the situation and expected result are part of the
        #  design. Only what was observed is gone.
        rows = (
            (await session.execute(select(AgentTest).where(AgentTest.agent_id == agent.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 5
        assert all(row.sample_situation for row in rows)
        assert all(row.status == SandboxTestStatus.NOT_RUN for row in rows)
        assert all(row.actual_result is None and row.run_at is None for row in rows)
        await session.rollback()


# ------------------------------------------------------------------ the permission gate


async def test_an_ungranted_tool_stops_the_publish(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """§9's second gate. "We'll sort the access out later" is what it exists to prevent."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague, with_tool=True
        )
        read = await service.read(session, context, agent.id)
        await publish.record_tests(
            session, context, agent.id, _five_passes(), expected_version=read.version
        )

        found = await publish.summary(session, context, agent.id)
        review = next(gate for gate in found.gates if gate.gate == "permission_review")
        assert not review.passed
        assert "ERP" in review.reason

        read = await service.read(session, context, agent.id)
        with pytest.raises(ValidationFailed) as refused:
            await publish.submit(session, context, agent.id, read.version)
        assert "not been reviewed" in str(refused.value)
        await session.rollback()


async def test_granting_the_tool_clears_the_permission_gate(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "manage_access")
        context = await _context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague, with_tool=True
        )
        read = await service.read(session, context, agent.id)
        await service.grant_tool(
            session,
            context,
            agent.id,
            read.tools[0].id,
            granted=True,
            expected_version=read.version,
        )
        read = await service.read(session, context, agent.id)
        await publish.record_tests(
            session, context, agent.id, _five_passes(), expected_version=read.version
        )

        found = await publish.summary(session, context, agent.id)
        assert all(gate.passed for gate in found.gates)
        assert found.granted_tool_count == 1
        await session.rollback()


# ------------------------------------------------------------------ approval


async def test_nobody_approves_their_own_agent(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """*"No Skill or Agent can approve/promote itself."* Nor may the person who submitted it."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "publish")
        context = await _context(session, left)

        #  Named as their own approver, and submitting it themselves.
        agent = await _ready_agent(
            session, context, left, approver_membership_id=context.membership_id
        )
        read = await service.read(session, context, agent.id)
        await publish.record_tests(
            session, context, agent.id, _five_passes(), expected_version=read.version
        )
        read = await service.read(session, context, agent.id)
        await publish.submit(session, context, agent.id, read.version)

        read = await service.read(session, context, agent.id)
        with pytest.raises(PermissionDenied):
            await publish.publish(session, context, agent.id, read.version)
        await session.rollback()


async def test_publishing_freezes_the_design_and_the_agent_points_at_it(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The whole path: record, submit as one person, approve as another, freeze."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        agent = await _ready_agent(
            session, author, left, approver_membership_id=colleague
        )
        read = await service.read(session, author, agent.id)
        await publish.record_tests(
            session, author, agent.id, _five_passes(), expected_version=read.version
        )
        read = await service.read(session, author, agent.id)
        await publish.submit(session, author, agent.id, read.version)

        await _grant(session, left, "publish")
        approver = await _context(session, left, membership_id=colleague)
        read = await service.read(session, approver, agent.id)
        version = await publish.publish(session, approver, agent.id, read.version)

        assert version.version_no == 1
        assert version.approved_by_membership_id == colleague
        assert version.published_by_membership_id == author.membership_id
        assert agent.status == AgentStatus.PUBLISHED
        assert agent.published_version_id == version.id

        #  The snapshot holds the design, the grants and the test results as they stood.
        assert version.snapshot["agent"]["name"] == "Invoice agent"
        assert len(version.snapshot["steps"]) == 1
        assert len(version.snapshot["escalation_rules"]) == 6
        assert len(version.snapshot["tests"]) == 5
        assert all(test["status"] == "pass" for test in version.snapshot["tests"])
        await session.rollback()


async def test_a_published_version_cannot_be_edited_or_deleted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Immutable twice over: a trigger refuses the change, and the privilege was never granted."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        agent = await _ready_agent(
            session, author, left, approver_membership_id=colleague
        )
        read = await service.read(session, author, agent.id)
        await publish.record_tests(
            session, author, agent.id, _five_passes(), expected_version=read.version
        )
        read = await service.read(session, author, agent.id)
        await publish.submit(session, author, agent.id, read.version)
        await _grant(session, left, "publish")
        approver = await _context(session, left, membership_id=colleague)
        read = await service.read(session, approver, agent.id)
        version = await publish.publish(session, approver, agent.id, read.version)
        await session.commit()
        version_id = version.id

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        with pytest.raises((DBAPIError, ProgrammingError)):
            await session.execute(
                text("UPDATE agent_versions SET name = 'rewritten' WHERE id = :i"),
                {"i": version_id},
            )
        await session.rollback()

        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        with pytest.raises((DBAPIError, ProgrammingError)):
            await session.execute(
                text("DELETE FROM agent_versions WHERE id = :i"), {"i": version_id}
            )
        await session.rollback()


async def test_version_numbers_are_gapless(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Version 3 existing with no version 2 would be a published thing nobody can account for."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        await _grant(session, left, "publish")
        author = await _context(session, left)
        agent = await _ready_agent(
            session, author, left, approver_membership_id=colleague
        )

        numbers = []
        for round_no in range(2):
            read = await service.read(session, author, agent.id)
            if read.status is not AgentStatus.DRAFT and read.status is not AgentStatus.NEEDS_REVIEW:
                #  A published agent goes back to a draft before it can be changed again.
                await session.execute(
                    text("UPDATE agents SET status = 'needs_review' WHERE id = :i"),
                    {"i": agent.id},
                )
                await session.flush()
                await session.refresh(agent)
            read = await service.read(session, author, agent.id)
            await service.update(
                session,
                context=author,
                agent_id=agent.id,
                payload=AgentUpdate(
                    expected_version=read.version, purpose=f"Round {round_no}"
                ),
            )
            read = await service.read(session, author, agent.id)
            await publish.record_tests(
                session, author, agent.id, _five_passes(), expected_version=read.version
            )
            read = await service.read(session, author, agent.id)
            await publish.submit(session, author, agent.id, read.version)
            approver = await _context(session, left, membership_id=colleague)
            read = await service.read(session, approver, agent.id)
            version = await publish.publish(session, approver, agent.id, read.version)
            numbers.append(version.version_no)
            author = await _context(session, left)

        assert numbers == [1, 2]
        await session.rollback()


async def test_the_approver_must_have_read_the_version_they_approve(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Approving a version you did not read is not approving."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        agent = await _ready_agent(
            session, author, left, approver_membership_id=colleague
        )
        read = await service.read(session, author, agent.id)
        await publish.record_tests(
            session, author, agent.id, _five_passes(), expected_version=read.version
        )
        read = await service.read(session, author, agent.id)
        await publish.submit(session, author, agent.id, read.version)

        await _grant(session, left, "publish")
        approver = await _context(session, left, membership_id=colleague)
        with pytest.raises(Conflict):
            await publish.publish(session, approver, agent.id, read.version - 1)
        await session.rollback()


# ------------------------------------------------------------------ warnings, not gates


async def test_an_unanswered_situation_warns_and_does_not_block(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """§9 names two gates. Form 4 prints section B without the asterisk it puts on the four
    required header fields, so an unanswered situation is surfaced loudly and does not block —
    inventing a third gate would be inventing a rule nobody approved."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await service.create(session, context, AgentCreate(name="Sparse agent"))
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                main_approver_membership_id=colleague,
                escalation_label="Finance",
                steps=[AgentStepInput(position=1, agent_action="Do the thing")],
                escalation_rules=[
                    EscalationRuleInput(
                        situation=Situation.MANDATORY_INPUT_MISSING,
                        required_action="Ask the user",
                    )
                ],
            ),
        )
        read = await service.read(session, context, agent.id)
        await publish.record_tests(
            session, context, agent.id, _five_passes(), expected_version=read.version
        )

        found = await publish.summary(session, context, agent.id)
        codes = {warning.code for warning in found.warnings}
        assert "situations_unanswered" in codes
        #  Both gates pass, so it is publishable despite the warning.
        assert all(gate.passed for gate in found.gates)

        read = await service.read(session, context, agent.id)
        await publish.submit(session, context, agent.id, read.version)
        assert agent.status == AgentStatus.READY_TO_PUBLISH
        await session.rollback()


async def test_a_tool_used_on_a_step_but_never_listed_is_warned_about(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Access nobody will review, because it never reached the list the review reads."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await service.create(session, context, AgentCreate(name="Quiet reacher"))
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                steps=[
                    AgentStepInput(
                        position=1, agent_action="Look it up", tool_system="Salesforce"
                    )
                ],
            ),
        )
        found = await publish.summary(session, context, agent.id)
        warning = next(
            w for w in found.warnings if w.code == "step_tool_not_listed"
        )
        assert "salesforce" in warning.message.lower()
        await session.rollback()


async def test_the_summary_counts_rows_and_invents_no_readiness_score(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """*"2 of 5 tests pass"* is more use than *"40% ready"* to the person who has to fix it."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague, with_tool=True
        )
        read = await service.read(session, context, agent.id)
        two = _five_passes()[:2]
        await publish.record_tests(
            session, context, agent.id, two, expected_version=read.version
        )

        found = await publish.summary(session, context, agent.id)
        assert (found.tests_passed, found.tests_total) == (2, 5)
        assert (found.tool_count, found.granted_tool_count) == (1, 0)
        assert found.step_count == 1
        assert found.next_action
        assert not found.can_approve
        await session.rollback()


async def test_a_read_only_role_cannot_record_a_test_result(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A person who may not edit the design has no business asserting that it passed."""
    _, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, right)
        with pytest.raises(PermissionDenied):
            await publish.record_tests(
                session, context, uuid.uuid4(), _five_passes(), expected_version=1
            )
        await session.rollback()


async def test_the_person_who_approved_a_version_can_still_be_deleted(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Found while building this, and it applied to `job_versions` too.

    `ON DELETE SET NULL` pointing into an append-only table is a contradiction: removing the person
    makes Postgres try to rewrite the row, the trigger refuses, and the deletion fails. The effect
    was that anybody who had ever approved anything became undeletable — an offboarding blocked by
    a foreign key, and a right-to-erasure request that could not be honoured.

    So the columns carry no foreign key, the same choice `audit_events.actor_membership_id`
    already makes. Who approved this version is a fact about the past, and it survives.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        agent = await _ready_agent(
            session, author, left, approver_membership_id=colleague
        )
        read = await service.read(session, author, agent.id)
        await publish.record_tests(
            session, author, agent.id, _five_passes(), expected_version=read.version
        )
        read = await service.read(session, author, agent.id)
        await publish.submit(session, author, agent.id, read.version)
        await _grant(session, left, "publish")
        approver = await _context(session, left, membership_id=colleague)
        read = await service.read(session, approver, agent.id)
        version = await publish.publish(session, approver, agent.id, read.version)
        await session.commit()
        version_id = version.id

    #  A second person, created and removed here so the fixture's own teardown is not the thing
    #  under test. Written as the owner because `uboss_app` cannot touch `users`.
    async with build_sessionmaker(owner_engine)() as owner:
        await owner.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        await owner.execute(
            text("DELETE FROM membership_roles WHERE membership_id = :m"), {"m": colleague}
        )
        #  This is the statement that used to fail.
        await owner.execute(text("DELETE FROM memberships WHERE id = :m"), {"m": colleague})

        #  The version still names them. Evidence outlives the person's account.
        approver_id = (
            await owner.execute(
                text("SELECT approved_by_membership_id FROM agent_versions WHERE id = :i"),
                {"i": version_id},
            )
        ).scalar_one()
        assert approver_id == colleague
        #  Rolled back: the fixture removes them for real, and this test only proves it can.
        await owner.rollback()


async def test_a_version_is_invisible_to_another_workspace(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        author = await _context(session, left)
        agent = await _ready_agent(
            session, author, left, approver_membership_id=colleague
        )
        read = await service.read(session, author, agent.id)
        await publish.record_tests(
            session, author, agent.id, _five_passes(), expected_version=read.version
        )
        read = await service.read(session, author, agent.id)
        await publish.submit(session, author, agent.id, read.version)
        await _grant(session, left, "publish")
        approver = await _context(session, left, membership_id=colleague)
        read = await service.read(session, approver, agent.id)
        await publish.publish(session, approver, agent.id, read.version)
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(right.tenant_id)}
        )
        assert (await session.execute(select(AgentVersion))).scalars().all() == []
        await session.rollback()
