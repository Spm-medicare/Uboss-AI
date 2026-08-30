"""A Job — the approved workbook's Form 3, and PLAN §8's ten groups.

*"Job Builder defines reusable work; it is not a runtime Agent."* This describes a method: who
does what, in what order, with which inputs, and what happens when something is missing. What
executes it is Gate 5's Agent and Gate 7's runtime.

The sheet and the plan agree on the sixteen step fields, so unlike the Objective there was no
conflict to resolve — both are implemented whole.
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


class JobStatus(enum.StrEnum):
    """The same lifecycle as an Objective.

    One vocabulary across the Builders, so somebody who has published one knows what the words
    mean on the next. `analyzing` is absent: a Job is written, not proposed.
    """

    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class WhoType(enum.StrEnum):
    """PLAN §8's six WHO types, exactly.

    A rule rather than a person, because a `who_person` column works until the first time
    somebody leaves — and then every job they touched is assigned to nobody.
    """

    USER = "user"
    TEAM = "team"
    DEPARTMENT = "department"
    ROLE = "role"
    HIERARCHY_POSITION = "hierarchy_position"
    HIERARCHY_SUBTREE = "hierarchy_subtree"
    DYNAMIC_GROUP = "dynamic_group"


class InputRequirement(enum.StrEnum):
    """The workbook's "Input Status" list."""

    MANDATORY = "Mandatory"
    OPTIONAL = "Optional"
    CONDITIONAL = "Conditional"


class AiAccess(enum.StrEnum):
    """What a model may do with an input.

    `NONE` is the default because the safe answer should be the one that has to be chosen, not
    the one that happens when nobody thinks about it.
    """

    NONE = "none"
    READ = "read"
    READ_WRITE = "read_write"


class StepMode(enum.StrEnum):
    HUMAN = "human"
    AI_AGENT = "ai_agent"
    HYBRID = "hybrid"


class Job(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    __tablename__ = "jobs"

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")

    #  ── Form 3's heading block ──────────────────────────────────────────────────────────
    #: Linked from Form 2 rather than retyped. Nullable because a job can be described before
    #: the objective it serves exists — teams do not work in the order a form imagines.
    objective_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    #: Which step of the objective's plan this job carries out — §8 group 1.
    objective_step_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: "Job ID / Name *"
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: "Current Person *" and "Role *" — who does it today, in their own words.
    current_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(200), nullable=True)
    high_level_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: How anybody knows it finished — §8 group 8.
    completion_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    normal_completion_time: Mapped[str | None] = mapped_column(String(60), nullable=True)
    time_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)

    #  ── §8's groups the sheet does not carry ────────────────────────────────────────────
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_checks: Mapped[str | None] = mapped_column(Text, nullable=True)
    sla_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: The job's policy when the whole thing fails. The step's "If Missing / Wrong" is the
    #: narrow case; this is the wide one.
    retry_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    escalation_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="department"
    )

    approver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    submitted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "job_versions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_jobs_published_version",
        ),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_jobs_tenant_objective",
            ondelete="SET NULL (objective_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_jobs_tenant_owner",
            ondelete="SET NULL (owner_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approver_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_jobs_tenant_approver",
            ondelete="SET NULL (approver_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submitted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_jobs_tenant_submitter",
            ondelete="SET NULL (submitted_by_membership_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_jobs_tenant_id"),
        CheckConstraint(
            "status NOT IN ('published', 'active', 'paused') OR published_version_id IS NOT NULL",
            name="ck_jobs_published_has_version",
        ),
        CheckConstraint(
            "status <> 'ready_to_publish' OR submitted_by_membership_id IS NOT NULL",
            name="ck_jobs_submitted_has_submitter",
        ),
        Index("ix_jobs_tenant_status", "tenant_id", "status"),
    )

    @property
    def is_editable(self) -> bool:
        return self.status in (
            JobStatus.DRAFT,
            JobStatus.NEEDS_REVIEW,
            JobStatus.READY_TO_PUBLISH,
        )


class JobStep(Base, PrimaryKey, TenantOwned, Timestamps):
    """One row of Form 3's step table — all sixteen columns.

    The column that separates this from the Objective's step table is `how_exact_method`: the
    objective records *what* happens, the job records *how*. And `if_missing_or_wrong` is the one
    that makes a job runnable rather than merely described — it says what to do when the input is
    not there, which is the case every written procedure omits.
    """

    __tablename__ = "job_steps"

    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    who_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    who_role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    when_trigger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    when_frequency: Mapped[str | None] = mapped_column(String(200), nullable=True)
    what_exact_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_exact: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_found_where: Mapped[str | None] = mapped_column(String(200), nullable=True)
    how_exact_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    where_performed: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Free text on purpose — a spreadsheet formula, a tolerance, a policy clause. Structuring it
    #: would refuse most of what people actually write.
    rule_formula_check: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_destination: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approval: Mapped[str | None] = mapped_column(String(200), nullable=True)
    if_missing_or_wrong: Mapped[str | None] = mapped_column(String(300), nullable=True)
    time_taken: Mapped[str | None] = mapped_column(String(100), nullable=True)

    #: §8 group 6. Not on the sheet — the sheet describes how a person does it today — so it
    #: defaults to `human` and somebody decides otherwise deliberately.
    mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="human")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_steps_tenant_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_job_steps_tenant_id"),
        UniqueConstraint("tenant_id", "job_id", "position", name="uq_job_steps_position"),
        Index("ix_job_steps_job", "tenant_id", "job_id", "position"),
    )


class JobStepDependency(Base, PrimaryKey, TenantOwned):
    """`step_id` waits for `depends_on_step_id`. Cycles are refused by trigger."""

    __tablename__ = "job_step_dependencies"

    step_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    depends_on_step_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "step_id"],
            ["job_steps.tenant_id", "job_steps.id"],
            name="fk_job_step_deps_tenant_step",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "depends_on_step_id"],
            ["job_steps.tenant_id", "job_steps.id"],
            name="fk_job_step_deps_tenant_target",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "step_id", "depends_on_step_id", name="uq_job_step_deps_pair"
        ),
        CheckConstraint("step_id <> depends_on_step_id", name="ck_job_step_deps_not_self"),
        Index("ix_job_step_deps_step", "tenant_id", "step_id"),
    )


class JobAssignmentRule(Base, PrimaryKey, TenantOwned, Timestamps):
    """One of §8's *"multiple WHO assignment rules"*."""

    __tablename__ = "job_assignment_rules"

    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    who_type: Mapped[str] = mapped_column(String(30), nullable=False)

    #: What it points at, in the terms of its own type. Null for `dynamic_group`, which names a
    #: condition rather than a row.
    target_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    #: A department name or group description, where the target is not a row here.
    target_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: When this rule applies. Multiple rules are only useful if each can say what it covers.
    condition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Whether everybody matched must act, or any one of them is enough.
    all_must_act: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_rules_tenant_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "job_id", "position", name="uq_job_rules_position"),
        CheckConstraint(
            "target_id IS NOT NULL OR length(btrim(coalesce(target_label, ''))) > 0",
            name="ck_job_rules_has_a_target",
        ),
        Index("ix_job_rules_job", "tenant_id", "job_id", "position"),
    )


class JobInput(Base, PrimaryKey, TenantOwned, Timestamps):
    """A typed input — §8: *"name, schema/type, source, required status, validation,
    classification, retention and AI-access permission."*

    That last field is why inputs are a table rather than a string: an input a model may not see
    has to be able to say so, and Gate 5's Agent reads it before it reads anything else.
    """

    __tablename__ = "job_inputs"

    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The workbook's "Input Type" list.
    input_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    requirement: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="Optional"
    )
    #: Required when `requirement` is `Conditional` — a conditional input with no condition is an
    #: optional one nobody can reason about.
    condition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="internal"
    )
    retention_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ai_access: Mapped[str] = mapped_column(String(20), nullable=False, server_default="none")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_inputs_tenant_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "job_id", "position", name="uq_job_inputs_position"),
        #: Two inputs with one name is two things a step could mean, and the step would take
        #: whichever the query returned first.
        UniqueConstraint("tenant_id", "job_id", "name", name="uq_job_inputs_name"),
        CheckConstraint(
            "requirement <> 'Conditional' OR length(btrim(coalesce(condition_note, ''))) > 0",
            name="ck_job_inputs_conditional_has_condition",
        ),
        #: Personal data a model may write back needs a decision nobody has made yet, so the
        #: schema refuses it rather than letting it arrive by default.
        CheckConstraint(
            "NOT (classification = 'personal_data' AND ai_access = 'read_write')",
            name="ck_job_inputs_no_ai_write_on_personal_data",
        ),
        Index("ix_job_inputs_job", "tenant_id", "job_id", "position"),
    )


class JobVersion(Base, PrimaryKey, TenantOwned):
    """What was approved, frozen. Immutable by trigger and by privilege, like every version here."""

    __tablename__ = "job_versions"

    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=FetchedValue()
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)

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
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_versions_tenant_job",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "job_id", "version_no", name="uq_job_versions_no"),
        Index("ix_job_versions_job", "tenant_id", "job_id", "version_no"),
    )
