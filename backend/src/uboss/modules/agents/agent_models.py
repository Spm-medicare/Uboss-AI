"""The Agent itself — Form 4 and `PLAN.md` §9's form groups.

Kept apart from `models.py`, which holds the Skill Registry. Both live in this module because §39
puts the Registry *inside* Agent Builder, but they are different objects with different lifecycles
and one file holding both would hide that.

Eight tables. Seven of them exist because §9 names something a single row cannot hold more than
one of: multiple I/O schemas, several knowledge sources, a tool per scope set, the skills chosen,
the people it is shared with, six named error situations and twelve design rows.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class AgentStatus(enum.StrEnum):
    """The same lifecycle as a Job and an Objective, deliberately.

    One vocabulary across the Builders: somebody who has published an Objective already knows what
    `ready_to_publish` means here.
    """

    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class AgentAudience(enum.StrEnum):
    """§9's access choices: *"Only me, selected users, teams, department, role/subtree or
    workspace."*

    Named for §9's own word — *"Owner, audience and sharing"* — rather than `Visibility`, which the
    Objective already uses for a different set of values. Two enums sharing a name make the
    generated TypeScript fall back to fully-qualified module paths on both of them, which breaks
    the frontend's existing type alias and leaves a contract nobody wants to read.

    `ONLY_ME` is the default because the plan's decision table says so. A default that shared by
    accident is the one mistake this field cannot afford.
    """

    ONLY_ME = "only_me"
    SELECTED_USERS = "selected_users"
    TEAMS = "teams"
    DEPARTMENT = "department"
    ROLE_SUBTREE = "role_subtree"
    WORKSPACE = "workspace"


class SharePrincipal(enum.StrEnum):
    """Who a share names."""

    USER = "user"
    TEAM = "team"
    DEPARTMENT = "department"
    ROLE = "role"
    HIERARCHY_SUBTREE = "hierarchy_subtree"


class Situation(enum.StrEnum):
    """Form 4 section B's six rows, printed on the approved form.

    A closed set rather than a suggestion list, because the sheet prints all six and leaving one
    unanswered is not an omission somebody made — it is a decision nobody took.
    """

    MANDATORY_INPUT_MISSING = "mandatory_input_missing"
    INFORMATION_UNCLEAR = "information_unclear"
    INFORMATION_CONFLICTS = "information_conflicts"
    TOOL_OR_SYSTEM_FAILS = "tool_or_system_fails"
    APPROVAL_REJECTED = "approval_rejected"
    PROHIBITED_ACTION_REQUESTED = "prohibited_action_requested"


class Direction(enum.StrEnum):
    """§9 group 4: *"Multiple input/output schemas."*"""

    INPUT = "input"
    OUTPUT = "output"


class Agent(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """One Job Agent.

    **It runs an approved version, not a draft.** `job_version_id` points at the immutable
    `job_versions` row. An Agent bound to a mutable draft would change what it does the moment
    somebody edited a form, which is the thing Operation is built to make impossible.

    **Every limit is a ceiling, and null means the tenant's policy decides.** A number here is
    this Agent's own bound and is never raised by a run.
    """

    __tablename__ = "agents"

    #  Group 1 — identity and the linked Job version.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    job_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(120), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(60), nullable=True)
    completion_time_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_time_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)

    #  Group 2 — purpose, instructions, boundaries, prohibited actions. Four columns rather than
    #  one description: a boundary and a prohibition are read by different people for different
    #  reasons, and a reviewer needs to find each on its own.
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    boundaries: Mapped[str | None] = mapped_column(Text, nullable=True)
    prohibited_actions: Mapped[str | None] = mapped_column(Text, nullable=True)

    #  Group 3 — owner and audience.
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="only_me"
    )

    #  Group 5 — a policy key, never a model name. CLAUDE.md forbids a hard-coded model in domain
    #  logic; the gateway resolves this. No vocabulary is invented: v3.2 approves *"Claude first
    #  through provider-neutral Gateway"* and names no policy catalogue.
    model_policy_key: Mapped[str | None] = mapped_column(String(60), nullable=True)

    #  Group 8 — Form 4's "Main Approver *" and "Error Escalation To *". A membership where the
    #  person is known, a label where the sheet named a role.
    main_approver_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    main_approver_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    escalation_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    escalation_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    #  Group 9 — cost, token, time, concurrency and retries.
    cost_cap_minor_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cap_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    token_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    submitted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_agents_tenant_objective",
            ondelete="SET NULL (objective_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_agents_tenant_job",
            ondelete="SET NULL (job_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "job_version_id"],
            ["job_versions.tenant_id", "job_versions.id"],
            name="fk_agents_tenant_job_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_agents_tenant_owner",
            ondelete="SET NULL (owner_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "main_approver_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_agents_tenant_approver",
            ondelete="SET NULL (main_approver_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "escalation_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_agents_tenant_escalation",
            ondelete="SET NULL (escalation_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submitted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_agents_tenant_submitter",
            ondelete="SET NULL (submitted_by_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_agents_tenant_creator",
            ondelete="SET NULL (created_by_membership_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_agents_tenant_id"),
        Index("ix_agents_tenant_status", "tenant_id", "status"),
        Index("ix_agents_tenant_owner", "tenant_id", "owner_membership_id"),
        Index("ix_agents_tenant_job", "tenant_id", "job_id"),
    )


class AgentStep(Base, PrimaryKey, TenantOwned, Timestamps):
    """One row of Form 4 section A — nine columns, in the sheet's own order.

    `must_never_do` is the sheet's *"Agent Must Never Do"* and §9's *"prohibited actions"*. It is
    per step because what an agent must never do at step 4 is not what it must never do at step 9.
    """

    __tablename__ = "agent_steps"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Where this row came from. Form 4 is *"generated from Forms 2 and 3"*, and keeping the link
    #: is what lets a reviewer see what was changed on the way.
    job_step_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    input_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval: Mapped[str | None] = mapped_column(String(120), nullable=True)
    must_never_do: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_steps_agent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "job_step_id"],
            ["job_steps.tenant_id", "job_steps.id"],
            name="fk_agent_steps_job_step",
            ondelete="SET NULL (job_step_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_agent_steps_tenant_id"),
        UniqueConstraint("tenant_id", "agent_id", "position", name="uq_agent_steps_position"),
        CheckConstraint("position >= 1", name="ck_agent_steps_position_positive"),
    )


class AgentEscalationRule(Base, PrimaryKey, TenantOwned, Timestamps):
    """One of Form 4 section B's six situations, and what the Agent must do about it.

    One row per situation. Two answers for "approval is rejected" would be two policies, and
    nothing in the design says which one wins.
    """

    __tablename__ = "agent_escalation_rules"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    situation: Mapped[str] = mapped_column(String(40), nullable=False)
    required_action: Mapped[str] = mapped_column(Text, nullable=False)
    escalate_to_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    escalate_to_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_rules_agent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "escalate_to_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_agent_rules_escalate_to",
            ondelete="SET NULL (escalate_to_membership_id)",
        ),
        UniqueConstraint("tenant_id", "agent_id", "situation", name="uq_agent_rules_situation"),
        CheckConstraint(
            "length(btrim(required_action)) > 0", name="ck_agent_rules_action_not_blank"
        ),
    )


class AgentIoSchema(Base, PrimaryKey, TenantOwned, Timestamps):
    """One input or output shape. §9 group 4 says *"multiple"*, so this is a table."""

    __tablename__ = "agent_io_schemas"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    format: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: JSON Schema, so a run can validate against it rather than hoping.
    json_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_io_agent",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "agent_id", "direction", "name", name="uq_agent_io_name"),
        CheckConstraint("position >= 1", name="ck_agent_io_position_positive"),
    )


class AgentKnowledgeSource(Base, PrimaryKey, TenantOwned, Timestamps):
    """One knowledge source, and how long what it holds is kept.

    §9 group 6 says *"and retention"*, so retention lives with the source rather than in one
    setting for the whole Agent: a policy document and a customer export do not keep for the same
    length of time. Null means the tenant's own retention policy decides.
    """

    __tablename__ = "agent_knowledge_sources"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The privacy gate reads this. A source nobody classified is one nobody can honour a deletion
    #: request against.
    contains_personal_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_knowledge_agent",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "agent_id", "name", name="uq_agent_knowledge_name"),
        CheckConstraint("position >= 1", name="ck_agent_knowledge_position_positive"),
    )


class AgentTool(Base, PrimaryKey, TenantOwned, Timestamps):
    """A tool the Agent needs, and the explicit scopes it needs on it.

    §9: *"Tool suggestions never grant access."* `granted` is false until somebody with the
    authority says otherwise, and the schema refuses a granted row that names no grantor. A design
    where a suggestion carried access would mean an agent acquiring a permission because a form
    proposed one.
    """

    __tablename__ = "agent_tools"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tool: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Non-empty. A tool with no scope is a tool with every scope.
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    granted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    granted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_tools_agent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "granted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_agent_tools_grantor",
            ondelete="SET NULL (granted_by_membership_id)",
        ),
        UniqueConstraint("tenant_id", "agent_id", "tool", name="uq_agent_tools_tool"),
        CheckConstraint("position >= 1", name="ck_agent_tools_position_positive"),
    )


class AgentSkill(Base, PrimaryKey, TenantOwned):
    """A skill this Agent uses, and the resolver decision that chose it.

    `resolver_decision_id` is what makes *"why does this agent use that skill"* answerable from the
    record — the gates that ran, the candidates that were refused, the route taken — rather than
    from somebody's memory. `RESTRICT` on both: a skill in use cannot be removed out from under
    the Agent using it, and the decision that justified it cannot be deleted either.
    """

    __tablename__ = "agent_skills"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    resolver_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_resolver_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    route: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_skills_agent",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "agent_id", "skill_id", name="uq_agent_skills_skill"),
        CheckConstraint("position >= 1", name="ck_agent_skills_position_positive"),
    )


class AgentShare(Base, PrimaryKey, TenantOwned):
    """One principal an Agent is shared with.

    Only `selected_users` and `teams` need rows; `department`, `role_subtree` and `workspace` are
    answered by the caller's own position in the hierarchy, and `only_me` names nobody.
    """

    __tablename__ = "agent_shares"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    principal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_shares_agent",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "agent_id",
            "principal_type",
            "principal_id",
            name="uq_agent_shares_principal",
        ),
    )
