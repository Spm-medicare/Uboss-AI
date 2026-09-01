"""The analysis, the graph, and the rule they exist to hold.

`docs/delivery/WORK_BREAKDOWN.md`: *"The AI produces a proposal. It never writes to governed
state. Run events are real: validate → context → workstreams → propose → policy → review."*

Both halves are tested. The stages write real rows — including when the run fails, which is where
a timeline driven by a timer would quietly show six green ticks. And the model's answer becomes
editable steps rather than anything published: publishing is 3.3 and is a human act.

The model is stubbed. These are about what the product does with an answer, not about what a
particular model says — a test that called the real API would be slow, would cost money, and
would fail on a day the model phrased something differently.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import ValidationFailed
from uboss.core.settings import Settings
from uboss.db.base import build_sessionmaker
from uboss.modules.ai_gateway.contract import Completion, ModelUnavailableError
from uboss.modules.hierarchy import service as hierarchy
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.objectives import analysis, graph, service
from uboss.modules.objectives.models import ObjectiveStatus
from uboss.modules.objectives.proposal_models import (
    AnalysisEvent,
    ObjectiveStep,
    ProposalStatus,
    Stage,
    StageState,
    StepKind,
    StepSource,
)
from uboss.modules.objectives.schemas import (
    CurrentStepInput,
    ObjectiveCreate,
    ObjectiveUpdate,
)

pytestmark = pytest.mark.anyio


PLAN: dict[str, Any] = {
    "steps": [
        {
            "number": 1,
            "kind": "ai_agent",
            "title": "Read the enquiry and extract the line items",
            "responsible_role": "Quotation agent",
            "replaces_current_step": 1,
            "rationale": "The team called this manual data entry.",
            "depends_on": [],
        },
        {
            "number": 2,
            "kind": "human",
            "title": "Check the price against the contract",
            "responsible_role": "Sales coordinator",
            "rationale": "Pricing needs judgement.",
            "depends_on": [1],
        },
        {
            "number": 3,
            "kind": "approval",
            "title": "Approve the quotation",
            "responsible_role": "Sales manager",
            "rationale": "Above the coordinator's limit.",
            "depends_on": [2],
        },
    ]
}


def _completion(content: dict[str, Any]) -> Completion:
    return Completion(
        content=content,
        model="claude-test",
        input_tokens=100,
        output_tokens=200,
        latency_ms=1200,
    )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Stand in for the gateway, and record what it was asked.

    Patched at `ai.run`, which is the gateway's own front door — so everything above it, including
    the audit row the gateway writes, is exercised exactly as in production.
    """
    calls: list[Any] = []
    answer: dict[str, Any] = {"content": PLAN}

    async def fake_run(session: Any, settings: Any, context: Any, task: Any) -> Completion:
        calls.append(task)
        if "error" in answer:
            raise answer["error"]
        return _completion(answer["content"])

    monkeypatch.setattr(analysis.ai, "run", fake_run)
    return type("Model", (), {"calls": calls, "answer": answer})()


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


async def _ready_objective(
    session: AsyncSession,
    context: SecurityContext,
    *,
    sensitive: bool = False,
) -> uuid.UUID:
    """An objective with a stated result and one described step — the minimum to analyse."""
    objective = await service.create(session, context, ObjectiveCreate(title="Quotations"))
    await session.flush()
    await service.update(
        session,
        context,
        objective.id,
        ObjectiveUpdate(
            expected_result="Quotations out the same day",
            handles_sensitive_data=sensitive,
            current_steps=[
                CurrentStepInput(
                    who_role="Sales coordinator",
                    what_exact_work="Copy the line items into the quote sheet",
                    current_problem="Manual data entry",
                )
            ],
            expected_version=objective.version,
        ),
    )
    await session.flush()
    return objective.id


async def test_the_timeline_records_all_six_stages(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """PLAN §6 asks for a *real* analysis timeline.

    Six stages, each written when it ran. A progress animation driven by a timer would look
    identical on screen — this is the test that tells them apart.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)

        proposal = await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        assert proposal.status == ProposalStatus.SUCCEEDED

        events = list(
            (
                await session.execute(
                    select(AnalysisEvent)
                    .where(AnalysisEvent.proposal_id == proposal.id)
                    .order_by(AnalysisEvent.at)
                )
            )
            .scalars()
            .all()
        )
        stages = [event.stage for event in events if event.state == StageState.DONE]
        assert stages == [
            Stage.VALIDATE,
            Stage.CONTEXT,
            Stage.WORKSTREAMS,
            Stage.PROPOSE,
            Stage.POLICY,
            Stage.REVIEW,
        ]
        #  Only one of the six calls a model. The other five are the product's own work, which is
        #  why the timeline is worth showing at all.
        assert len(model.calls) == 1
        await session.rollback()


async def test_the_proposal_becomes_editable_steps_not_published_state(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """The AI produces a proposal. It never writes to governed state.

    The objective lands in `needs_review` — a person's inbox — and not in `published`.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)

        await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        objective = await service.read(session, context, objective_id)
        assert objective.status == ObjectiveStatus.NEEDS_REVIEW
        assert objective.published_version_id is None

        steps = list(
            (
                await session.execute(
                    select(ObjectiveStep)
                    .where(ObjectiveStep.objective_id == objective_id)
                    .order_by(ObjectiveStep.position)
                )
            )
            .scalars()
            .all()
        )
        assert [step.title for step in steps] == [
            "Read the enquiry and extract the line items",
            "Check the price against the contract",
            "Approve the quotation",
        ]
        assert all(step.source == StepSource.AI for step in steps)
        assert not any(step.edited for step in steps)
        await session.rollback()


async def test_sensitive_data_turns_an_unattended_agent_into_a_hybrid(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """The policy stage, and the reason it runs *after* the model rather than before.

    The model proposed an unattended `ai_agent` step. The objective says it handles sensitive
    data, so a person stays in the loop — and the step says why, rather than being silently
    changed or silently dropped.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context, sensitive=True)

        await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        first = (
            await session.execute(
                select(ObjectiveStep)
                .where(ObjectiveStep.objective_id == objective_id)
                .order_by(ObjectiveStep.position)
                .limit(1)
            )
        ).scalar_one()

        assert first.kind == StepKind.HYBRID
        assert "sensitive data" in (first.rationale or "")
        await session.rollback()


async def test_a_failed_analysis_says_where_it_stopped_and_unlocks_the_form(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """No model reachable is a supported state, not a fault in what the person was doing.

    Left in `analyzing`, the form would stay locked with nothing the person could do about it.
    """
    left, _ = two_workspaces
    model.answer["error"] = ModelUnavailableError("No model is configured.")

    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)

        proposal = await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        assert proposal.status == ProposalStatus.FAILED
        assert proposal.stage == Stage.PROPOSE
        assert "No model" in (proposal.failure_detail or "")

        objective = await service.read(session, context, objective_id)
        assert objective.status == ObjectiveStatus.DRAFT
        assert objective.is_editable

        #  And the timeline shows where it stopped — the first three stages did happen.
        events = list(
            (
                await session.execute(
                    select(AnalysisEvent).where(AnalysisEvent.proposal_id == proposal.id)
                )
            )
            .scalars()
            .all()
        )
        assert any(
            event.stage == Stage.PROPOSE and event.state == StageState.FAILED
            for event in events
        )
        await session.rollback()


async def test_an_objective_with_no_described_steps_is_refused_before_the_model(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """`validate` exists so a hopeless run costs nothing and says something useful."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective = await service.create(session, context, ObjectiveCreate(title="Empty"))
        await session.flush()

        proposal = await analysis.start(session, settings_for_tests, context, objective.id)
        await session.flush()

        assert proposal.status == ProposalStatus.FAILED
        assert proposal.stage == Stage.VALIDATE
        assert model.calls == []
        await session.rollback()


async def test_editing_an_ai_step_marks_it_and_the_mark_never_clears(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """PLAN §7's "compare AI/human changes", as a flag that cannot be laundered.

    Changing a step back to what the model said still leaves it marked. Clearing it would make
    the comparison lie in the model's favour, which is the one direction it must not lie in.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)
        await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        step = (
            await session.execute(
                select(ObjectiveStep)
                .where(ObjectiveStep.objective_id == objective_id)
                .order_by(ObjectiveStep.position)
                .limit(1)
            )
        ).scalar_one()
        original = step.title

        edited = await graph.update(
            session,
            context,
            step.id,
            expected_version=step.version,
            changes={"title": "Extract the line items, and flag anything unclear"},
        )
        await session.flush()
        assert edited.edited

        back = await graph.update(
            session,
            context,
            step.id,
            expected_version=edited.version,
            changes={"title": original},
        )
        await session.flush()
        assert back.edited
        await session.rollback()


async def test_a_dependency_that_closes_a_loop_is_refused(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """A plan that waits for itself can never start.

    Refused by the database, so a bulk path — a duplicated section, an imported plan — cannot get
    around it.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)
        await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        steps = list(
            (
                await session.execute(
                    select(ObjectiveStep)
                    .where(ObjectiveStep.objective_id == objective_id)
                    .order_by(ObjectiveStep.position)
                )
            )
            .scalars()
            .all()
        )
        #  Step 3 already waits for 2, which waits for 1. Making 1 wait for 3 closes the ring.
        with pytest.raises(Exception) as refused:
            await graph.set_dependencies(
                session,
                context,
                steps[0].id,
                [steps[2].id],
                expected_version=steps[0].version,
            )
        assert "wait for itself" in str(refused.value)
        await session.rollback()


async def test_merging_keeps_what_the_absorbed_step_said(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """A merge that dropped half of what it merged would be a delete wearing a friendlier name."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)
        await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        steps = list(
            (
                await session.execute(
                    select(ObjectiveStep)
                    .where(ObjectiveStep.objective_id == objective_id)
                    .order_by(ObjectiveStep.position)
                )
            )
            .scalars()
            .all()
        )
        await graph.update(
            session,
            context,
            steps[1].id,
            expected_version=steps[1].version,
            changes={"detail": "Check the contract price list."},
        )
        await session.flush()

        #  The version of the step being absorbed, read after the update above spent one.
        absorbed_version = steps[1].version
        merged = await graph.merge(
            session,
            context,
            steps[1].id,
            steps[0].id,
            expected_version=absorbed_version,
        )
        await session.flush()

        assert "contract price list" in (merged.detail or "")
        remaining = list(
            (
                await session.execute(
                    select(ObjectiveStep)
                    .where(ObjectiveStep.objective_id == objective_id)
                    .order_by(ObjectiveStep.position)
                )
            )
            .scalars()
            .all()
        )
        #  Two left, and renumbered 1 and 2 — no gap where the merged step was.
        assert [step.position for step in remaining] == [1, 2]
        await session.rollback()


async def test_a_plan_with_more_steps_than_anybody_reviews_is_refused(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """The schema fixes the shape; it cannot say the plan is small enough to read."""
    left, _ = two_workspaces
    model.answer["content"] = {
        "steps": [
            {
                "number": index,
                "kind": "human",
                "title": f"Step {index}",
                "responsible_role": "Somebody",
                "rationale": "…",
            }
            for index in range(1, analysis.MAX_PROPOSED_STEPS + 2)
        ]
    }

    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)

        proposal = await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        assert proposal.status == ProposalStatus.FAILED
        assert "reviews properly" in (proposal.failure_detail or "")
        await session.rollback()


async def test_a_dependency_on_a_step_the_model_did_not_produce_is_dropped(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """Dropped, not fatal.

    It is the model referring to something it decided against. The plan is still usable, and
    failing the whole run over it would be the worse trade for the person waiting.
    """
    left, _ = two_workspaces
    model.answer["content"] = {
        "steps": [
            {
                "number": 1,
                "kind": "human",
                "title": "Do the thing",
                "responsible_role": "Somebody",
                "rationale": "…",
                "depends_on": [99],
            }
        ]
    }

    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)

        proposal = await analysis.start(session, settings_for_tests, context, objective_id)
        await session.flush()

        assert proposal.status == ProposalStatus.SUCCEEDED
        await session.rollback()


async def test_analysis_is_refused_when_the_objective_says_no_ai(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    settings_for_tests: Settings,
    model: Any,
) -> None:
    """§7 group 8 is a preference the product honours, not a suggestion."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        objective_id = await _ready_objective(session, context)
        objective = await service.read(session, context, objective_id)
        await service.update(
            session,
            context,
            objective_id,
            ObjectiveUpdate(ai_assistance="none", expected_version=objective.version),
        )
        await session.flush()

        with pytest.raises(ValidationFailed):
            await analysis.start(session, settings_for_tests, context, objective_id)
        assert model.calls == []
        await session.rollback()
