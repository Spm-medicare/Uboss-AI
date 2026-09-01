"""Retention, breach cases and the processor register — §5, §6 and §7's tables.

Kept apart from `models.py` because they arrived with their own migration and their own services,
and one 900-line models file is one nobody reads before adding to it.

Three rules run through all three families, and each is held by migration 0045 rather than by a
service:

* A retention run is approved by somebody who did not prepare it. A disposal proposed and approved
  by one person is a disposal nobody reviewed.
* A breach notification names the person who decided it should be sent. §6: an Agent *"may draft; it
  cannot decide legal notification or send without authorised approval."*
* A processor does not become active without a review and a contract version. The consequence of
  skipping that is personal data leaving the country under no agreement.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class Disposal(enum.StrEnum):
    """§5's *"disposal method"*.

    `REVIEW` is one of them on purpose: some categories end in somebody looking at the row rather
    than in an automatic outcome, and a policy that could not say so would be a policy people work
    around.
    """

    DELETE = "delete"
    ANONYMISE = "anonymise"
    ARCHIVE = "archive"
    REVIEW = "review"


class RunState(enum.StrEnum):
    """A retention run's life. §5: *"Execution requires preview and approval where configured."*

    A preview is a plan — candidates counted, nothing touched. Only an approved run becomes
    evidence of a disposal, and `CANCELLED` exists because a plan somebody decided against is a
    fact worth keeping.
    """

    PREVIEW = "preview"
    APPROVED = "approved"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BreachState(enum.StrEnum):
    """§6's progression."""

    OPEN = "open"
    CONTAINED = "contained"
    ASSESSING = "assessing"
    NOTIFYING = "notifying"
    REMEDIATING = "remediating"
    CLOSED = "closed"


class BreachSeverity(enum.StrEnum):
    """How bad it looks. `UNKNOWN` is the honest first answer and is therefore the default."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BreachActionKind(enum.StrEnum):
    """One step of a breach case, for the trail."""

    OPENED = "opened"
    CONTAINED = "contained"
    ASSESSED = "assessed"
    NOTIFICATION_DECIDED = "notification_decided"
    AUTHORITY_NOTIFIED = "authority_notified"
    PRINCIPALS_NOTIFIED = "principals_notified"
    REMEDIATED = "remediated"
    POSTMORTEM = "postmortem"
    CLOSED = "closed"
    NOTE = "note"


class ProcessorState(enum.StrEnum):
    """§7's workflow: *"risk review, contract approval and configured customer-notice … before
    personal data is sent."*"""

    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class ProcessorRole(enum.StrEnum):
    PROCESSOR = "processor"
    SUBPROCESSOR = "subprocessor"
    JOINT_CONTROLLER = "joint_controller"


class RetentionPolicy(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """What to keep, for how long, and what to do when the time is up.

    **`period_days` has no default and is nullable.** §5 scopes a policy by category, purpose,
    jurisdiction and lifecycle state, and every one of those is somebody's decision — a default
    would be this product deciding how long an organisation keeps personal data. Null says *"decided
    case by case"*, which is a real answer for some categories and better than a number nobody
    chose.

    `trigger` is a sentence rather than a column reference: *"when the employment ends"*, *"the last
    day of the financial year the invoice falls in"*. When retention needs to select rows
    automatically it should get a real predicate; prose parsed by a matcher would be the worst of
    both.
    """

    __tablename__ = "retention_policies"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    data_category: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lifecycle_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    processing_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disposal: Mapped[str] = mapped_column(String(20), nullable=False)
    exception_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    backup_behaviour: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    review_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "processing_activity_id"],
            ["processing_activities.tenant_id", "processing_activities.id"],
            name="fk_retention_policies_activity",
            ondelete="SET NULL (processing_activity_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_retention_policies_owner",
            ondelete="SET NULL (owner_membership_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_retention_policies_tenant_id"),
    )


class RetentionRun(Base, PrimaryKey, TenantOwned):
    """One preview, and — if somebody approved it — the disposal it became.

    §5's five counts, each nullable until the run reaches the state that knows it. A preview knows
    its candidates and nothing else, and a `disposed = 0` on a preview would say it deleted nothing
    when it has not been asked to delete anything yet.

    `DELETE` is refused by a trigger and withheld from the application role: this row is the record
    that a deletion happened, and a record of a deletion that can be removed is not one. `UPDATE` is
    allowed, because the row moves through its states — what protects it is the constraints and the
    service, and both are in migration 0045's header.
    """

    __tablename__ = "retention_runs"

    policy_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="preview")
    candidates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excluded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disposed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reconciled: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    prepared_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    prepared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["retention_policies.tenant_id", "retention_policies.id"],
            name="fk_retention_runs_policy",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_retention_runs_tenant_id"),
        Index("ix_retention_runs_policy", "tenant_id", "policy_id", "prepared_at"),
    )


class BreachCase(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """A suspected personal-data breach, and everything §6 asks a case to record.

    **Three times, and they are different.** `detected_at` is when it happened as far as anybody can
    tell, `awareness_at` is when somebody realised, `created_at` is when the case was opened.
    Statutory clocks run from awareness — which is why it is required, and why nothing here computes
    a deadline from it.

    **The notification decision is a person's.** §6: an Agent *"may draft; it cannot decide legal
    notification or send without authorised approval."* So `authority_notification_required` and
    `principal_notification_required` are nullable — *"not yet decided"* is the truthful state for
    the first hours — and the table refuses a recorded notification that names nobody who decided
    it.
    """

    __tablename__ = "breach_cases"

    reference: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown")

    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    awareness_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reported_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    commander_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    affected_systems: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_regions: Mapped[str | None] = mapped_column(String(300), nullable=True)
    data_categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_principals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    containment: Mapped[str | None] = mapped_column(Text, nullable=True)

    authority_notification_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    principal_notification_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notification_decided_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    notification_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    authority_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    principals_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    postmortem: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_breach_cases_reference"),
        UniqueConstraint("tenant_id", "id", name="uq_breach_cases_tenant_id"),
    )

    @property
    def is_open(self) -> bool:
        return self.state != BreachState.CLOSED


class BreachAction(Base, PrimaryKey, TenantOwned):
    """One step somebody took on a breach case. Append-only.

    §6 asks for a decision log, and this is it. The same shape as `request_actions` and
    `run_events`, for the same reason: a trail that can be edited is a trail nobody can rely on
    during the argument about what was known when.
    """

    __tablename__ = "breach_actions"

    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["breach_cases.tenant_id", "breach_cases.id"],
            name="fk_breach_actions_case",
            ondelete="RESTRICT",
        ),
        Index("ix_breach_actions_case", "tenant_id", "case_id", "occurred_at"),
    )


class Processor(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """One provider that processes personal data on this workspace's behalf — §7's register.

    `state` is the workflow, not a label: §7 requires *"risk review, contract approval and
    configured customer-notice/change workflow before personal data is sent"*, and migration 0045
    refuses an `active` processor with no reviewer and no contract version.

    Retiring one requires exit evidence, because §7 asks for export, deletion confirmation and
    credential revocation — and a provider marked retired with nothing recorded is a provider that
    may still hold the data.
    """

    __tablename__ = "processors"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    service: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    processing_role: Mapped[str] = mapped_column(String(30), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="proposed")
    data_categories: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transfer_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    safeguards: Mapped[str | None] = mapped_column(Text, nullable=True)
    deletion_support: Mapped[str | None] = mapped_column(Text, nullable=True)
    security_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_processors_reviewer",
            ondelete="SET NULL (reviewed_by_membership_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_processors_tenant_id"),
    )

    @property
    def is_active(self) -> bool:
        return self.state == ProcessorState.ACTIVE and self.retired_at is None
