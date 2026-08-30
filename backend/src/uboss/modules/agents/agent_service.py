"""Creating and editing an Agent draft.

The same shape as the Job's service, deliberately: authorise through the one guard, match the
version, replace child collections wholesale, write an audit event, commit together. A person who
has used one Builder should find the next behaves the same way, and so should whoever reads this.

Two things here are not in the Job's service, and both come straight from §9:

**Tool suggestions never grant access.** Saving a draft writes `agent_tools` rows with `granted`
false and never touches the flag on an existing row. Granting is `grant_tool`, a separate call
behind `manage_access`, and it records who granted it and when. A save that could set the flag
would be exactly the shortcut the sentence forbids.

**A skill is attached with the decision that chose it.** `agent_skills.resolver_decision_id`
points at the 5.2 record, and the route is copied from it rather than supplied by the caller — a
caller who could name the route could claim a candidate was *reused* when the resolver had
actually blocked it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.agents.agent_models import (
    Agent,
    AgentAudience,
    AgentEscalationRule,
    AgentIoSchema,
    AgentKnowledgeSource,
    AgentShare,
    AgentSkill,
    AgentStatus,
    AgentStep,
    AgentTool,
    Direction,
    SharePrincipal,
    Situation,
)
from uboss.modules.agents.agent_schemas import (
    MAX_IO_SCHEMAS,
    MAX_KNOWLEDGE_SOURCES,
    MAX_SHARES,
    MAX_SKILLS,
    MAX_STEPS,
    MAX_TOOLS,
    SITUATION_LABELS,
    AgentCard,
    AgentCreate,
    AgentList,
    AgentRead,
    AgentStepRead,
    AgentUpdate,
    EscalationRuleRead,
    IoSchemaRead,
    KnowledgeSourceRead,
    ShareRead,
    SkillRead,
    ToolRead,
)
from uboss.modules.agents.models import Skill, SkillResolverDecision
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.jobs.models import Job, JobVersion
from uboss.modules.objectives.models import Objective

#: A draft is editable; anything past it is not. Same rule as the Job.
EDITABLE = (AgentStatus.DRAFT, AgentStatus.NEEDS_REVIEW)

#: §9's access choices that are answered by a person's position rather than by naming principals.
#: Sending shares alongside one of these is a contradiction, not an extra.
POSITIONAL_VISIBILITY = (
    AgentAudience.ONLY_ME,
    AgentAudience.DEPARTMENT,
    AgentAudience.ROLE_SUBTREE,
    AgentAudience.WORKSPACE,
)

_SCALAR_FIELDS = frozenset(
    {
        "name",
        "objective_id",
        "job_id",
        "job_version_id",
        "trigger",
        "frequency",
        "completion_time_value",
        "completion_time_unit",
        "purpose",
        "instructions",
        "boundaries",
        "prohibited_actions",
        "owner_membership_id",
        "visibility",
        "model_policy_key",
        "main_approver_membership_id",
        "main_approver_label",
        "escalation_membership_id",
        "escalation_label",
        "cost_cap_minor_units",
        "cost_cap_currency",
        "token_cap",
        "time_limit_seconds",
        "max_concurrency",
        "max_retries",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


async def list_agents(
    session: AsyncSession,
    context: SecurityContext,
    *,
    status: str | None = None,
    job_id: uuid.UUID | None = None,
    include_archived: bool = False,
) -> AgentList:
    await guard.authorise(session, context, Action.VIEW)

    steps = (
        select(AgentStep.agent_id.label("agent_id"), func.count().label("n"))
        .group_by(AgentStep.agent_id)
        .subquery()
    )
    skills = (
        select(AgentSkill.agent_id.label("agent_id"), func.count().label("n"))
        .group_by(AgentSkill.agent_id)
        .subquery()
    )

    statement = (
        select(
            Agent,
            Membership.display_name,
            Job.name,
            func.coalesce(steps.c.n, 0),
            func.coalesce(skills.c.n, 0),
        )
        .outerjoin(Membership, Membership.id == Agent.owner_membership_id)
        .outerjoin(Job, Job.id == Agent.job_id)
        .outerjoin(steps, steps.c.agent_id == Agent.id)
        .outerjoin(skills, skills.c.agent_id == Agent.id)
        .order_by(Agent.updated_at.desc())
    )
    if not include_archived:
        statement = statement.where(Agent.archived_at.is_(None))
    if status:
        statement = statement.where(Agent.status == status)
    if job_id is not None:
        statement = statement.where(Agent.job_id == job_id)

    rows = (await session.execute(statement)).all()
    total = (
        await session.execute(
            select(func.count()).select_from(Agent).where(Agent.archived_at.is_(None))
        )
    ).scalar_one()

    return AgentList(
        agents=[
            AgentCard(
                id=agent.id,
                name=agent.name,
                status=AgentStatus(agent.status),
                owner_name=owner_name,
                job_name=job_name,
                visibility=AgentAudience(agent.visibility),
                step_count=step_count,
                skill_count=skill_count,
                updated_at=agent.updated_at,
            )
            for agent, owner_name, job_name, step_count, skill_count in rows
        ],
        is_empty=total == 0,
    )


async def read(
    session: AsyncSession, context: SecurityContext, agent_id: uuid.UUID
) -> AgentRead:
    await guard.authorise(session, context, Action.VIEW)
    return await _describe(session, await _get(session, agent_id))


async def create(
    session: AsyncSession, context: SecurityContext, payload: AgentCreate
) -> Agent:
    """Start a draft from a name.

    Naming a Job carries its objective and its **published version** across. Form 4 is *"generated
    from Forms 2 and 3"*, and a person who has already chosen the job should not have to find its
    version number as well — nor should they be able to pick a different one by accident.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    objective_id = payload.objective_id
    job_version_id: uuid.UUID | None = None

    if payload.job_id is not None:
        job = (
            await session.execute(select(Job).where(Job.id == payload.job_id))
        ).scalar_one_or_none()
        if job is None:
            raise ValidationFailed("That job is not in this workspace.")
        objective_id = objective_id or job.objective_id
        job_version_id = job.published_version_id

    agent = Agent(
        tenant_id=context.tenant_id,
        name=payload.name.strip(),
        job_id=payload.job_id,
        objective_id=objective_id,
        job_version_id=job_version_id,
        owner_membership_id=context.membership_id,
        created_by_membership_id=context.membership_id,
        status=AgentStatus.DRAFT,
        visibility=AgentAudience.ONLY_ME,
    )
    session.add(agent)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="agent.created",
        resource_type="agent",
        resource_id=agent.id,
        actor=context,
        detail={"name": agent.name, "job_id": str(payload.job_id) if payload.job_id else None},
    )
    return agent


async def update(
    session: AsyncSession,
    context: SecurityContext,
    agent_id: uuid.UUID,
    payload: AgentUpdate,
) -> Agent:
    """Save the draft.

    Each collection is replaced wholesale when it is sent and left alone when it is not — the same
    reason as everywhere else here: a diff on the client is a second implementation of what the
    server already does, and the two disagree the first time somebody reorders a row.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    agent = await _get(session, agent_id)
    if agent.status not in EDITABLE:
        raise ValidationFailed(
            f"This agent is {agent.status.replace('_', ' ')} and cannot be edited."
        )
    if agent.version != payload.expected_version:
        raise Conflict(
            "Somebody else saved this agent while you were editing. Reload it and apply your "
            "change again."
        )

    changes = payload.model_dump(exclude_unset=True)
    changes.pop("expected_version", None)
    steps = changes.pop("steps", None)
    rules = changes.pop("escalation_rules", None)
    io_schemas = changes.pop("io_schemas", None)
    knowledge = changes.pop("knowledge_sources", None)
    tools = changes.pop("tools", None)
    skills = changes.pop("skills", None)
    shares = changes.pop("shares", None)

    for field, value in changes.items():
        if field in _SCALAR_FIELDS:
            setattr(agent, field, value)

    for column, role in (
        ("owner_membership_id", "owner"),
        ("main_approver_membership_id", "approver"),
        ("escalation_membership_id", "escalation contact"),
    ):
        if changes.get(column) is not None:
            await _require_member(session, changes[column], role)

    if changes.get("job_version_id") is not None:
        await _require_job_version(session, agent, changes["job_version_id"])

    if steps is not None:
        await _replace_steps(session, agent, steps)
    if rules is not None:
        await _replace_rules(session, agent, rules)
    if io_schemas is not None:
        await _replace_io(session, agent, io_schemas)
    if knowledge is not None:
        await _replace_knowledge(session, agent, knowledge)
    if tools is not None:
        await _replace_tools(session, agent, tools)
    if skills is not None:
        await _replace_skills(session, agent, skills)
    if shares is not None:
        await _replace_shares(session, agent, shares)

    _refuse_contradictory_sharing(agent, shares)

    agent.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="agent.updated",
        resource_type="agent",
        resource_id=agent.id,
        actor=context,
        #  Which fields, never their values. An Agent carries a company's method and its
        #  instructions to a model; an audit trail is not the place to keep a second copy.
        detail={
            "fields": sorted(changes),
            "replaced": sorted(
                name
                for name, sent in (
                    ("steps", steps),
                    ("escalation_rules", rules),
                    ("io_schemas", io_schemas),
                    ("knowledge_sources", knowledge),
                    ("tools", tools),
                    ("skills", skills),
                    ("shares", shares),
                )
                if sent is not None
            ),
        },
    )
    return agent


async def grant_tool(
    session: AsyncSession,
    context: SecurityContext,
    agent_id: uuid.UUID,
    tool_id: uuid.UUID,
    *,
    granted: bool,
    expected_version: int,
) -> AgentTool:
    """Grant or withdraw one tool's access.

    §9: *"Tool suggestions never grant access."* This is the separate act that does, and it is
    behind `manage_access` rather than `edit_draft` — designing an agent and deciding what it may
    reach are different authorities, and a person who has one does not automatically have the
    other.
    """
    await guard.authorise(session, context, Action.MANAGE_ACCESS)

    agent = await _get(session, agent_id)
    if agent.version != expected_version:
        raise Conflict("Somebody else changed this agent. Reload it and try again.")

    tool = (
        await session.execute(
            select(AgentTool).where(AgentTool.id == tool_id, AgentTool.agent_id == agent_id)
        )
    ).scalar_one_or_none()
    if tool is None:
        raise NotFound("No such tool on this agent.")

    tool.granted = granted
    tool.granted_by_membership_id = context.membership_id if granted else None
    tool.granted_at = _now() if granted else None
    agent.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="agent.tool_granted" if granted else "agent.tool_withdrawn",
        resource_type="agent",
        resource_id=agent.id,
        actor=context,
        detail={"tool": tool.tool, "scopes": list(tool.scopes)},
    )
    return tool


async def archive(
    session: AsyncSession,
    context: SecurityContext,
    agent_id: uuid.UUID,
    expected_version: int,
) -> Agent:
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    agent = await _get(session, agent_id)
    if agent.version != expected_version:
        raise Conflict("Somebody else changed this agent. Reload it and try again.")
    if agent.archived_at is not None:
        return agent

    agent.archived_at = _now()
    agent.status = AgentStatus.ARCHIVED
    agent.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="agent.archived",
        resource_type="agent",
        resource_id=agent.id,
        actor=context,
        detail={"name": agent.name},
    )
    return agent


# ---------------------------------------------------------------------------- internals


async def _get(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise NotFound("No such agent.")
    return agent


async def _require_member(
    session: AsyncSession, membership_id: uuid.UUID, role: str
) -> None:
    member = (
        await session.execute(select(Membership).where(Membership.id == membership_id))
    ).scalar_one_or_none()
    if member is None:
        raise ValidationFailed(f"That {role} is not a member of this workspace.")


async def _require_job_version(
    session: AsyncSession, agent: Agent, version_id: uuid.UUID
) -> None:
    """The version has to exist, and it has to belong to the job this Agent runs.

    Without the second half an Agent could be pointed at another job's approved version, which
    would run the wrong method under the right name.
    """
    version = (
        await session.execute(select(JobVersion).where(JobVersion.id == version_id))
    ).scalar_one_or_none()
    if version is None:
        raise ValidationFailed("That job version is not in this workspace.")
    if agent.job_id is not None and version.job_id != agent.job_id:
        raise ValidationFailed(
            "That version belongs to a different job. An agent runs a version of the job it is "
            "for."
        )
    if agent.job_id is None:
        agent.job_id = version.job_id


def _refuse_contradictory_sharing(agent: Agent, shares: list[Any] | None) -> None:
    """`only_me` with a share list is two answers to one question.

    Refused rather than silently preferring one, because either choice would be somebody's
    intention discarded without being told.
    """
    if shares is None:
        return
    if shares and AgentAudience(agent.visibility) in POSITIONAL_VISIBILITY:
        readable = agent.visibility.replace("_", " ")
        raise ValidationFailed(
            f"AgentAudience is set to {readable!r}, which names nobody, but this save also lists "
            "people to share with. Choose 'selected users' or 'teams', or remove the list."
        )


async def _replace_steps(
    session: AsyncSession, agent: Agent, steps: list[dict[str, Any]]
) -> None:
    if len(steps) > MAX_STEPS:
        raise ValidationFailed(
            f"An agent design may have up to {MAX_STEPS} steps. Past that, split it in two."
        )
    _refuse_duplicate_positions(steps, "step")
    await session.execute(delete(AgentStep).where(AgentStep.agent_id == agent.id))
    for step in steps:
        session.add(AgentStep(tenant_id=agent.tenant_id, agent_id=agent.id, **step))


async def _replace_rules(
    session: AsyncSession, agent: Agent, rules: list[dict[str, Any]]
) -> None:
    """Form 4's six situations. One answer each — two would be two policies."""
    seen = [rule["situation"] for rule in rules]
    if len(set(seen)) != len(seen):
        raise ValidationFailed(
            "Each situation may have one required action. Two answers for the same situation is "
            "two policies, and nothing says which one wins."
        )
    await session.execute(
        delete(AgentEscalationRule).where(AgentEscalationRule.agent_id == agent.id)
    )
    for rule in rules:
        session.add(
            AgentEscalationRule(tenant_id=agent.tenant_id, agent_id=agent.id, **rule)
        )


async def _replace_io(
    session: AsyncSession, agent: Agent, schemas: list[dict[str, Any]]
) -> None:
    if len(schemas) > MAX_IO_SCHEMAS:
        raise ValidationFailed(f"Up to {MAX_IO_SCHEMAS} input/output schemas.")
    named = [(row["direction"], row["name"].strip().lower()) for row in schemas]
    if len(set(named)) != len(named):
        raise ValidationFailed(
            "Two inputs or two outputs share a name. A run could not tell which one it was "
            "given."
        )
    await session.execute(delete(AgentIoSchema).where(AgentIoSchema.agent_id == agent.id))
    for row in schemas:
        session.add(AgentIoSchema(tenant_id=agent.tenant_id, agent_id=agent.id, **row))


async def _replace_knowledge(
    session: AsyncSession, agent: Agent, sources: list[dict[str, Any]]
) -> None:
    if len(sources) > MAX_KNOWLEDGE_SOURCES:
        raise ValidationFailed(f"Up to {MAX_KNOWLEDGE_SOURCES} knowledge sources.")
    _refuse_duplicate_positions(sources, "knowledge source")
    await session.execute(
        delete(AgentKnowledgeSource).where(AgentKnowledgeSource.agent_id == agent.id)
    )
    for source in sources:
        session.add(
            AgentKnowledgeSource(tenant_id=agent.tenant_id, agent_id=agent.id, **source)
        )


async def _replace_tools(
    session: AsyncSession, agent: Agent, tools: list[dict[str, Any]]
) -> None:
    """Rewrites the suggestions and **preserves every grant that still applies**.

    A save that dropped the grants would mean editing a form silently revoked an agent's access,
    and re-granting it would become a habit rather than a decision. A tool removed from the form
    loses its grant, which is correct: the tool is no longer part of the design.
    """
    if len(tools) > MAX_TOOLS:
        raise ValidationFailed(f"Up to {MAX_TOOLS} tools.")
    _refuse_duplicate_positions(tools, "tool")

    existing = {
        row.tool: row
        for row in (
            await session.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))
        )
        .scalars()
        .all()
    }
    await session.execute(delete(AgentTool).where(AgentTool.agent_id == agent.id))
    for tool in tools:
        previous = existing.get(tool["tool"])
        #  Carried over only when the scopes are unchanged. A grant was given for a particular
        #  set of scopes, and widening them is a new decision for the same person to take again.
        keep = (
            previous is not None
            and previous.granted
            and list(previous.scopes) == list(tool["scopes"])
        )
        session.add(
            AgentTool(
                tenant_id=agent.tenant_id,
                agent_id=agent.id,
                granted=keep,
                granted_by_membership_id=(
                    previous.granted_by_membership_id if keep and previous else None
                ),
                granted_at=previous.granted_at if keep and previous else None,
                **tool,
            )
        )


async def _replace_skills(
    session: AsyncSession, agent: Agent, skills: list[dict[str, Any]]
) -> None:
    """The route is copied from the decision, never taken from the caller.

    A caller who could name the route could record a candidate as *reused* when the resolver had
    blocked it — and the record is the whole reason the decision is linked at all.
    """
    if len(skills) > MAX_SKILLS:
        raise ValidationFailed(f"Up to {MAX_SKILLS} skills.")
    _refuse_duplicate_positions(skills, "skill")

    chosen = [row["skill_id"] for row in skills]
    if len(set(chosen)) != len(chosen):
        raise ValidationFailed("The same skill is listed twice.")

    await session.execute(delete(AgentSkill).where(AgentSkill.agent_id == agent.id))
    for row in skills:
        skill = (
            await session.execute(select(Skill).where(Skill.id == row["skill_id"]))
        ).scalar_one_or_none()
        if skill is None:
            raise ValidationFailed("That skill is not in the registry for this workspace.")

        route: str | None = None
        decision_id = row.get("resolver_decision_id")
        if decision_id is not None:
            decision = (
                await session.execute(
                    select(SkillResolverDecision).where(
                        SkillResolverDecision.id == decision_id
                    )
                )
            ).scalar_one_or_none()
            if decision is None:
                raise ValidationFailed("That resolver decision is not in this workspace.")
            if decision.route == "blocked":
                raise ValidationFailed(
                    "That decision blocked the requirement. A blocked decision is not a reason "
                    "to use a skill."
                )
            route = decision.route

        session.add(
            AgentSkill(
                tenant_id=agent.tenant_id,
                agent_id=agent.id,
                position=row["position"],
                skill_id=row["skill_id"],
                resolver_decision_id=decision_id,
                route=route,
                notes=row.get("notes"),
            )
        )


async def _replace_shares(
    session: AsyncSession, agent: Agent, shares: list[dict[str, Any]]
) -> None:
    if len(shares) > MAX_SHARES:
        raise ValidationFailed(f"Up to {MAX_SHARES} people or groups.")
    named = [(row["principal_type"], row.get("principal_id"), row.get("label")) for row in shares]
    if len(set(named)) != len(named):
        raise ValidationFailed("The same person or group is listed twice.")
    await session.execute(delete(AgentShare).where(AgentShare.agent_id == agent.id))
    for share in shares:
        session.add(AgentShare(tenant_id=agent.tenant_id, agent_id=agent.id, **share))


def _refuse_duplicate_positions(rows: list[dict[str, Any]], what: str) -> None:
    positions = [row["position"] for row in rows]
    if len(set(positions)) != len(positions):
        raise ValidationFailed(f"Two {what} rows share a position. Renumber them.")


async def _describe(session: AsyncSession, agent: Agent) -> AgentRead:
    """One Agent in full, so a form renders from one request."""
    steps = (
        (
            await session.execute(
                select(AgentStep)
                .where(AgentStep.agent_id == agent.id)
                .order_by(AgentStep.position)
            )
        )
        .scalars()
        .all()
    )
    rules = (
        (
            await session.execute(
                select(AgentEscalationRule)
                .where(AgentEscalationRule.agent_id == agent.id)
                .order_by(AgentEscalationRule.situation)
            )
        )
        .scalars()
        .all()
    )
    io_rows = (
        (
            await session.execute(
                select(AgentIoSchema)
                .where(AgentIoSchema.agent_id == agent.id)
                .order_by(AgentIoSchema.direction, AgentIoSchema.position)
            )
        )
        .scalars()
        .all()
    )
    knowledge = (
        (
            await session.execute(
                select(AgentKnowledgeSource)
                .where(AgentKnowledgeSource.agent_id == agent.id)
                .order_by(AgentKnowledgeSource.position)
            )
        )
        .scalars()
        .all()
    )
    tools = (
        (
            await session.execute(
                select(AgentTool)
                .where(AgentTool.agent_id == agent.id)
                .order_by(AgentTool.position)
            )
        )
        .scalars()
        .all()
    )
    skill_rows = (
        await session.execute(
            select(AgentSkill, Skill)
            .join(Skill, Skill.id == AgentSkill.skill_id)
            .where(AgentSkill.agent_id == agent.id)
            .order_by(AgentSkill.position)
        )
    ).all()
    shares = (
        (
            await session.execute(
                select(AgentShare).where(AgentShare.agent_id == agent.id)
            )
        )
        .scalars()
        .all()
    )

    owner_name = await _display_name(session, agent.owner_membership_id)
    approver_name = await _display_name(session, agent.main_approver_membership_id)
    escalation_name = await _display_name(session, agent.escalation_membership_id)

    objective_name = None
    if agent.objective_id is not None:
        objective_name = (
            await session.execute(
                select(Objective.title).where(Objective.id == agent.objective_id)
            )
        ).scalar_one_or_none()
    job_name = None
    if agent.job_id is not None:
        job_name = (
            await session.execute(select(Job.name).where(Job.id == agent.job_id))
        ).scalar_one_or_none()
    job_version_no = None
    if agent.job_version_id is not None:
        job_version_no = (
            await session.execute(
                select(JobVersion.version_no).where(JobVersion.id == agent.job_version_id)
            )
        ).scalar_one_or_none()

    answered = {rule.situation for rule in rules}

    return AgentRead(
        id=agent.id,
        version=agent.version,
        status=AgentStatus(agent.status),
        name=agent.name,
        objective_id=agent.objective_id,
        objective_name=objective_name,
        job_id=agent.job_id,
        job_name=job_name,
        job_version_id=agent.job_version_id,
        job_version_no=job_version_no,
        trigger=agent.trigger,
        frequency=agent.frequency,
        completion_time_value=agent.completion_time_value,
        completion_time_unit=agent.completion_time_unit,
        purpose=agent.purpose,
        instructions=agent.instructions,
        boundaries=agent.boundaries,
        prohibited_actions=agent.prohibited_actions,
        owner_membership_id=agent.owner_membership_id,
        owner_name=owner_name,
        visibility=AgentAudience(agent.visibility),
        shares=[
            ShareRead(
                id=share.id,
                principal_type=SharePrincipal(share.principal_type),
                principal_id=share.principal_id,
                label=share.label,
            )
            for share in shares
        ],
        io_schemas=[
            IoSchemaRead(
                id=row.id,
                position=row.position,
                direction=Direction(row.direction),
                name=row.name,
                format=row.format,
                json_schema=row.json_schema,
                required=row.required,
                description=row.description,
            )
            for row in io_rows
        ],
        model_policy_key=agent.model_policy_key,
        knowledge_sources=[
            KnowledgeSourceRead(
                id=source.id,
                position=source.position,
                name=source.name,
                location=source.location,
                description=source.description,
                retention_days=source.retention_days,
                contains_personal_data=source.contains_personal_data,
            )
            for source in knowledge
        ],
        tools=[
            ToolRead(
                id=tool.id,
                position=tool.position,
                tool=tool.tool,
                scopes=list(tool.scopes),
                purpose=tool.purpose,
                granted=tool.granted,
                granted_by_membership_id=tool.granted_by_membership_id,
                granted_at=tool.granted_at,
            )
            for tool in tools
        ],
        main_approver_membership_id=agent.main_approver_membership_id,
        main_approver_name=approver_name,
        main_approver_label=agent.main_approver_label,
        escalation_membership_id=agent.escalation_membership_id,
        escalation_name=escalation_name,
        escalation_label=agent.escalation_label,
        escalation_rules=[
            EscalationRuleRead(
                id=rule.id,
                situation=Situation(rule.situation),
                label=SITUATION_LABELS[rule.situation],
                required_action=rule.required_action,
                escalate_to_membership_id=rule.escalate_to_membership_id,
                escalate_to_label=rule.escalate_to_label,
            )
            for rule in rules
        ],
        cost_cap_minor_units=agent.cost_cap_minor_units,
        cost_cap_currency=agent.cost_cap_currency,
        token_cap=agent.token_cap,
        time_limit_seconds=agent.time_limit_seconds,
        max_concurrency=agent.max_concurrency,
        max_retries=agent.max_retries,
        steps=[
            AgentStepRead(
                id=step.id,
                position=step.position,
                job_step_id=step.job_step_id,
                input_used=step.input_used,
                input_source=step.input_source,
                tool_system=step.tool_system,
                agent_action=step.agent_action,
                output=step.output,
                output_destination=step.output_destination,
                approval=step.approval,
                must_never_do=step.must_never_do,
            )
            for step in steps
        ],
        skills=[
            SkillRead(
                id=link.id,
                position=link.position,
                skill_id=skill.id,
                name=skill.name,
                catalogue_id=skill.catalogue_id,
                autonomy=skill.autonomy,
                exclusions=skill.exclusions,
                resolver_decision_id=link.resolver_decision_id,
                route=link.route,
                notes=link.notes,
            )
            for link, skill in skill_rows
        ],
        situations_unanswered=[
            situation for situation in Situation if situation not in answered
        ],
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


async def _display_name(
    session: AsyncSession, membership_id: uuid.UUID | None
) -> str | None:
    if membership_id is None:
        return None
    return (
        await session.execute(
            select(Membership.display_name).where(Membership.id == membership_id)
        )
    ).scalar_one_or_none()
