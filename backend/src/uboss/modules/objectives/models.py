"""The Objective, its current-process steps, and its published versions.

`docs/architecture/OBJECTIVE_FIELDS.md` records why the field set comes from two places: the
approved workbook's Form 2 is the floor of what must be captured, and PLAN §7 adds what governing
it needs. Neither is dropped.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class ObjectiveStatus(enum.StrEnum):
    """PLAN §7's views and statuses, in the order work moves through them."""

    DRAFT = "draft"
    ANALYZING = "analyzing"
    NEEDS_REVIEW = "needs_review"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    ACTIVE = "active"
    PAUSED = "paused"
    #: The only terminal state. A published objective is archived, never deleted — every run
    #: recorded against it needs it to still exist.
    ARCHIVED = "archived"


class Priority(enum.StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Visibility(enum.StrEnum):
    OWNER = "owner"
    DEPARTMENT = "department"
    COMPANY = "company"


class AiAssistance(enum.StrEnum):
    """§7 group 8 — how much the product may do without being asked."""

    NONE = "none"
    #: The default, and what §7 describes: Claude proposes, a person decides.
    PROPOSE_ONLY = "propose_only"
    PROPOSE_AND_DRAFT = "propose_and_draft"


class Objective(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    __tablename__ = "objectives"

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")

    #  ── the workbook's heading block ────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    #: Free text with the workbook's list offered, not a foreign key. A team writes "Sales"
    #: before anybody has built the hierarchy, and refusing the objective until they do would
    #: stop exactly the work this product exists to capture.
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    workload_count: Mapped[str | None] = mapped_column(String(60), nullable=True)
    workload_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    #  ── PLAN §7's additions ─────────────────────────────────────────────────────────────
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")
    baseline: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_measures: Mapped[str | None] = mapped_column(Text, nullable=True)
    included_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    excluded_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    stakeholders: Mapped[str | None] = mapped_column(Text, nullable=True)
    geography: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(200), nullable=True)
    budget_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    dependencies: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Separate from the owner on purpose. PLAN §16 forbids self-approval, and one column could
    #: not express the distinction.
    approver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="department"
    )
    handles_sensitive_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sensitive_data_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_assistance: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="propose_only"
    )
    human_checkpoints: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: The two tables point at each other — an objective names its published version, and a
    #: version names its objective. `use_alter` tells SQLAlchemy to add this key after both
    #: tables exist rather than trying to order them, which it cannot do and warns about.
    #: The migration already does exactly that.
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "objective_versions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_objectives_published_version",
        ),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "owner_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_objectives_tenant_owner",
            ondelete="SET NULL (owner_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approver_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_objectives_tenant_approver",
            ondelete="SET NULL (approver_membership_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_objectives_tenant_id"),
        CheckConstraint(
            "status NOT IN ('published', 'active', 'paused') OR published_version_id IS NOT NULL",
            name="ck_objectives_published_has_version",
        ),
        Index("ix_objectives_tenant_status", "tenant_id", "status"),
    )

    @property
    def is_editable(self) -> bool:
        """A draft is edited; a published version is not.

        `analyzing` is excluded as well: a proposal is being worked out against these fields, and
        changing them underneath it would produce a plan for an objective that no longer exists.
        """
        return self.status in (
            ObjectiveStatus.DRAFT,
            ObjectiveStatus.NEEDS_REVIEW,
            ObjectiveStatus.READY_TO_PUBLISH,
        )


class ObjectiveCurrentStep(Base, PrimaryKey, TenantOwned, Timestamps):
    """One row of the workbook's step table — the work as it happens **today**.

    Deliberately not the execution graph Claude proposes. Comparing the two is the point of the
    product (PLAN §7: *"compare AI/human changes"*), and one table could not hold both.

    Every column is free text. Seven of them have the workbook's suggested list, and every one of
    those lists ends in `Other` — so refusing a value outside the list would refuse something the
    approved workbook explicitly allows.
    """

    __tablename__ = "objective_current_steps"

    objective_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    #: 1-based, as the workbook numbers them.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    who_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    who_role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    when_trigger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    when_frequency: Mapped[str | None] = mapped_column(String(200), nullable=True)
    what_exact_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_received_from: Mapped[str | None] = mapped_column(String(200), nullable=True)
    where_done: Mapped[str | None] = mapped_column(String(200), nullable=True)
    output_produced: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_sent_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    time_taken: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_problem: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approval: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_current_steps_tenant_objective",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "objective_id", "position", name="uq_current_steps_position"
        ),
        Index("ix_current_steps_objective", "tenant_id", "objective_id", "position"),
    )


class ObjectiveVersion(Base, PrimaryKey, TenantOwned):
    """What was approved, frozen.

    PLAN §30: *"Published versions are immutable."* The trigger refuses UPDATE and DELETE and the
    application role does not hold the privilege — two independent reasons a published version
    cannot change, which is the standard this schema holds everywhere else too.
    """

    __tablename__ = "objective_versions"

    objective_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    #: Assigned by trigger, gapless per objective. A gap would be indistinguishable from a
    #: version somebody removed — the one thing an immutable table exists to rule out.
    version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=FetchedValue()
    )

    #: The whole objective at publish, steps included. PLAN §30 allows JSON for snapshots
    #: specifically: the searchable fields are normalised on `objectives`, and nothing queries
    #: this.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Denormalised so a version list reads without opening the snapshot.
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    published_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    approved_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_versions_tenant_objective",
            #  RESTRICT: a published version is evidence, and deleting the objective must not
            #  take the record of what was approved with it.
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "objective_id", "version_no", name="uq_versions_objective_no"
        ),
        Index("ix_versions_objective", "tenant_id", "objective_id", "version_no"),
    )
