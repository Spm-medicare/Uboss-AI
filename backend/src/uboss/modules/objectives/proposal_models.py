"""The analysis run, its real timeline, and the execution graph it proposes.

PLAN §7: *"Claude proposes an execution graph with Human, AI Agent, Hybrid, Approval and Output
blocks."* The proposal is kept exactly as the model returned it, and the steps created from it are
ordinary editable rows — which is the only way §7's *"compare AI/human changes"* can be answered
after somebody has edited half of them.
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


class ProposalStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    #: A later run replaced it. Kept, because the steps it produced may still be in the graph.
    SUPERSEDED = "superseded"


class Stage(enum.StrEnum):
    """The six stages, from `docs/delivery/WORK_BREAKDOWN.md`. Not invented here."""

    VALIDATE = "validate"
    CONTEXT = "context"
    WORKSTREAMS = "workstreams"
    PROPOSE = "propose"
    POLICY = "policy"
    REVIEW = "review"


#: In the order they run. The screen draws the timeline from this, so a stage that has not
#: started yet can be shown as not started rather than as missing.
STAGE_ORDER: tuple[Stage, ...] = (
    Stage.VALIDATE,
    Stage.CONTEXT,
    Stage.WORKSTREAMS,
    Stage.PROPOSE,
    Stage.POLICY,
    Stage.REVIEW,
)


class StageState(enum.StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepKind(enum.StrEnum):
    """PLAN §7's block kinds, exactly.

    A closed list, because the runtime routes work by it: a `HUMAN` block becomes somebody's
    to-do and an `AI_AGENT` block becomes a run. A kind the runtime does not know is a step that
    would silently never execute.
    """

    HUMAN = "human"
    AI_AGENT = "ai_agent"
    HYBRID = "hybrid"
    APPROVAL = "approval"
    OUTPUT = "output"


class StepSource(enum.StrEnum):
    AI = "ai"
    HUMAN = "human"


class ObjectiveProposal(Base, PrimaryKey, TenantOwned):
    """One analysis run."""

    __tablename__ = "objective_proposals"

    objective_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")
    stage: Mapped[str | None] = mapped_column(String(30), nullable=True)

    #: What the objective looked like when the run started. Kept because the person keeps
    #: editing, and "the plan was proposed for this" has to stay answerable.
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: The model's answer as it validated. Never edited.
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_proposals_tenant_objective",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_proposals_tenant_id"),
        CheckConstraint(
            "(status <> 'failed') OR (failure_detail IS NOT NULL)",
            name="ck_proposals_failure_has_reason",
        ),
        Index("ix_proposals_objective", "tenant_id", "objective_id"),
    )


class AnalysisEvent(Base, PrimaryKey, TenantOwned):
    """One stage starting or finishing, written as it actually happens.

    Append-only, like the audit trail. PLAN §6 asks for a *real* analysis timeline, and a stage
    that could be rewritten afterwards is a stage nobody can rely on — at which point drawing it
    from a timer would be no worse, which is exactly the outcome to avoid.
    """

    __tablename__ = "objective_analysis_events"

    proposal_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    #: One line a person reads on screen. Not a log line.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["objective_proposals.tenant_id", "objective_proposals.id"],
            name="fk_analysis_events_tenant_proposal",
            ondelete="CASCADE",
        ),
        Index("ix_analysis_events_proposal", "tenant_id", "proposal_id", "at"),
    )


class ObjectiveStep(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """One block of the proposed execution graph — and, after editing, of the agreed one."""

    __tablename__ = "objective_steps"

    objective_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    #: The run that first proposed it, or null once a person adds one by hand.
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: A role rather than a person: an objective is published once and run many times, and the
    #: person in a seat changes.
    responsible_role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Which current-process step this replaces. Null when the proposal introduces work that did
    #: not exist — a check nobody was doing, for instance.
    replaces_current_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Why the model put it there, in its own words. Shown beside the step, so a reviewer sees
    #: the reasoning and not only the conclusion.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ai")
    #: True once a person has changed an AI-proposed step. `source = 'ai' AND edited` is exactly
    #: "the model proposed this and a human corrected it" — §7's comparison, as a query.
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_objective_steps_tenant_objective",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["objective_proposals.tenant_id", "objective_proposals.id"],
            name="fk_objective_steps_tenant_proposal",
            ondelete="SET NULL (proposal_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_objective_steps_tenant_id"),
        Index("ix_objective_steps_objective", "tenant_id", "objective_id", "position"),
    )


class StepDependency(Base, PrimaryKey, TenantOwned):
    """`step_id` waits for `depends_on_step_id`.

    A cycle is refused by trigger. A plan that waits for itself can never start, and the
    topological sort that orders the run would not terminate.
    """

    __tablename__ = "objective_step_dependencies"

    step_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    depends_on_step_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "step_id"],
            ["objective_steps.tenant_id", "objective_steps.id"],
            name="fk_step_deps_tenant_step",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "depends_on_step_id"],
            ["objective_steps.tenant_id", "objective_steps.id"],
            name="fk_step_deps_tenant_target",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "step_id", "depends_on_step_id", name="uq_step_deps_pair"
        ),
        CheckConstraint("step_id <> depends_on_step_id", name="ck_step_deps_not_self"),
        Index("ix_step_deps_step", "tenant_id", "step_id"),
    )
