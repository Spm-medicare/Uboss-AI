"""Publishing an Agent — the two gates §9 names, and the version they guard.

> Tests and permission review are publish gates.

Two gates, and only two. §9 names these; nothing else here blocks, because a gate this file
invented would be a rule nobody approved. Everything else that looks wrong is a **warning** —
shown, never hidden, and never in the way.

**The tests gate.** All five of Form 4 section C must exist and read `Pass`. A `Fail`, a `Blocked`
or a `Not Run` stops the publish and says which. There is no sandbox runtime until Gate 7, so a
status is recorded by the person who ran the test — `run_by` and `run_at` are what make that
evidence rather than a checkbox, and a result with no observation is refused by the schema.

**The permission review gate.** Every tool the design lists must have been granted or removed. A
tool sitting ungranted at publish is a permission nobody reviewed, and §9 makes the review a gate
precisely so that "we'll sort the access out later" cannot reach production.

**Nobody approves their own work.** The same four checks as the Objective and the Job: `publish`
held and recently proved, the caller is the named approver, they did not submit it, and the
version they read is the one they approve. `docs/product/SKILL_REGISTRY.md` states the general
rule — *"No Skill or Agent can approve/promote itself."*

**Section B is a warning, not a gate.** Form 4 prints six error situations without the asterisk it
puts on the four required header fields, and §9 names only two gates. An unanswered situation is
therefore surfaced loudly and does not block. Making it block is a business decision the client can
take; inventing it here would not be.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.agents.agent_models import (
    Agent,
    AgentEscalationRule,
    AgentIoSchema,
    AgentKnowledgeSource,
    AgentShare,
    AgentSkill,
    AgentStatus,
    AgentStep,
    AgentTest,
    AgentTool,
    AgentVersion,
    Direction,
    SandboxTestKind,
    SandboxTestStatus,
    Situation,
)
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PublishWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class GateResult:
    """One of §9's two gates, and what it is waiting for."""

    gate: str
    name: str
    passed: bool
    #: What would clear it, in a sentence somebody can act on.
    reason: str


@dataclass(slots=True)
class Summary:
    """What publishing this would mean, and what is standing in the way."""

    agent_id: uuid.UUID
    name: str
    status: str
    owner_name: str | None
    approver_name: str | None
    submitted_by_name: str | None
    job_name: str | None
    job_version_no: int | None

    step_count: int
    skill_count: int
    tool_count: int
    #: How many tools have actually been granted. The number people most want here, because it is
    #: the one that answers "what can this thing reach".
    granted_tool_count: int
    io_input_count: int
    io_output_count: int
    knowledge_count: int
    #: Sources holding personal data. The privacy review reads this line.
    personal_data_sources: int
    shared_with_count: int

    tests_passed: int
    tests_total: int

    #: §9's two gates. Both must pass; nothing else blocks.
    gates: list[GateResult] = field(default_factory=list)
    warnings: list[PublishWarning] = field(default_factory=list)
    next_action: str = ""
    can_submit: bool = False
    can_approve: bool = False
    version: int = 1


async def summary(
    session: AsyncSession, context: SecurityContext, agent_id: uuid.UUID
) -> Summary:
    await guard.authorise(session, context, Action.VIEW)

    agent = await _get(session, agent_id)
    steps = await _rows(session, AgentStep, agent_id)
    rules = await _rows(session, AgentEscalationRule, agent_id)
    tools = await _rows(session, AgentTool, agent_id)
    skills = await _rows(session, AgentSkill, agent_id)
    io_rows = await _rows(session, AgentIoSchema, agent_id)
    knowledge = await _rows(session, AgentKnowledgeSource, agent_id)
    shares = await _rows(session, AgentShare, agent_id)
    tests = await _rows(session, AgentTest, agent_id)

    names = await _names(
        session,
        agent.owner_membership_id,
        agent.main_approver_membership_id,
        agent.submitted_by_membership_id,
    )
    job_name, job_version_no = await _job_facts(session, agent)

    gates = [_tests_gate(tests), _permission_gate(tools)]
    warnings = _warnings(agent, steps, rules, tools, io_rows, skills)

    passed = sum(1 for test in tests if test.status == SandboxTestStatus.PASS)
    granted = sum(1 for tool in tools if tool.granted)

    can_submit = agent.status in (AgentStatus.DRAFT, AgentStatus.NEEDS_REVIEW)
    can_approve = (
        agent.status == AgentStatus.READY_TO_PUBLISH
        and agent.main_approver_membership_id == context.membership_id
        and agent.submitted_by_membership_id != context.membership_id
        and all(gate.passed for gate in gates)
    )

    return Summary(
        agent_id=agent.id,
        name=agent.name,
        status=agent.status,
        owner_name=names.get(agent.owner_membership_id),
        approver_name=names.get(agent.main_approver_membership_id),
        submitted_by_name=names.get(agent.submitted_by_membership_id),
        job_name=job_name,
        job_version_no=job_version_no,
        step_count=len(steps),
        skill_count=len(skills),
        tool_count=len(tools),
        granted_tool_count=granted,
        io_input_count=sum(1 for row in io_rows if row.direction == Direction.INPUT),
        io_output_count=sum(1 for row in io_rows if row.direction == Direction.OUTPUT),
        knowledge_count=len(knowledge),
        personal_data_sources=sum(1 for row in knowledge if row.contains_personal_data),
        shared_with_count=len(shares),
        tests_passed=passed,
        tests_total=len(SandboxTestKind),
        gates=gates,
        warnings=warnings,
        next_action=_next_action(agent, gates, context),
        can_submit=can_submit,
        can_approve=can_approve,
        version=agent.version,
    )


def _tests_gate(tests: list[AgentTest]) -> GateResult:
    """All five of Form 4 section C, and every one a `Pass`."""
    by_kind = {test.kind: test for test in tests}
    absent = [kind for kind in SandboxTestKind if kind not in by_kind]
    if absent:
        listed = ", ".join(kind.value.replace("_", " ") for kind in absent)
        return GateResult(
            gate="tests",
            name="Sandbox tests",
            passed=False,
            reason=f"{len(absent)} of the five tests have not been written: {listed}.",
        )

    unfinished = [
        test for test in tests if test.status != SandboxTestStatus.PASS
    ]
    if unfinished:
        listed = "; ".join(
            f"{test.kind.replace('_', ' ')} is {test.status.replace('_', ' ')}"
            for test in sorted(unfinished, key=lambda t: t.kind)
        )
        return GateResult(
            gate="tests",
            name="Sandbox tests",
            passed=False,
            reason=f"Every test must pass before this publishes. {listed}.",
        )
    return GateResult(
        gate="tests",
        name="Sandbox tests",
        passed=True,
        reason="All five tests pass against the current design.",
    )


def _permission_gate(tools: list[AgentTool]) -> GateResult:
    """Every tool granted, or removed from the design.

    A tool sitting ungranted at publish is a permission nobody reviewed — and "we'll sort the
    access out later" is exactly what §9 makes this a gate to prevent.
    """
    ungranted = [tool.tool for tool in tools if not tool.granted]
    if ungranted:
        return GateResult(
            gate="permission_review",
            name="Permission review",
            passed=False,
            reason=(
                f"{len(ungranted)} tool(s) have not been reviewed: {', '.join(sorted(ungranted))}. "
                "Grant each one or remove it from the design."
            ),
        )
    return GateResult(
        gate="permission_review",
        name="Permission review",
        passed=True,
        reason=(
            f"All {len(tools)} tools have been granted."
            if tools
            else "This agent asks for no tools."
        ),
    )


def _warnings(
    agent: Agent,
    steps: list[AgentStep],
    rules: list[AgentEscalationRule],
    tools: list[AgentTool],
    io_rows: list[AgentIoSchema],
    skills: list[AgentSkill],
) -> list[PublishWarning]:
    """Everything worth saying that §9 does not make a gate.

    Shown, never hidden, never in the way. A warning that blocked would be a rule nobody approved;
    a warning that was hidden would be a rule nobody heard.
    """
    warnings: list[PublishWarning] = []

    answered = {rule.situation for rule in rules}
    missing = [situation for situation in Situation if situation not in answered]
    if missing:
        listed = ", ".join(situation.value.replace("_", " ") for situation in missing)
        warnings.append(
            PublishWarning(
                code="situations_unanswered",
                message=(
                    f"{len(missing)} of Form 4's six error situations have no answer: {listed}. "
                    "Nobody has decided what this agent does when they happen."
                ),
            )
        )

    if not agent.prohibited_actions and not any(step.must_never_do for step in steps):
        warnings.append(
            PublishWarning(
                code="nothing_prohibited",
                message=(
                    "This agent has no prohibited actions, at the agent or at any step. An agent "
                    "with no stated boundary is one nobody has drawn a line around."
                ),
            )
        )

    if not io_rows:
        warnings.append(
            PublishWarning(
                code="no_io_schema",
                message=(
                    "No input or output shape is declared, so nothing a run produces can be "
                    "checked against what was expected."
                ),
            )
        )

    if not agent.model_policy_key:
        warnings.append(
            PublishWarning(
                code="no_model_policy",
                message=(
                    "No model policy is named, so this agent will fall back to the workspace "
                    "default rather than a choice somebody made for it."
                ),
            )
        )

    undecided = [link for link in skills if link.resolver_decision_id is None]
    if undecided:
        warnings.append(
            PublishWarning(
                code="skills_without_a_decision",
                message=(
                    f"{len(undecided)} skill(s) were attached without going through the resolver. "
                    "Nothing records why they were chosen or which gates they passed."
                ),
            )
        )

    #  A tool named on a step but never listed under group 7 is access nobody will review.
    listed_tools = {tool.tool.strip().lower() for tool in tools}
    on_steps = {
        step.tool_system.strip().lower()
        for step in steps
        if step.tool_system and step.tool_system.strip()
    }
    unlisted = sorted(on_steps - listed_tools)
    if unlisted:
        warnings.append(
            PublishWarning(
                code="step_tool_not_listed",
                message=(
                    f"{len(unlisted)} tool(s) appear on a step but not in the tool list, so they "
                    f"were never scoped or reviewed: {', '.join(unlisted)}."
                ),
            )
        )

    #  Someone left, and the columns naming them were cleared. Reported rather than enforced by a
    #  constraint: refusing the deletion would block an offboarding and a right-to-erasure
    #  request, which is a worse failure than an Agent nobody has re-pointed yet.
    running = agent.status in (
        AgentStatus.PUBLISHED,
        AgentStatus.ACTIVE,
        AgentStatus.PAUSED,
    )
    if running and not agent.escalation_membership_id and not agent.escalation_label:
        warnings.append(
            PublishWarning(
                code="no_escalation_contact",
                message=(
                    "This agent is running and has nobody to escalate to — the person named has "
                    "most likely left. Name someone before it next fails."
                ),
            )
        )
    if running and not agent.main_approver_membership_id and not agent.main_approver_label:
        warnings.append(
            PublishWarning(
                code="no_approver",
                message=(
                    "This agent has no approver, so its next change cannot be submitted. "
                    "What was approved is unaffected — that is recorded on the published version."
                ),
            )
        )

    if agent.max_retries is None and agent.time_limit_seconds is None:
        warnings.append(
            PublishWarning(
                code="no_limits",
                message=(
                    "Neither a time limit nor a retry count is set, so this agent is bounded only "
                    "by the workspace policy."
                ),
            )
        )

    return warnings


def _next_action(
    agent: Agent, gates: list[GateResult], context: SecurityContext
) -> str:
    blocked = [gate for gate in gates if not gate.passed]
    if agent.status in (AgentStatus.DRAFT, AgentStatus.NEEDS_REVIEW):
        if blocked:
            return blocked[0].reason
        if agent.main_approver_membership_id is None and not agent.main_approver_label:
            return "Name an approver, then send this for approval."
        return "Send this for approval."
    if agent.status == AgentStatus.READY_TO_PUBLISH:
        if blocked:
            return blocked[0].reason
        if agent.main_approver_membership_id == context.membership_id:
            if agent.submitted_by_membership_id == context.membership_id:
                return "You submitted this, so somebody else has to approve it."
            return "Read it, then approve and publish."
        return "Waiting for the named approver."
    if agent.status == AgentStatus.PUBLISHED:
        return "Published. Editing it starts a new draft."
    return ""


async def record_tests(
    session: AsyncSession,
    context: SecurityContext,
    agent_id: uuid.UUID,
    entries: list[dict[str, Any]],
    *,
    expected_version: int,
) -> list[AgentTest]:
    """Write Form 4 section C — the five tests and whatever has been observed of them.

    Recording a result is `edit_draft`: it is part of preparing the design, and a person who may
    not edit the design has no business asserting that it passed. The **approval** of what those
    results mean is the separate act, and it is somebody else's.

    A status other than `not_run` must carry what actually happened. The schema refuses one that
    does not, so a `Pass` is always a claim somebody can check.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    agent = await _get(session, agent_id)
    if agent.status not in (AgentStatus.DRAFT, AgentStatus.NEEDS_REVIEW):
        raise ValidationFailed(
            f"This agent is {agent.status.replace('_', ' ')}. Results are recorded on a draft."
        )
    if agent.version != expected_version:
        raise Conflict("Somebody else changed this agent. Reload it and try again.")

    kinds = [entry["kind"] for entry in entries]
    if len(set(kinds)) != len(kinds):
        raise ValidationFailed("The same test is listed twice.")

    existing = {
        test.kind: test
        for test in await _rows(session, AgentTest, agent_id)
    }
    written: list[AgentTest] = []
    for entry in entries:
        test = existing.get(entry["kind"])
        if test is None:
            test = AgentTest(
                tenant_id=agent.tenant_id, agent_id=agent.id, kind=entry["kind"]
            )
            session.add(test)
        test.sample_situation = entry.get("sample_situation")
        test.expected_result = entry.get("expected_result")
        status = entry.get("status", SandboxTestStatus.NOT_RUN)
        test.status = status
        test.actual_result = entry.get("actual_result")
        #  Who observed it, and when. Stamped here rather than accepted from the caller: a result
        #  somebody could backdate or attribute elsewhere is not evidence.
        observed = status != SandboxTestStatus.NOT_RUN
        test.run_by_membership_id = context.membership_id if observed else None
        test.run_at = _now() if observed else None
        written.append(test)

    agent.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="agent.tests_recorded",
        resource_type="agent",
        resource_id=agent.id,
        actor=context,
        detail={
            "results": {test.kind: test.status for test in written},
        },
    )
    return written


def clear_results(tests: list[AgentTest]) -> int:
    """Set every recorded result back to `not_run`, and say how many were cleared.

    Called when the design changes. A pass recorded against yesterday's steps says nothing about
    today's, and deciding which edits "do not count" is exactly the judgement that lets a stale
    pass through. It costs somebody re-recording results after a small change, and that is the
    right side to err on.

    The *test* survives — its sample situation and expected result are part of the design. Only
    what was observed is cleared, because that is the part that is no longer true.
    """
    cleared = 0
    for test in tests:
        if test.status == SandboxTestStatus.NOT_RUN:
            continue
        test.status = SandboxTestStatus.NOT_RUN
        test.actual_result = None
        test.run_by_membership_id = None
        test.run_at = None
        cleared += 1
    return cleared


async def submit(
    session: AsyncSession,
    context: SecurityContext,
    agent_id: uuid.UUID,
    expected_version: int,
) -> Agent:
    """`edit_draft` — submitting is the last act of writing, not the first act of approving.

    Both gates are checked here as well as at publish. Sending something into somebody's approval
    queue that cannot be approved wastes their time and teaches people to ignore the queue.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    agent = await _get(session, agent_id)
    if agent.version != expected_version:
        raise Conflict("Somebody else changed this agent. Reload it and try again.")
    if agent.status not in (AgentStatus.DRAFT, AgentStatus.NEEDS_REVIEW):
        raise ValidationFailed(
            f"This agent is {agent.status.replace('_', ' ')} and cannot be submitted."
        )
    if agent.main_approver_membership_id is None:
        raise ValidationFailed(
            "Name an approver — a person, not a role — before submitting this."
        )
    if not await _rows(session, AgentStep, agent_id):
        raise ValidationFailed(
            "There is no design to publish. Describe at least one step before submitting."
        )
    _require_gates(await _gates(session, agent_id))

    agent.status = AgentStatus.READY_TO_PUBLISH
    agent.submitted_by_membership_id = context.membership_id
    agent.submitted_at = _now()
    agent.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="agent.submitted",
        resource_type="agent",
        resource_id=agent.id,
        actor=context,
        detail={"approver": str(agent.main_approver_membership_id)},
    )
    return agent


async def withdraw(
    session: AsyncSession,
    context: SecurityContext,
    agent_id: uuid.UUID,
    expected_version: int,
) -> Agent:
    """Take it back. The submitter is cleared so the next submission is judged on its own."""
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    agent = await _get(session, agent_id)
    if agent.version != expected_version:
        raise Conflict("Somebody else changed this agent. Reload it and try again.")
    if agent.status != AgentStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This agent is not waiting for approval.")

    agent.status = AgentStatus.NEEDS_REVIEW
    agent.submitted_by_membership_id = None
    agent.submitted_at = None
    agent.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="agent.withdrawn",
        resource_type="agent",
        resource_id=agent.id,
        actor=context,
    )
    return agent


async def publish(
    session: AsyncSession,
    context: SecurityContext,
    agent_id: uuid.UUID,
    expected_version: int,
) -> AgentVersion:
    """Approve it, and freeze the design that was approved.

    Both gates are re-checked here, not only at submission. A test result can be cleared by an
    edit between the two, and a publish that trusted the earlier check would approve a design
    nobody tested.
    """
    await guard.authorise(session, context, Action.PUBLISH)

    agent = await _get(session, agent_id)
    if agent.version != expected_version:
        raise Conflict(
            "This agent changed since you opened it. Reload and read it again before approving."
        )
    if agent.status != AgentStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This agent has not been submitted for approval.")
    if agent.main_approver_membership_id != context.membership_id:
        raise ValidationFailed("You are not the named approver for this agent.")

    await guard.refuse_self_approval(
        session,
        context,
        submitted_by_membership_id=agent.submitted_by_membership_id or uuid.UUID(int=0),
        resource=guard.Resource(type="agent", id=agent.id),
    )
    _require_gates(await _gates(session, agent_id))

    snapshot = await _snapshot(session, agent)
    version = AgentVersion(
        tenant_id=context.tenant_id,
        agent_id=agent.id,
        snapshot=snapshot,
        name=agent.name,
        job_version_id=agent.job_version_id,
        published_by_membership_id=agent.submitted_by_membership_id,
        approved_by_membership_id=context.membership_id,
    )
    session.add(version)
    await session.flush()

    agent.status = AgentStatus.PUBLISHED
    agent.published_version_id = version.id
    agent.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="agent.published",
        resource_type="agent",
        resource_id=agent.id,
        actor=context,
        detail={
            "version_id": str(version.id),
            "version_no": version.version_no,
            "submitted_by": str(agent.submitted_by_membership_id),
            "steps": len(snapshot.get("steps", [])),
            "granted_tools": sum(
                1 for tool in snapshot.get("tools", []) if tool.get("granted")
            ),
        },
    )
    return version


async def versions(
    session: AsyncSession, context: SecurityContext, agent_id: uuid.UUID
) -> list[AgentVersion]:
    """Everything ever published for this Agent, newest first."""
    await guard.authorise(session, context, Action.VIEW)
    await _get(session, agent_id)
    rows = (
        await session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no.desc())
        )
    ).scalars()
    return list(rows)


# ---------------------------------------------------------------------------- internals


def _require_gates(gates: list[GateResult]) -> None:
    """§9's two gates, enforced. The message is the gate's own — it says what would clear it."""
    for gate in gates:
        if not gate.passed:
            raise ValidationFailed(gate.reason)


async def _gates(session: AsyncSession, agent_id: uuid.UUID) -> list[GateResult]:
    return [
        _tests_gate(await _rows(session, AgentTest, agent_id)),
        _permission_gate(await _rows(session, AgentTool, agent_id)),
    ]


async def _get(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise NotFound("No such agent.")
    return agent


async def _rows(session: AsyncSession, model: Any, agent_id: uuid.UUID) -> list[Any]:
    return list(
        (await session.execute(select(model).where(model.agent_id == agent_id))).scalars().all()
    )


async def _names(
    session: AsyncSession, *membership_ids: uuid.UUID | None
) -> dict[uuid.UUID | None, str | None]:
    wanted = [value for value in membership_ids if value is not None]
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(Membership.id, Membership.display_name).where(Membership.id.in_(wanted))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def _job_facts(session: AsyncSession, agent: Agent) -> tuple[str | None, int | None]:
    from uboss.modules.jobs.models import Job, JobVersion

    name = None
    if agent.job_id is not None:
        name = (
            await session.execute(select(Job.name).where(Job.id == agent.job_id))
        ).scalar_one_or_none()
    version_no = None
    if agent.job_version_id is not None:
        version_no = (
            await session.execute(
                select(JobVersion.version_no).where(JobVersion.id == agent.job_version_id)
            )
        ).scalar_one_or_none()
    return name, version_no


async def _snapshot(session: AsyncSession, agent: Agent) -> dict[str, Any]:
    """The whole design, frozen.

    Every group, plus the test results as they stood at approval. What ran is what was approved,
    and the snapshot is the only thing that can still say so after the draft moves on.
    """
    steps = sorted(await _rows(session, AgentStep, agent.id), key=lambda r: r.position)
    rules = sorted(await _rows(session, AgentEscalationRule, agent.id), key=lambda r: r.situation)
    io_rows = sorted(
        await _rows(session, AgentIoSchema, agent.id), key=lambda r: (r.direction, r.position)
    )
    knowledge = sorted(
        await _rows(session, AgentKnowledgeSource, agent.id), key=lambda r: r.position
    )
    tools = sorted(await _rows(session, AgentTool, agent.id), key=lambda r: r.position)
    skills = sorted(await _rows(session, AgentSkill, agent.id), key=lambda r: r.position)
    shares = await _rows(session, AgentShare, agent.id)
    tests = sorted(await _rows(session, AgentTest, agent.id), key=lambda r: r.kind)

    return {
        "agent": {
            "name": agent.name,
            "objective_id": _plain(agent.objective_id),
            "job_id": _plain(agent.job_id),
            "job_version_id": _plain(agent.job_version_id),
            "trigger": agent.trigger,
            "frequency": agent.frequency,
            "completion_time_value": agent.completion_time_value,
            "completion_time_unit": agent.completion_time_unit,
            "purpose": agent.purpose,
            "instructions": agent.instructions,
            "boundaries": agent.boundaries,
            "prohibited_actions": agent.prohibited_actions,
            "owner_membership_id": _plain(agent.owner_membership_id),
            "visibility": agent.visibility,
            "model_policy_key": agent.model_policy_key,
            "main_approver_membership_id": _plain(agent.main_approver_membership_id),
            "main_approver_label": agent.main_approver_label,
            "escalation_membership_id": _plain(agent.escalation_membership_id),
            "escalation_label": agent.escalation_label,
            "cost_cap_minor_units": agent.cost_cap_minor_units,
            "cost_cap_currency": agent.cost_cap_currency,
            "token_cap": agent.token_cap,
            "time_limit_seconds": agent.time_limit_seconds,
            "max_concurrency": agent.max_concurrency,
            "max_retries": agent.max_retries,
        },
        "steps": [
            {
                "position": step.position,
                "job_step_id": _plain(step.job_step_id),
                "input_used": step.input_used,
                "input_source": step.input_source,
                "tool_system": step.tool_system,
                "agent_action": step.agent_action,
                "output": step.output,
                "output_destination": step.output_destination,
                "approval": step.approval,
                "must_never_do": step.must_never_do,
            }
            for step in steps
        ],
        "escalation_rules": [
            {
                "situation": rule.situation,
                "required_action": rule.required_action,
                "escalate_to_membership_id": _plain(rule.escalate_to_membership_id),
                "escalate_to_label": rule.escalate_to_label,
            }
            for rule in rules
        ],
        "io_schemas": [
            {
                "direction": row.direction,
                "position": row.position,
                "name": row.name,
                "format": row.format,
                "json_schema": row.json_schema,
                "required": row.required,
                "description": row.description,
            }
            for row in io_rows
        ],
        "knowledge_sources": [
            {
                "position": source.position,
                "name": source.name,
                "location": source.location,
                "description": source.description,
                "retention_days": source.retention_days,
                "contains_personal_data": source.contains_personal_data,
            }
            for source in knowledge
        ],
        #  Grants included: what an approved Agent may reach is part of what was approved.
        "tools": [
            {
                "position": tool.position,
                "tool": tool.tool,
                "scopes": list(tool.scopes),
                "purpose": tool.purpose,
                "granted": tool.granted,
                "granted_by_membership_id": _plain(tool.granted_by_membership_id),
                "granted_at": _plain(tool.granted_at),
            }
            for tool in tools
        ],
        "skills": [
            {
                "position": link.position,
                "skill_id": _plain(link.skill_id),
                "resolver_decision_id": _plain(link.resolver_decision_id),
                "route": link.route,
                "notes": link.notes,
            }
            for link in skills
        ],
        "shares": [
            {
                "principal_type": share.principal_type,
                "principal_id": _plain(share.principal_id),
                "label": share.label,
            }
            for share in shares
        ],
        "tests": [
            {
                "kind": test.kind,
                "sample_situation": test.sample_situation,
                "expected_result": test.expected_result,
                "status": test.status,
                "actual_result": test.actual_result,
                "run_by_membership_id": _plain(test.run_by_membership_id),
                "run_at": _plain(test.run_at),
            }
            for test in tests
        ],
    }


def _plain(value: Any) -> Any:
    """UUIDs and datetimes as strings, so the snapshot is JSON a person can read."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
