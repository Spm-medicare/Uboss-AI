"""Schedule firings, as SQLAlchemy sees them.

Mirrors migration 0034. The reasoning for each column is there; this is the mapping.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from uboss.db.base import Base
from uboss.db.mixins import PrimaryKey, TenantOwned


class FiringState(enum.StrEnum):
    """What happened to one occurrence.

    `SKIPPED` is not a failure and `FAILED` is not a skip. One is a rule the schedule's author
    chose — an overlap policy, a concurrency ceiling, a holiday — and the other is something going
    wrong. A page that showed them the same way would make a correctly-behaving schedule look
    broken every bank holiday.
    """

    #: Claimed, and not yet acted on. A crash here leaves a visible row rather than a silent gap.
    DUE = "due"
    STARTED = "started"
    SKIPPED = "skipped"
    FAILED = "failed"
    #: §8's `requires_approval_per_run`. Due, not started, waiting for a person to release it.
    AWAITING_APPROVAL = "awaiting_approval"

    @classmethod
    def settled(cls) -> frozenset[str]:
        """The states the scheduler will not look at again."""
        return frozenset({cls.STARTED, cls.SKIPPED, cls.FAILED})


class ScheduleFiring(Base, PrimaryKey, TenantOwned):
    """One occurrence of one schedule, and what became of it."""

    __tablename__ = "schedule_firings"
    __table_args__ = (
        UniqueConstraint("schedule_id", "due_at", name="uq_schedule_firings_occurrence"),
        UniqueConstraint("tenant_id", "id", name="uq_schedule_firings_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "schedule_id"],
            ["job_schedules.tenant_id", "job_schedules.id"],
            name="fk_schedule_firings_schedule",
            ondelete="CASCADE",
        ),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    #: The occurrence this row *is*, in UTC. Its identity, together with the schedule.
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: When the scheduler got to it. The gap from `due_at` is the only honest measure of whether
    #: the scheduler is keeping up.
    fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: One of `FiringState`.
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FiringState.DUE
    )
    #: Which rule skipped it, or what failed. Never null on `skipped` or `failed`.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The run this occurrence started. **A plain value, not a foreign key** — see migration
    #: 0036. A firing is evidence that the schedule fired, and evidence outlives the row it
    #: describes: "run 47 was started, and run 47 has since been removed" is the truth, where a
    #: null is the loss of it.
    run_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    #: Recorded per firing, because a schedule can be pinned while the Job's published version
    #: moves underneath it.
    job_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: Made up for after the scheduler had been down — so a run at 09:14 for an 03:00 slot says
    #: why rather than looking like a schedule that fires at the wrong time.
    was_missed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
