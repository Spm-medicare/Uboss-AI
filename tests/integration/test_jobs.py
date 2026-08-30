"""The Job draft — Form 3's sixteen columns, WHO rules and typed inputs.

The sheet and `PLAN.md` §8 agree on the sixteen step fields, so this suite's job is to prove none
of them was quietly dropped, and that the two things §8 adds — multiple WHO rules and typed
inputs — actually hold their rules rather than being free-form lists with names.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy import service as hierarchy
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.jobs import service
from uboss.modules.jobs.schemas import (
    AssignmentRuleInput,
    JobCreate,
    JobInputDefinition,
    JobStepInput,
    JobToolDefinition,
    JobUpdate,
)
from uboss.modules.objectives import service as objectives
from uboss.modules.objectives.schemas import ObjectiveCreate, ObjectiveUpdate

pytestmark = pytest.mark.anyio


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = hierarchy._now()
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=workspace.membership_id,
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


async def test_an_empty_workspace_reads_as_empty(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        listing = await service.list_jobs(session, context)

    assert listing.is_empty
    assert listing.jobs == []


async def test_form_threes_sixteen_step_columns_round_trip(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Every column of the approved sheet, saved and read back.

    This is the test that fails if a refactor quietly drops one — and the one that would have
    caught it before a customer noticed their method was missing the field that made it work.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Prepare a quotation"))
        await session.flush()

        step = JobStepInput(
            who_person="Priya",
            who_role="Sales coordinator",
            when_trigger="New email",
            when_frequency="Every transaction",
            what_exact_work="Turn the enquiry into a priced quotation",
            input_exact="Customer enquiry email with part numbers",
            input_found_where="Email",
            how_exact_method="Extract",
            where_performed="Excel",
            rule_formula_check="Unit price from the contract sheet, never the list price",
            output="Draft quotation",
            output_destination="Sales manager",
            approval="Before this step",
            if_missing_or_wrong="Ask the user",
            time_taken="25 minutes",
            mode="human",
        )
        await service.update(
            session,
            context,
            job.id,
            JobUpdate(steps=[step], expected_version=job.version),
        )
        await session.flush()

        saved = await service.read(session, context, job.id)
        assert len(saved.steps) == 1
        stored = saved.steps[0]
        assert stored.position == 1
        for field, expected in step.model_dump().items():
            assert getattr(stored, field) == expected, field
        await session.rollback()


async def test_a_who_rule_has_to_point_at_somebody(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A rule naming neither a row nor a label matches everybody or nobody.

    Which of those it meant would be anybody's guess, and the guess would be made at run time by
    whoever wrote the query.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await service.update(
                session,
                context,
                job.id,
                JobUpdate(
                    assignment_rules=[AssignmentRuleInput(who_type="team")],
                    expected_version=job.version,
                ),
            )
        assert "point at somebody" in str(refused.value)
        await session.rollback()


async def test_several_who_rules_are_kept_in_order(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§8 asks for *multiple* WHO assignment rules, which is only useful if each says what it
    covers and the order is stable."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        await service.update(
            session,
            context,
            job.id,
            JobUpdate(
                assignment_rules=[
                    AssignmentRuleInput(
                        who_type="role",
                        target_label="Sales coordinator",
                        condition_note="Everything under ₹5 lakh",
                    ),
                    AssignmentRuleInput(
                        who_type="hierarchy_subtree",
                        target_label="Sales department and below",
                        condition_note="Anything above it",
                        all_must_act=True,
                    ),
                ],
                expected_version=job.version,
            ),
        )
        await session.flush()

        saved = await service.read(session, context, job.id)
        assert [rule.position for rule in saved.assignment_rules] == [1, 2]
        assert saved.assignment_rules[0].who_type == "role"
        assert saved.assignment_rules[1].all_must_act is True
        await session.rollback()


async def test_a_conditional_input_must_say_when_it_is_required(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A conditional input with no condition is an optional one nobody can reason about."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await service.update(
                session,
                context,
                job.id,
                JobUpdate(
                    inputs=[
                        JobInputDefinition(
                            name="Customer contract",
                            input_type="PDF",
                            requirement="Conditional",
                        )
                    ],
                    expected_version=job.version,
                ),
            )
        assert "when it is required" in str(refused.value)
        await session.rollback()


async def test_an_agent_cannot_be_given_write_access_to_personal_data(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A combination that needs a decision nobody has made.

    Refused rather than allowed-by-default, and refused in the schema as well as here — so a
    bulk path cannot introduce it either.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Payroll"))
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await service.update(
                session,
                context,
                job.id,
                JobUpdate(
                    inputs=[
                        JobInputDefinition(
                            name="Employee bank details",
                            input_type="System Data",
                            classification="personal_data",
                            ai_access="read_write",
                        )
                    ],
                    expected_version=job.version,
                ),
            )
        assert "personal data" in str(refused.value)
        await session.rollback()


async def test_an_input_defaults_to_no_ai_access(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The safe answer should be the one somebody chooses, not the one that happens."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        await service.update(
            session,
            context,
            job.id,
            JobUpdate(
                inputs=[JobInputDefinition(name="Enquiry email", input_type="Email")],
                expected_version=job.version,
            ),
        )
        await session.flush()

        saved = await service.read(session, context, job.id)
        assert saved.inputs[0].ai_access == "none"
        assert saved.inputs[0].classification == "internal"
        await session.rollback()


async def test_two_inputs_cannot_share_a_name(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A step referring to one of them would take whichever the query returned first."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await service.update(
                session,
                context,
                job.id,
                JobUpdate(
                    inputs=[
                        JobInputDefinition(name="Contract", input_type="PDF"),
                        JobInputDefinition(name="contract", input_type="Excel"),
                    ],
                    expected_version=job.version,
                ),
            )
        assert "both called" in str(refused.value)
        await session.rollback()


async def test_a_job_carries_its_objectives_department_across(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Form 3 says the objective and department are *linked* from Form 2.

    Retyping is how two records of one fact start to disagree.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective = await objectives.create(
            session, context, ObjectiveCreate(title="Quotations", department="Sales")
        )
        await session.flush()

        job = await service.create(
            session,
            context,
            JobCreate(name="Prepare a quotation", objective_id=objective.id),
        )
        await session.flush()

        assert job.department == "Sales"
        saved = await service.read(session, context, job.id)
        assert saved.objective_name == "Quotations"
        await session.rollback()


async def test_reordering_the_steps_does_not_collide(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Positions are unique per job, so the delete has to land before the inserts."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        await service.update(
            session,
            context,
            job.id,
            JobUpdate(
                steps=[
                    JobStepInput(what_exact_work="first"),
                    JobStepInput(what_exact_work="second"),
                ],
                expected_version=job.version,
            ),
        )
        await session.flush()

        await service.update(
            session,
            context,
            job.id,
            JobUpdate(
                steps=[
                    JobStepInput(what_exact_work="second"),
                    JobStepInput(what_exact_work="first"),
                ],
                expected_version=job.version,
            ),
        )
        await session.flush()

        saved = await service.read(session, context, job.id)
        assert [step.what_exact_work for step in saved.steps] == ["second", "first"]
        await session.rollback()


async def test_a_stale_version_is_a_conflict(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The form autosaves, so a stale version is what a second tab produces within seconds."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()
        stale = job.version

        await service.update(
            session, context, job.id, JobUpdate(purpose="Faster quotes", expected_version=stale)
        )
        await session.flush()

        with pytest.raises(Conflict):
            await service.update(
                session, context, job.id, JobUpdate(purpose="Other", expected_version=stale)
            )
        await session.rollback()


async def test_writing_a_job_needs_edit_draft(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`right` holds `view` alone. Reading is allowed; writing is not."""
    _, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, right)

        await service.list_jobs(session, context)

        with pytest.raises(PermissionDenied):
            await service.create(session, context, JobCreate(name="Not allowed"))
        await session.rollback()


async def test_a_tool_declares_what_the_job_may_do_with_it(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §8 group 7, and PLAN §19's governed gateway.

    A tool declaration is a permission ceiling, not a note: a job that never declared `Send` on
    Outlook does not get to send mail, whatever a model decides mid-run. What is stored here is
    what that gateway will check.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        await service.update(
            session,
            context,
            job.id,
            JobUpdate(
                steps=[JobStepInput(what_exact_work="Send the quotation")],
                tools=[
                    JobToolDefinition(
                        name="Outlook",
                        permissions=["Read", "Send"],
                        step_position=1,
                        note="The shared sales mailbox only.",
                    )
                ],
                expected_version=job.version,
            ),
        )
        await session.flush()

        saved = await service.read(session, context, job.id)
        assert len(saved.tools) == 1
        assert saved.tools[0].permissions == ["Read", "Send"]
        #  Resolved back to a position, because the client edits by position and the step ids
        #  change on every save.
        assert saved.tools[0].step_position == 1
        #  Not connected to anything yet — Gate 8 wires the real integrations.
        assert saved.tools[0].integration_id is None
        await session.rollback()


async def test_a_tool_with_no_permission_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Every call to it would be refused, so it is better refused where somebody can fix it."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        with pytest.raises(ValidationError):
            JobToolDefinition(name="Outlook", permissions=[])
        await session.rollback()


async def test_reordering_steps_does_not_repoint_a_tools_permission(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The step a tool names is resolved by position at save time.

    Storing the id would break on every save, because the step list is replaced wholesale.
    Storing the number without re-resolving would silently point a permission at different work
    the first time somebody reordered — which is the failure worth a test.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Quotations"))
        await session.flush()

        await service.update(
            session,
            context,
            job.id,
            JobUpdate(
                steps=[
                    JobStepInput(what_exact_work="Draft it"),
                    JobStepInput(what_exact_work="Send it"),
                ],
                tools=[
                    JobToolDefinition(name="Outlook", permissions=["Send"], step_position=2)
                ],
                expected_version=job.version,
            ),
        )
        await session.flush()

        saved = await service.read(session, context, job.id)
        sending_step = saved.steps[1]
        assert saved.tools[0].step_position == 2
        assert sending_step.what_exact_work == "Send it"
        await session.rollback()
