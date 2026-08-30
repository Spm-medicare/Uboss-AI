"""The Supervisor — `PLAN.md` §10.

A Supervisor *"monitors and coordinates published Job Agents"*. It performs no business action
itself; CLAUDE.md states the boundary in one line — **Supervisor coordinates; bounded Job/Synced
workers perform business actions.**

**Two scopes, and they are independent.** §10 makes both mandatory and they answer different
questions: *whose Agents are watched*, and *who may control this*. Nothing in this module derives
one from the other — there is no foreign key between `SupervisorSupervised` and
`SupervisorHandler`, no shared column and no rule that reads a department and produces a handler.
A department head may control a Supervisor watching Agents whose outputs they may not read.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, time

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
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class SupervisorKind(enum.StrEnum):
    """The two §10 approves.

    Workspace-wide is *"restricted and may be added later"*, so it is not here. A third value now
    would be building against a decision nobody has taken.
    """

    PERSONAL = "personal"
    DEPARTMENT = "department"


class HandlerRole(enum.StrEnum):
    """§10's six, in the order the plan lists them — which is increasing authority.

    The order is load-bearing: 6.2 compares roles, and a list reordered for tidiness would quietly
    change who may do what.
    """

    VIEWER = "viewer"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    MANAGER = "manager"
    OWNER = "owner"


class SupervisorStatus(enum.StrEnum):
    """The same lifecycle as every other designed object here."""

    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class Supervisor(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """One Supervisor Agent.

    `owner_membership_id` is **not null**: a Supervisor with no owner is one nobody is answerable
    for, and a personal Supervisor's entire scope is defined by whose it is. Its foreign key is
    `RESTRICT` rather than `SET NULL` for the same reason — removing somebody who owns a
    Supervisor should make you reassign it first, which is a decision rather than a cascade.
    """

    __tablename__ = "supervisors"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    #: The department it supervises. Required for a department Supervisor, forbidden for a
    #: personal one — a check constraint says so rather than a service remembering to.
    org_node_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    objective_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)

    #  Group 4 — the trigger. The workbook's list, so text: every one of its lists ends in
    #  `Other`. The schedule itself is `SupervisorSchedule`, and the execution order §10 asks for
    #  is already `SupervisorSupervised.position` — a second column would be a second answer.
    trigger: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #  Group 5 — routing and concurrency. §10 names no routing vocabulary, so this is free text
    #  until one is approved; `docs/architecture/SUPERVISOR_FIELDS.md` records it as open.
    routing_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #  Group 7 — §10: *"Track SLA, deadline, cost, tokens and concurrency."* Null means the
    #  workspace policy decides; a number here is this Supervisor's own ceiling.
    cost_cap_minor_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cap_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    token_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Null means the workspace default rather than zero, which would mean "immediately".
    retry_backoff_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #  Group 8 — who approves, and who hears about a failure.
    approver_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    approver_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    escalation_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    escalation_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    submitted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "owner_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supervisors_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "org_node_id"],
            ["org_units.tenant_id", "org_units.id"],
            name="fk_supervisors_org_node",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_supervisors_objective",
            ondelete="SET NULL (objective_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submitted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supervisors_submitter",
            ondelete="SET NULL (submitted_by_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supervisors_creator",
            ondelete="SET NULL (created_by_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approver_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supervisors_approver",
            ondelete="SET NULL (approver_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "escalation_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supervisors_escalation",
            ondelete="SET NULL (escalation_membership_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_supervisors_tenant_id"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_supervisors_name_not_blank"),
        Index("ix_supervisors_tenant_status", "tenant_id", "status"),
        Index("ix_supervisors_tenant_owner", "tenant_id", "owner_membership_id"),
    )

    @property
    def is_editable(self) -> bool:
        return self.status in (SupervisorStatus.DRAFT, SupervisorStatus.NEEDS_REVIEW)


class SupervisorSupervised(Base, PrimaryKey, TenantOwned):
    """Scope 1 — whose Agents are watched.

    `agent_id` null means every Agent that person owns, now and later. Set means this one only.
    `agent_version_id` pins what was approved rather than whatever the draft became, which is
    §10 group 2's *"Supervised members and Agent versions"*.

    A trigger refuses a row whose membership is not the owner's on a **personal** Supervisor —
    §10's *"supervises that user's permitted Job Agents"*, held in the database because it is what
    the word "personal" means.
    """

    __tablename__ = "supervisor_supervised"

    supervisor_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_supervised_supervisor",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supervised_membership",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_supervised_agent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_version_id"],
            ["agent_versions.tenant_id", "agent_versions.id"],
            name="fk_supervised_agent_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "supervisor_id", "membership_id", "agent_id", name="uq_supervised_pair"
        ),
        CheckConstraint("position >= 1", name="ck_supervised_position_positive"),
    )


class SupervisorHandler(Base, PrimaryKey, TenantOwned):
    """Scope 2 — who may control this Supervisor, and how far.

    `role` is a **ceiling for this Supervisor**, never a grant. A handler cannot do something the
    workspace has not already permitted them; the role only narrows it further. 6.2 is where that
    becomes enforcement.

    Explicit rows only. The plan's decision table settles it for department Supervisors:
    *"Explicit selected people; no automatic department-wide control."* Nothing in this module
    reads a department and produces a handler.
    """

    __tablename__ = "supervisor_handlers"

    supervisor_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Who added them. A handler nobody can be shown to have granted is a handler nobody can be
    #: asked about.
    granted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_handlers_supervisor",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_handlers_membership",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "granted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_handlers_grantor",
            ondelete="SET NULL (granted_by_membership_id)",
        ),
        UniqueConstraint(
            "tenant_id", "supervisor_id", "membership_id", name="uq_handlers_membership"
        ),
    )


class OnFailure(enum.StrEnum):
    """What a quality gate does when it does not hold.

    §10 group 6 pairs quality with evidence, and a gate with no stated consequence is an
    observation rather than a gate.
    """

    BLOCK = "block"
    ESCALATE = "escalate"
    FLAG_AND_CONTINUE = "flag_and_continue"


class SupervisorSchedule(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """When a Supervisor runs — §10 group 4.

    **The same columns as `job_schedules`, deliberately.** `jobs/recurrence.py` already solves
    timezones, DST gaps and ambiguity, missed runs and overlap, and it is pure — no database
    anywhere in it. Carrying the same column names means the same code reads these rows. A second
    implementation of DST handling is a second set of bugs, and they appear at the clock change
    when nobody is looking.

    `auto_run` is off until somebody turns it on. A schedule that starts firing because a form was
    saved is a schedule nobody agreed to.
    """

    __tablename__ = "supervisor_schedules"

    supervisor_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    auto_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    at_time: Mapped[time] = mapped_column(Time, nullable=False)
    weekdays: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    monthday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dst_policy: Mapped[str] = mapped_column(String(10), nullable=False, server_default="shift")
    ambiguous_policy: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="first"
    )
    skip_dates: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    weekdays_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    missed_run_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="skip"
    )
    #: The plan's decision table recommends *"Queue one run"*, which is `QUEUE`.
    overlap_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="queue"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_schedules_supervisor",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "supervisor_id", name="uq_sup_schedules_supervisor"),
    )


class SupervisorDependency(Base, PrimaryKey, TenantOwned):
    """One supervised row waiting on another — §10's *"start eligible dependency-ready work"*.

    Both sides point at `supervisor_supervised`, so a dependency can only ever be between two
    things this Supervisor actually watches. A cycle is refused by a trigger: a set that each
    waits for the next can never start, and the order that would schedule them does not terminate.
    """

    __tablename__ = "supervisor_dependencies"

    supervisor_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    supervised_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("supervisor_supervised.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("supervisor_supervised.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_deps_supervisor",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "supervised_id", "depends_on_id", name="uq_sup_deps_pair"
        ),
        CheckConstraint("supervised_id <> depends_on_id", name="ck_sup_deps_not_itself"),
    )


class SupervisorQualityGate(Base, PrimaryKey, TenantOwned, Timestamps):
    """§10 group 6 — *"detect quality/policy problems"*, and what proves one did not happen.

    `condition` and `evidence` are free text: §10 names no expression language, and inventing one
    would be inventing a product rather than implementing a plan.
    """

    __tablename__ = "supervisor_quality_gates"

    supervisor_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    on_failure: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="escalate"
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_gates_supervisor",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "supervisor_id", "name", name="uq_sup_gates_name"),
        CheckConstraint("position >= 1", name="ck_sup_gates_position"),
    )


class SupervisorEscalation(Base, PrimaryKey, TenantOwned, Timestamps):
    """§10 group 8 — *"escalate to configured people"*.

    `situation` is free text because §10 prints no list the way the Agent's Form 4 section B does.
    A closed set here would be situations somebody invented.
    """

    __tablename__ = "supervisor_escalations"

    supervisor_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    situation: Mapped[str] = mapped_column(String(200), nullable=False)
    required_action: Mapped[str] = mapped_column(Text, nullable=False)
    escalate_to_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    escalate_to_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Null means immediately.
    after_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_esc_supervisor",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "escalate_to_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_sup_esc_escalate_to",
            ondelete="SET NULL (escalate_to_membership_id)",
        ),
        UniqueConstraint(
            "tenant_id", "supervisor_id", "situation", name="uq_sup_esc_situation"
        ),
        CheckConstraint("position >= 1", name="ck_sup_esc_position"),
    )


class SupervisorNotification(Base, PrimaryKey, TenantOwned, Timestamps):
    """§10 group 9 — *"notify handlers and stakeholders"*.

    `to_handlers` defaults on because handlers are who §10 says to notify. A named recipient is
    the stakeholder half, and the schema refuses a row that reaches neither.
    """

    __tablename__ = "supervisor_notifications"

    supervisor_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(60), nullable=True)
    to_handlers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    recipient_membership_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    recipient_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_notify_supervisor",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_sup_notify_recipient",
            ondelete="SET NULL (recipient_membership_id)",
        ),
        UniqueConstraint("tenant_id", "supervisor_id", "event", name="uq_sup_notify_event"),
        CheckConstraint("position >= 1", name="ck_sup_notify_position"),
    )
