"""The Agent draft — Form 4's fields, and `PLAN.md` §9's form groups.

Two sources describe this object and both are implemented whole, so this suite's first job is to
prove neither was quietly trimmed: every column of Form 4 section A survives a round trip, all six
of section B's situations are answerable, and each of §9's nine design groups has somewhere to go.

Its second job is the two sentences §9 adds that a schema alone cannot hold:

* *"Tool suggestions never grant access."*
* An Agent runs an **approved version**, not a draft.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.agents import agent_service as service
from uboss.modules.agents.agent_models import (
    Agent,
    AgentStatus,
    AgentTool,
    Direction,
    SharePrincipal,
    Situation,
    AgentAudience,
)
from uboss.modules.agents.agent_schemas import (
    SITUATION_LABELS,
    AgentCreate,
    AgentStepInput,
    AgentUpdate,
    EscalationRuleInput,
    IoSchemaInput,
    KnowledgeSourceInput,
    ShareInput,
    SkillInput,
    ToolInput,
)
from uboss.modules.agents.models import Skill
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.jobs import service as jobs
from uboss.modules.jobs.schemas import JobCreate

pytestmark = pytest.mark.anyio

#: Form 4 section A's nine columns. Named here so a column dropped from the schema fails a test
#: rather than disappearing from a form nobody re-read.
SECTION_A_COLUMNS = (
    "input_used",
    "input_source",
    "tool_system",
    "agent_action",
    "output",
    "output_destination",
    "approval",
    "must_never_do",
)


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


async def _agent(session: AsyncSession, context: SecurityContext, name: str = "Invoice agent"):
    return await service.create(session, context, AgentCreate(name=name))


# ------------------------------------------------------------------ Form 4, kept whole


async def test_every_column_of_form_4_section_a_survives_a_round_trip(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Nine columns on the approved sheet. A dropped one is a question nobody gets asked."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        written = AgentStepInput(
            position=1,
            input_used="Supplier invoice PDF",
            input_source="Shared mailbox",
            tool_system="ERP",
            agent_action="Extract the header and match it to the purchase order",
            output="Matched invoice record",
            output_destination="ERP invoice register",
            approval="Team Lead",
            must_never_do="Never post to the ledger or change a vendor bank account",
        )
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(expected_version=agent.version, steps=[written]),
        )
        read = await service.read(session, context, agent.id)

        assert len(read.steps) == 1
        for column in SECTION_A_COLUMNS:
            assert getattr(read.steps[0], column) == getattr(written, column), column
        await session.rollback()


async def test_all_six_error_situations_can_be_answered_and_are_labelled_as_the_sheet_prints_them(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Form 4 section B prints six rows. A closed set, and each carries the sheet's own words."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                escalation_rules=[
                    EscalationRuleInput(
                        situation=situation,
                        required_action=f"Handle {situation.value}",
                        escalate_to_label="Department Head",
                    )
                    for situation in Situation
                ],
            ),
        )
        read = await service.read(session, context, agent.id)

        assert len(read.escalation_rules) == 6
        assert {rule.situation for rule in read.escalation_rules} == set(Situation)
        assert read.situations_unanswered == []
        #  The labels are the sheet's, not a prettified enum name.
        by_situation = {rule.situation: rule.label for rule in read.escalation_rules}
        assert by_situation[Situation.MANDATORY_INPUT_MISSING] == "Mandatory input missing"
        assert by_situation[Situation.APPROVAL_REJECTED] == "Approval is rejected"
        assert set(by_situation.values()) == set(SITUATION_LABELS.values())
        await session.rollback()


async def test_an_unanswered_situation_is_a_checklist_not_a_refusal(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A form is filled in over time. Refusing the first save would be refusing to let somebody
    start — so the six are reported as what is left, and 5.4 makes them a publish gate."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                escalation_rules=[
                    EscalationRuleInput(
                        situation=Situation.MANDATORY_INPUT_MISSING,
                        required_action="Ask the user",
                    )
                ],
            ),
        )
        read = await service.read(session, context, agent.id)
        assert Situation.MANDATORY_INPUT_MISSING not in read.situations_unanswered
        assert len(read.situations_unanswered) == 5
        await session.rollback()


async def test_one_situation_cannot_have_two_answers(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two answers is two policies, and nothing in the design says which one wins."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        with pytest.raises(ValidationFailed):
            await service.update(
                session,
                context,
                agent.id,
                AgentUpdate(
                    expected_version=agent.version,
                    escalation_rules=[
                        EscalationRuleInput(
                            situation=Situation.TOOL_OR_SYSTEM_FAILS, required_action="Retry"
                        ),
                        EscalationRuleInput(
                            situation=Situation.TOOL_OR_SYSTEM_FAILS, required_action="Escalate"
                        ),
                    ],
                ),
            )
        await session.rollback()


# ------------------------------------------------------------------ §9's groups


async def test_every_form_group_holds_what_section_9_says_it_holds(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Groups 1 to 9 in one save, read back whole.

    Written as one test on purpose: the claim being checked is that the *set* is complete, and
    nine separate tests would each pass while a group was missing from the schema.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                #  1 — identity
                name="Invoice exception agent",
                trigger="New email",
                frequency="Every transaction",
                completion_time_value=30,
                completion_time_unit="Minutes",
                #  2 — purpose, instructions, boundaries, prohibited actions
                purpose="Clear invoice exceptions without a person re-keying them.",
                instructions="Match, then route what cannot be matched.",
                boundaries="Only invoices under the approved value threshold.",
                prohibited_actions="Never approve a payment.",
                #  3 — owner, audience, sharing
                visibility=AgentAudience.SELECTED_USERS,
                shares=[
                    ShareInput(principal_type=SharePrincipal.USER, principal_id=uuid.uuid4())
                ],
                #  4 — multiple input/output schemas
                io_schemas=[
                    IoSchemaInput(
                        position=1,
                        direction=Direction.INPUT,
                        name="invoice",
                        format="PDF",
                        json_schema={"type": "object"},
                    ),
                    IoSchemaInput(
                        position=1,
                        direction=Direction.OUTPUT,
                        name="matched record",
                        format="System Record",
                    ),
                ],
                #  5 — model policy, as a key the gateway resolves
                model_policy_key="finance-default",
                #  6 — knowledge sources and retention
                knowledge_sources=[
                    KnowledgeSourceInput(
                        position=1,
                        name="Approved supplier list",
                        location="ERP",
                        retention_days=365,
                        contains_personal_data=True,
                    )
                ],
                #  7 — tools and explicit scopes
                tools=[ToolInput(position=1, tool="ERP", scopes=["Read", "Update"])],
                #  8 — approval and escalation
                main_approver_label="Department Head",
                escalation_label="Finance",
                #  9 — cost, token, time, concurrency, retries
                cost_cap_minor_units=50000,
                cost_cap_currency="INR",
                token_cap=200000,
                time_limit_seconds=900,
                max_concurrency=2,
                max_retries=3,
            ),
        )
        read = await service.read(session, context, agent.id)

        assert read.name == "Invoice exception agent"
        assert (read.trigger, read.frequency) == ("New email", "Every transaction")
        assert (read.completion_time_value, read.completion_time_unit) == (30, "Minutes")
        assert read.purpose and read.instructions and read.boundaries
        assert read.prohibited_actions == "Never approve a payment."
        assert read.visibility is AgentAudience.SELECTED_USERS
        assert len(read.shares) == 1
        assert {row.direction for row in read.io_schemas} == {Direction.INPUT, Direction.OUTPUT}
        assert read.model_policy_key == "finance-default"
        assert read.knowledge_sources[0].retention_days == 365
        assert read.knowledge_sources[0].contains_personal_data
        assert read.tools[0].scopes == ["Read", "Update"]
        assert read.main_approver_label == "Department Head"
        assert (read.cost_cap_minor_units, read.cost_cap_currency) == (50000, "INR")
        assert (read.token_cap, read.time_limit_seconds) == (200000, 900)
        assert (read.max_concurrency, read.max_retries) == (2, 3)
        await session.rollback()


async def test_an_agent_may_have_more_than_one_input_and_more_than_one_output(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§9 group 4 says *"multiple"*. One column would have made this impossible."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                io_schemas=[
                    IoSchemaInput(position=1, direction=Direction.INPUT, name="invoice"),
                    IoSchemaInput(position=2, direction=Direction.INPUT, name="credit note"),
                    IoSchemaInput(position=1, direction=Direction.OUTPUT, name="record"),
                    IoSchemaInput(position=2, direction=Direction.OUTPUT, name="exception note"),
                ],
            ),
        )
        read = await service.read(session, context, agent.id)
        assert len([r for r in read.io_schemas if r.direction is Direction.INPUT]) == 2
        assert len([r for r in read.io_schemas if r.direction is Direction.OUTPUT]) == 2
        await session.rollback()


async def test_two_inputs_cannot_share_a_name(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A run could not tell which one it was given."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        with pytest.raises(ValidationFailed):
            await service.update(
                session,
                context,
                agent.id,
                AgentUpdate(
                    expected_version=agent.version,
                    io_schemas=[
                        IoSchemaInput(position=1, direction=Direction.INPUT, name="Invoice"),
                        IoSchemaInput(position=2, direction=Direction.INPUT, name="invoice"),
                    ],
                ),
            )
        await session.rollback()


# ------------------------------------------------------------------ tool suggestions


async def test_saving_a_form_proposes_a_tool_and_never_grants_it(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§9: *"Tool suggestions never grant access."*

    There is no `granted` field on the input at all, so this is not a rule the service enforces
    against a hostile payload — it is a rule the contract makes unstatable.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                tools=[
                    ToolInput(position=1, tool="Outlook", scopes=["Send"], purpose="Reply"),
                ],
            ),
        )
        read = await service.read(session, context, agent.id)
        assert read.tools[0].granted is False
        assert read.tools[0].granted_by_membership_id is None
        assert read.tools[0].granted_at is None
        await session.rollback()


async def test_granting_a_tool_needs_manage_access_not_edit_draft(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Designing an agent and deciding what it may reach are different authorities.

    The fixture's role holds `edit_draft`; it does not hold `manage_access` until this test grants
    it, which is the point being made.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                tools=[ToolInput(position=1, tool="ERP", scopes=["Read"])],
            ),
        )
        read = await service.read(session, context, agent.id)
        tool_id = read.tools[0].id

        with pytest.raises(PermissionDenied):
            await service.grant_tool(
                session,
                context,
                agent.id,
                tool_id,
                granted=True,
                expected_version=read.version,
            )
        await session.rollback()


async def test_a_granted_tool_records_who_granted_it_and_when(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """An access review should read a name and a time, not infer both from a form's history."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "manage_access")
        context = await _context(session, left)

        agent = await _agent(session, context)
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                tools=[ToolInput(position=1, tool="ERP", scopes=["Read"])],
            ),
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
        after = await service.read(session, context, agent.id)
        assert after.tools[0].granted is True
        assert after.tools[0].granted_by_membership_id == context.membership_id
        assert after.tools[0].granted_at is not None
        await session.rollback()


async def test_editing_the_form_keeps_a_grant_but_widening_the_scopes_does_not(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two failures avoided at once.

    A save that dropped grants would make re-granting a habit rather than a decision. A save that
    kept a grant across a scope change would let somebody widen an agent's access by editing a
    form — so the grant is carried over only while the scopes are exactly what was granted.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _grant(session, left, "manage_access")
        context = await _context(session, left)

        agent = await _agent(session, context)
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                tools=[ToolInput(position=1, tool="ERP", scopes=["Read"])],
            ),
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

        #  An unrelated edit: the grant survives.
        read = await service.read(session, context, agent.id)
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=read.version,
                purpose="Now with a purpose",
                tools=[ToolInput(position=1, tool="ERP", scopes=["Read"], purpose="Look up")],
            ),
        )
        assert (await service.read(session, context, agent.id)).tools[0].granted is True

        #  Widening the scopes: the grant does not.
        read = await service.read(session, context, agent.id)
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=read.version,
                tools=[ToolInput(position=1, tool="ERP", scopes=["Read", "Update"])],
            ),
        )
        after = await service.read(session, context, agent.id)
        assert after.tools[0].scopes == ["Read", "Update"]
        assert after.tools[0].granted is False
        await session.rollback()


async def test_a_tool_with_no_scope_is_refused_by_the_contract(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A tool with no scope is a tool with every scope. §9 says *"explicit scopes"*."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ToolInput(position=1, tool="ERP", scopes=[])


# ------------------------------------------------------------------ approved versions


async def test_an_agent_takes_the_jobs_published_version_rather_than_asking(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Form 4 is *"generated from Forms 2 and 3"*.

    A person who has chosen the job should not have to find its version number too — nor be able
    to pick a different one by accident.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await jobs.create(session, context, JobCreate(name="Invoice matching"))
        agent = await service.create(
            session, context, AgentCreate(name="Invoice agent", job_id=job.id)
        )
        #  The job has no published version yet, so there is nothing to carry — and the Agent says
        #  so rather than inventing one.
        assert agent.job_version_id is None
        assert agent.job_id == job.id
        await session.rollback()


async def test_a_running_agent_must_name_the_version_it_runs(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Operation runs only approved, immutable versions. Held by the schema, not by a service."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)
        await session.flush()

        with pytest.raises(IntegrityError):
            await session.execute(
                text("UPDATE agents SET status = 'published' WHERE id = :i"), {"i": agent.id}
            )
            await session.flush()
        await session.rollback()


# ------------------------------------------------------------------ skills


async def test_a_skill_is_attached_with_the_decision_that_chose_it(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """*"Why does this agent use that skill"* should be answerable from the record."""
    left, _ = two_workspaces
    marker = uuid.uuid4().hex[:6].upper()
    async with build_sessionmaker(owner_engine)() as owner:
        owner.add(
            Skill(
                tenant_id=None,
                catalogue_id=f"A-{marker}",
                name="Invoice exception triage",
                layer="Universal Department",
                exclusions="Do not approve payment.",
            )
        )
        await owner.commit()

    try:
        async with build_sessionmaker(app_engine)() as session:
            context = await _context(session, left)
            skill_id = (
                await session.execute(
                    select(Skill.id).where(Skill.catalogue_id == f"A-{marker}")
                )
            ).scalar_one()

            agent = await _agent(session, context)
            await service.update(
                session,
                context,
                agent.id,
                AgentUpdate(
                    expected_version=agent.version,
                    skills=[SkillInput(position=1, skill_id=skill_id, notes="Closest fit")],
                ),
            )
            read = await service.read(session, context, agent.id)

            assert len(read.skills) == 1
            assert read.skills[0].skill_id == skill_id
            #  The exclusions come with it: what the skill is *not* for is what stops a plausible
            #  choice from being the wrong one, and no gate decides it.
            assert read.skills[0].exclusions == "Do not approve payment."
            await session.rollback()
    finally:
        async with build_sessionmaker(owner_engine)() as owner:
            await owner.execute(
                text("DELETE FROM skills WHERE catalogue_id = :c"), {"c": f"A-{marker}"}
            )
            await owner.commit()


async def test_the_same_skill_cannot_be_attached_twice(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    left, _ = two_workspaces
    marker = uuid.uuid4().hex[:6].upper()
    async with build_sessionmaker(owner_engine)() as owner:
        owner.add(
            Skill(
                tenant_id=None,
                catalogue_id=f"D-{marker}",
                name="Duplicate check",
                layer="Universal Department",
            )
        )
        await owner.commit()

    try:
        async with build_sessionmaker(app_engine)() as session:
            context = await _context(session, left)
            skill_id = (
                await session.execute(
                    select(Skill.id).where(Skill.catalogue_id == f"D-{marker}")
                )
            ).scalar_one()
            agent = await _agent(session, context)

            with pytest.raises(ValidationFailed):
                await service.update(
                    session,
                    context,
                    agent.id,
                    AgentUpdate(
                        expected_version=agent.version,
                        skills=[
                            SkillInput(position=1, skill_id=skill_id),
                            SkillInput(position=2, skill_id=skill_id),
                        ],
                    ),
                )
            await session.rollback()
    finally:
        async with build_sessionmaker(owner_engine)() as owner:
            await owner.execute(
                text("DELETE FROM skills WHERE catalogue_id = :c"), {"c": f"D-{marker}"}
            )
            await owner.commit()


# ------------------------------------------------------------------ sharing


async def test_only_me_with_a_share_list_is_refused_rather_than_half_applied(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two answers to one question. Preferring either would discard somebody's intention."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)

        with pytest.raises(ValidationFailed):
            await service.update(
                session,
                context,
                agent.id,
                AgentUpdate(
                    expected_version=agent.version,
                    visibility=AgentAudience.ONLY_ME,
                    shares=[
                        ShareInput(principal_type=SharePrincipal.TEAM, label="Finance team")
                    ],
                ),
            )
        await session.rollback()


async def test_a_new_agent_is_visible_to_nobody_else(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The plan's decision table: *"Personal Agent visibility | Only me."*

    A default that shared by accident is the one mistake this field cannot afford.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)
        assert agent.visibility == AgentAudience.ONLY_ME
        await session.rollback()


# ------------------------------------------------------------------ the usual guarantees


async def test_a_stale_save_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Optimistic concurrency, or the second save quietly discards the first."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)
        await service.update(
            session, context, agent.id, AgentUpdate(expected_version=agent.version, purpose="a")
        )

        with pytest.raises(Conflict):
            await service.update(
                session,
                context,
                agent.id,
                AgentUpdate(expected_version=agent.version - 1, purpose="b"),
            )
        await session.rollback()


async def test_an_agent_is_invisible_to_another_workspace(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Row-level security, asked directly rather than through the service that also filters."""
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await _agent(session, context)
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(right.tenant_id)}
        )
        assert (await session.execute(select(Agent))).scalars().all() == []
        await session.rollback()


async def test_editing_writes_an_audit_event_naming_fields_and_never_their_values(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """An Agent carries a company's method and its instructions to a model.

    An audit trail is not the place to keep a second copy of either.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)
        await service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=agent.version,
                instructions="Something confidential about how this company works",
            ),
        )
        await session.flush()

        detail = (
            await session.execute(
                text(
                    "SELECT detail FROM audit_events "
                    "WHERE tenant_id = :t AND action = 'agent.updated'"
                ),
                {"t": left.tenant_id},
            )
        ).scalar_one()
        assert detail["fields"] == ["instructions"]
        assert "Something confidential" not in str(detail)
        await session.rollback()


async def test_an_archived_agent_cannot_be_edited(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        agent = await _agent(session, context)
        await service.archive(session, context, agent.id, agent.version)

        with pytest.raises(ValidationFailed):
            await service.update(
                session,
                context,
                agent.id,
                AgentUpdate(expected_version=agent.version, purpose="too late"),
            )
        assert agent.status == AgentStatus.ARCHIVED
        await session.rollback()


async def test_a_read_only_role_cannot_create_an_agent(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The right-hand workspace holds `view` and nothing else."""
    _, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, right)
        with pytest.raises(PermissionDenied):
            await service.create(session, context, AgentCreate(name="Not allowed"))
        await session.rollback()
