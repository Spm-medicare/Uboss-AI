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
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
