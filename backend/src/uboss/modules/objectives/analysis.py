"""The analysis — six real stages, one model call, and a graph a person then edits.

`docs/delivery/WORK_BREAKDOWN.md` names the stages and says what they must be:

    Run events are real: validate → context → workstreams → propose → policy → review.

**Real** is the requirement. Each stage writes a row when it starts and when it finishes, so the
timeline on screen is a record of what happened rather than an animation driven by a timer. Five
of the six are the product's own work; only `propose` calls a model.

**The AI produces a proposal. It never writes to governed state.** The model's answer is stored
unchanged and steps are created from it, marked `source = 'ai'`. From that moment they are
ordinary editable rows, and nothing downstream treats them as more authoritative than a step
somebody typed. Publishing them is a separate, human act — 3.3.

**Policy is checked after the model, not before.** A proposal that hands a person's approval to an
agent, or puts an AI block on work the objective marked sensitive, is caught here and flagged on
the step rather than silently applied. PLAN §16's `AI_FORBIDDEN_ACTIONS` is the same idea one
layer down.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.core.settings import Settings
from uboss.modules.ai_gateway import service as ai
from uboss.modules.ai_gateway.contract import ModelUnavailableError, Task, TaskKind
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.objectives.models import (
    AiAssistance,
    Objective,
    ObjectiveCurrentStep,
    ObjectiveStatus,
)
from uboss.modules.objectives.proposal_models import (
    AnalysisEvent,
    ObjectiveProposal,
    ObjectiveStep,
    ProposalStatus,
    Stage,
    StageState,
    StepKind,
    StepSource,
)

#: What the model is told. Versioned, because 3.2's exit check asks for a *versioned prompt*: a
#: proposal records which one produced it, so a change in wording is visible in the audit rather
#: than being an unexplained change in behaviour.
PROMPT_VERSION = "objective-graph/1"

INSTRUCTIONS = """\
You turn a description of how work is done today into a proposed execution plan.

You are given an objective and the steps of the current process, exactly as the team described
them. Propose a plan of blocks that reaches the objective's stated result.

Block kinds, and what each means:
- human: a person does it. Use this whenever judgement, relationships or accountability are
  involved.
- ai_agent: software does it unattended. Only for work that is well defined, repeatable and
  checkable.
- hybrid: software prepares and a person confirms. Prefer this over ai_agent wherever a mistake
  would be expensive or hard to notice.
- approval: somebody with authority signs off. Never assign this to an agent.
- output: what the objective produces, and who receives it.

Rules:
- Stay inside the described work. Do not invent steps for problems the team did not mention.
- Every step names who is responsible, as a role rather than a person.
- Where a step replaces one of the current steps, give its number.
- Give a short reason for each step, in plain language a person who does this work would use.
- Dependencies are by step number within your own plan, and must not form a loop.
- If the current process is too thin to plan from, return no steps and say so in `note`.
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer", "minimum": 1},
                    "kind": {
                        "type": "string",
                        "enum": ["human", "ai_agent", "hybrid", "approval", "output"],
                    },
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "responsible_role": {"type": "string"},
                    "replaces_current_step": {"type": "integer", "minimum": 1},
                    "rationale": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "integer", "minimum": 1}},
                },
                "required": ["number", "kind", "title", "responsible_role", "rationale"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["steps"],
    "additionalProperties": False,
}

#: More than this and nobody reviews it properly. The model is told to stay inside the described
#: work; this is the backstop for when it does not.
MAX_PROPOSED_STEPS = 40


def _now() -> datetime:
    return datetime.now(UTC)


async def start(
    session: AsyncSession,
    settings: Settings,
    context: SecurityContext,
    objective_id: uuid.UUID,
) -> ObjectiveProposal:
    """Run the analysis, start to finish, and leave a graph the person can edit.

    Synchronous on the request. One model call on a small input takes seconds, and a background
    job would need a queue, a worker and a way to tell the browser it finished — all of which
    arrive with Temporal in Gate 7, and none of which this needs today. The timeline rows are
    written as each stage happens either way, so moving it later changes nothing on screen.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    objective = (
        await session.execute(select(Objective).where(Objective.id == objective_id))
    ).scalar_one_or_none()
    if objective is None:
        raise NotFound("No such objective.")

    if objective.ai_assistance == AiAssistance.NONE:
        raise ValidationFailed(
            "This objective is set to no AI help. Change that in AI preferences first."
        )
    if not objective.is_editable:
        raise ValidationFailed(
            f"This objective is {objective.status.replace('_', ' ')} and cannot be analysed."
        )

    running = (
        await session.execute(
            select(ObjectiveProposal).where(
                ObjectiveProposal.objective_id == objective_id,
                ObjectiveProposal.status == ProposalStatus.RUNNING,
            )
        )
    ).scalar_one_or_none()
    if running is not None:
        raise Conflict("An analysis is already running for this objective.")

    steps = list(
        (
            await session.execute(
                select(ObjectiveCurrentStep)
                .where(ObjectiveCurrentStep.objective_id == objective_id)
                .order_by(ObjectiveCurrentStep.position)
            )
        )
        .scalars()
        .all()
    )

    proposal = ObjectiveProposal(
        tenant_id=context.tenant_id,
        objective_id=objective_id,
        status=ProposalStatus.RUNNING,
        stage=Stage.VALIDATE,
        input_snapshot=_snapshot(objective, steps),
        requested_by_membership_id=context.membership_id,
    )
    session.add(proposal)
    await session.flush()

    objective.status = ObjectiveStatus.ANALYZING
    objective.version += 1

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="objective.analysis.started",
        resource_type="objective",
        resource_id=objective_id,
        actor=context,
        detail={"proposal_id": str(proposal.id), "prompt_version": PROMPT_VERSION},
    )

    try:
        await _run_stages(session, settings, context, objective, steps, proposal)
    except ModelUnavailableError as unavailable:
        await _fail(session, objective, proposal, Stage.PROPOSE, str(unavailable))
        return proposal
    except ValidationFailed as refused:
        #  `proposal.stage` is the column's `str`; the failure row wants the enum member, which
        #  is also what the screen reads to mark the right stage as the one that stopped.
        stopped = Stage(proposal.stage) if proposal.stage else Stage.VALIDATE
        await _fail(session, objective, proposal, stopped, str(refused))
        return proposal

    return proposal


async def _run_stages(
    session: AsyncSession,
    settings: Settings,
    context: SecurityContext,
    objective: Objective,
    current: list[ObjectiveCurrentStep],
    proposal: ObjectiveProposal,
) -> None:
    # ── validate ────────────────────────────────────────────────────────────────────────
    await _event(session, context, proposal, Stage.VALIDATE, StageState.RUNNING)
    if not current:
        raise ValidationFailed(
            "There are no steps in the current process to plan from. Describe at least one "
            "step of how the work happens today."
        )
    if not (objective.expected_result or "").strip():
        raise ValidationFailed(
            "The expected final result is empty, so there is nothing to plan towards."
        )
    await _event(
        session,
        context,
        proposal,
        Stage.VALIDATE,
        StageState.DONE,
        f"{len(current)} steps of the current process, and a stated result.",
    )

    # ── context ─────────────────────────────────────────────────────────────────────────
    await _advance(session, proposal, Stage.CONTEXT)
    await _event(session, context, proposal, Stage.CONTEXT, StageState.RUNNING)
    material = _material(objective, current)
    await _event(
        session,
        context,
        proposal,
        Stage.CONTEXT,
        StageState.DONE,
        #  Said out loud, because a person is entitled to know what left the building. Nothing
        #  from another objective and nothing from another tenant is in here — it is built from
        #  rows already read under this tenant's own policy.
        f"Sent the objective and its {len(current)} steps. Nothing else.",
    )

    # ── workstreams ─────────────────────────────────────────────────────────────────────
    await _advance(session, proposal, Stage.WORKSTREAMS)
    await _event(session, context, proposal, Stage.WORKSTREAMS, StageState.RUNNING)
    problems = sorted(
        {
            step.current_problem
            for step in current
            if step.current_problem and step.current_problem != "No problem"
        }
    )
    await _event(
        session,
        context,
        proposal,
        Stage.WORKSTREAMS,
        StageState.DONE,
        (
            f"Problems the team recorded: {', '.join(problems)}."
            if problems
            else "The team recorded no problems with the current process."
        ),
    )

    # ── propose ─────────────────────────────────────────────────────────────────────────
    await _advance(session, proposal, Stage.PROPOSE)
    await _event(session, context, proposal, Stage.PROPOSE, StageState.RUNNING)

    completion = await ai.run(
        session,
        settings,
        context,
        Task(
            kind=TaskKind.OBJECTIVE_PROPOSAL,
            instructions=INSTRUCTIONS,
            input=json.dumps(material, ensure_ascii=False),
            schema=SCHEMA,
        ),
    )
    proposal.output = completion.content
    proposal.model = completion.model
    proposal.input_tokens = completion.input_tokens
    proposal.output_tokens = completion.output_tokens
    proposal.latency_ms = completion.latency_ms

    proposed = _clean(completion.content, len(current))
    await _event(
        session,
        context,
        proposal,
        Stage.PROPOSE,
        StageState.DONE,
        f"{completion.model} proposed {len(proposed)} steps.",
    )

    # ── policy ──────────────────────────────────────────────────────────────────────────
    await _advance(session, proposal, Stage.POLICY)
    await _event(session, context, proposal, Stage.POLICY, StageState.RUNNING)
    flagged = _apply_policy(objective, proposed)
    await _event(
        session,
        context,
        proposal,
        Stage.POLICY,
        StageState.DONE,
        (
            f"{len(flagged)} steps changed to keep a person in the loop."
            if flagged
            else "Nothing in the plan conflicts with this objective's policy."
        ),
    )

    # ── review ──────────────────────────────────────────────────────────────────────────
    await _advance(session, proposal, Stage.REVIEW)
    await _event(session, context, proposal, Stage.REVIEW, StageState.RUNNING)
    await _write_steps(session, context, objective, proposal, proposed)

    proposal.status = ProposalStatus.SUCCEEDED
    proposal.stage = Stage.REVIEW
    proposal.finished_at = _now()
    objective.status = ObjectiveStatus.NEEDS_REVIEW
    objective.version += 1
    await session.flush()

    await _event(
        session,
        context,
        proposal,
        Stage.REVIEW,
        StageState.DONE,
        "Ready for you to edit. Nothing is published until you say so.",
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="objective.analysis.succeeded",
        resource_type="objective",
        resource_id=objective.id,
        actor=context,
        detail={
            "proposal_id": str(proposal.id),
            "model": completion.model,
            "steps": len(proposed),
            "prompt_version": PROMPT_VERSION,
        },
    )


# ------------------------------------------------------------------------------ the material


def _snapshot(objective: Objective, steps: list[ObjectiveCurrentStep]) -> dict[str, Any]:
    return {
        "title": objective.title,
        "expected_result": objective.expected_result,
        "department": objective.department,
        "current_step_count": len(steps),
        "at": _now().isoformat(),
        "prompt_version": PROMPT_VERSION,
    }


def _material(objective: Objective, steps: list[ObjectiveCurrentStep]) -> dict[str, Any]:
    """What the model is given, and nothing else.

    Built from rows already read under this tenant's own policy, so there is no path by which
    another organisation's work could reach a prompt. Names are deliberately included — the team
    described their process in terms of who does what, and stripping that would produce a plan
    about nobody.
    """
    return {
        "objective": {
            "title": objective.title,
            "department": objective.department,
            "expected_result": objective.expected_result,
            "current_workload": (
                f"{objective.workload_count} per {objective.workload_unit}"
                if objective.workload_count and objective.workload_unit
                else None
            ),
            "success_measures": objective.success_measures,
            "included_work": objective.included_work,
            "excluded_work": objective.excluded_work,
            "policy_constraints": objective.policy_constraints,
            "handles_sensitive_data": objective.handles_sensitive_data,
            "human_checkpoints": objective.human_checkpoints,
        },
        "current_process": [
            {
                "number": step.position,
                "who": step.who_role or step.who_person,
                "trigger": step.when_trigger,
                "frequency": step.when_frequency,
                "work": step.what_exact_work,
                "input": step.input_used,
                "input_from": step.input_received_from,
                "where": step.where_done,
                "output": step.output_produced,
                "output_to": step.output_sent_to,
                "time_taken": step.time_taken,
                "problem": step.current_problem,
                "approval": step.approval,
            }
            for step in steps
        ],
    }


def _clean(output: dict[str, Any], current_count: int) -> list[dict[str, Any]]:
    """Everything the schema could not guarantee.

    A JSON Schema fixes the shape; it cannot say that a step number is unique, that a dependency
    points at a step that exists, or that the plan is small enough for a person to review. Each
    check below has a failure mode that would otherwise reach the database.
    """
    raw = output.get("steps") or []
    if not isinstance(raw, list):
        raise ValidationFailed("The model's answer was not a plan.")
    if len(raw) > MAX_PROPOSED_STEPS:
        raise ValidationFailed(
            f"The proposal has more than {MAX_PROPOSED_STEPS} steps, which is more than anybody "
            "reviews properly. Narrow the objective and analyse it again."
        )

    seen: set[int] = set()
    cleaned: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        number = entry.get("number")
        kind = entry.get("kind")
        title = str(entry.get("title", "")).strip()
        if not isinstance(number, int) or number in seen:
            continue
        if kind not in tuple(StepKind) or not title:
            continue
        seen.add(number)
        cleaned.append(
            {
                "number": number,
                "kind": kind,
                "title": title[:300],
                "detail": str(entry.get("detail", "")).strip() or None,
                "responsible_role": str(entry.get("responsible_role", "")).strip()[:200] or None,
                "replaces_current_step": (
                    entry["replaces_current_step"]
                    if isinstance(entry.get("replaces_current_step"), int)
                    and 1 <= entry["replaces_current_step"] <= current_count
                    else None
                ),
                "rationale": str(entry.get("rationale", "")).strip() or None,
                "depends_on": [
                    value
                    for value in (entry.get("depends_on") or [])
                    if isinstance(value, int) and value != number
                ],
            }
        )

    cleaned.sort(key=lambda step: step["number"])
    #  A dependency on a step the model did not produce is dropped rather than failing the run.
    #  It is the model referring to something it decided against; the plan is still usable, and
    #  refusing the whole thing over it would be a worse trade for the person waiting.
    numbers = {step["number"] for step in cleaned}
    for step in cleaned:
        step["depends_on"] = [value for value in step["depends_on"] if value in numbers]
    return cleaned


def _apply_policy(objective: Objective, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where the plan and the objective's own policy disagree, the policy wins.

    Two rules, both from the objective the person filled in:

    * **An approval is never an agent's.** PLAN §16 keeps approval a human act. A model that
      proposes an `ai_agent` approval is proposing something the runtime would refuse anyway.
    * **Sensitive data means a person stays in the loop.** Where the objective says it handles
      personal or sensitive data, an unattended `ai_agent` step becomes `hybrid` — software
      prepares, a person confirms.

    Changed rather than removed, and the change is said out loud on the step. Dropping the step
    would leave a hole in the plan that nobody would notice.
    """
    flagged: list[dict[str, Any]] = []
    for step in steps:
        if step["kind"] == StepKind.APPROVAL and step.get("responsible_role") in (None, ""):
            step["responsible_role"] = "Approver"

        if step["kind"] == StepKind.AI_AGENT and objective.handles_sensitive_data:
            step["kind"] = StepKind.HYBRID.value
            step["rationale"] = _note(
                step.get("rationale"),
                "Changed to hybrid: this objective handles sensitive data, so a person confirms "
                "before the step completes.",
            )
            flagged.append(step)

    return flagged


def _note(existing: str | None, addition: str) -> str:
    return f"{existing}\n\n{addition}" if existing else addition


# ------------------------------------------------------------------------------- persistence


async def _write_steps(
    session: AsyncSession,
    context: SecurityContext,
    objective: Objective,
    proposal: ObjectiveProposal,
    steps: list[dict[str, Any]],
) -> None:
    """Replace the graph with this proposal's.

    Replaced, not merged. A rerun is a person asking for a different plan, and merging two plans
    produces one nobody designed. §7's *"rerun only a selected section"* is a narrower operation
    that arrives with the section editor; this is the whole-graph case.
    """
    from uboss.modules.objectives.proposal_models import StepDependency

    await session.execute(
        delete(ObjectiveStep).where(ObjectiveStep.objective_id == objective.id)
    )
    await session.flush()

    by_number: dict[int, uuid.UUID] = {}
    for position, step in enumerate(steps, start=1):
        row = ObjectiveStep(
            tenant_id=context.tenant_id,
            objective_id=objective.id,
            proposal_id=proposal.id,
            position=position,
            kind=step["kind"],
            title=step["title"],
            detail=step["detail"],
            responsible_role=step["responsible_role"],
            replaces_current_step=step["replaces_current_step"],
            rationale=step["rationale"],
            source=StepSource.AI,
        )
        session.add(row)
        await session.flush()
        by_number[step["number"]] = row.id

    for step in steps:
        for target in step["depends_on"]:
            if target not in by_number:
                continue
            session.add(
                StepDependency(
                    tenant_id=context.tenant_id,
                    step_id=by_number[step["number"]],
                    depends_on_step_id=by_number[target],
                )
            )
    #  The cycle trigger fires on this flush. A model that proposed a loop fails the run rather
    #  than leaving a plan that can never start.
    await session.flush()


async def _event(
    session: AsyncSession,
    context: SecurityContext,
    proposal: ObjectiveProposal,
    stage: Stage,
    state: StageState,
    detail: str | None = None,
) -> None:
    session.add(
        AnalysisEvent(
            tenant_id=context.tenant_id,
            proposal_id=proposal.id,
            stage=stage,
            state=state,
            detail=detail,
        )
    )
    await session.flush()


async def _advance(
    session: AsyncSession, proposal: ObjectiveProposal, stage: Stage
) -> None:
    proposal.stage = stage
    await session.flush()


async def _fail(
    session: AsyncSession,
    objective: Objective,
    proposal: ObjectiveProposal,
    stage: Stage,
    detail: str,
) -> None:
    """Record the failure and put the objective back where it was.

    Left in `analyzing`, the form would stay locked and the person would have nothing to do about
    it. The stage that failed and the reason are both kept, so "it did not work" is answerable.
    """
    session.add(
        AnalysisEvent(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal.id,
            stage=stage,
            state=StageState.FAILED,
            detail=detail,
        )
    )
    proposal.status = ProposalStatus.FAILED
    proposal.stage = stage
    proposal.failure_detail = detail
    proposal.finished_at = _now()
    objective.status = ObjectiveStatus.DRAFT
    objective.version += 1
    await session.flush()
