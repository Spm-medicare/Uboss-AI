"""Runs, as SQLAlchemy sees them.

Mirrors migration 0029 and nothing more. The comments there explain *why* each column exists; this
file is the mapping, and a second copy of the reasoning would be a second copy to keep true.

**No relationships are declared.** A `Run.steps` collection would be convenient and would make
every query that touched a run capable of loading its steps by accident — which on a list of two
hundred runs is two hundred extra queries nobody asked for. Steps are read when a caller asks for
steps, and the service says so at the call site.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from uboss.db.base import Base
from uboss.db.mixins import PrimaryKey, TenantOwned


class RunState(enum.StrEnum):
    """Where a run is.

    `PENDING` is the gap between the row being written and the workflow being started — see
    migration 0029. `WAITING` is a run whose current step needs a person, which is a different
    thing from a run that is doing something and a different thing again from one that failed.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def finished(cls) -> frozenset[str]:
        return frozenset({cls.SUCCEEDED, cls.FAILED, cls.CANCELLED})


class StepState(enum.StrEnum):
    """Where one step is.

    `SKIPPED` is a step a condition ruled out. It is deliberately not `succeeded`: a report that
    counted skipped steps as done would say a run did work it did not do.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @classmethod
    def finished(cls) -> frozenset[str]:
        """The states that mean "not still working on it".

        `SKIPPED` is in here and is deliberately not `SUCCEEDED`: a report that counted skipped
        steps as done would say a run did work it did not do.
        """
        return frozenset({cls.SUCCEEDED, cls.FAILED, cls.SKIPPED, cls.CANCELLED})


class RunTrigger(enum.StrEnum):
    """Why this run exists.

    Recorded because it is the first question asked about an unexpected run, and "a person pressed
    Run" and "a schedule fired" are answers that lead to different places.
    """

    MANUAL = "manual"
    SCHEDULE = "schedule"
    SUPERVISOR = "supervisor"
    API = "api"


class Run(Base, PrimaryKey, TenantOwned):
    """One execution of one **pinned version**.

    `job_version_id`, never `job_id` alone: a run that read the draft would change under itself the
    moment somebody edited the Job, which is the thing immutable versions exist to prevent.
    """

    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_runs_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "job_version_id"],
            ["job_versions.tenant_id", "job_versions.id"],
            name="fk_runs_job_version",
        ),
    )

    job_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    #: Temporal's id for this run. Written before the workflow starts, so a crash in between
    #: leaves a `pending` row a reconciler can resolve rather than a workflow nothing points at.
    workflow_id: Mapped[str] = mapped_column(String(200), nullable=False)

    #: One of `RunState`. Typed `str` because the column is `String` and SQLAlchemy returns what
    #: is stored — declaring it as the enum would type-check and then hand back a `str` at
    #: runtime, which is the worst of both. The enum is the vocabulary; `String` is the storage.
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=RunState.PENDING)
    #: One of `RunTrigger`.
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)

    #: Null for a scheduled run. Nobody started it, and naming whoever wrote the schedule would
    #: record an approval they did not give for this particular execution.
    started_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RunStep(Base, PrimaryKey, TenantOwned):
    """One step of a run — the unit a person is assigned and a retry replays."""

    __tablename__ = "run_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_run_steps_run",
            ondelete="CASCADE",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    #: 1-based, in the version's own order.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: §9's work mode, copied from the version so a run never has to re-read a snapshot to know
    #: whether this step is somebody's job or an agent's.
    mode: Mapped[str] = mapped_column(String(20), nullable=False)

    #: One of `StepState`.
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=StepState.PENDING)
    #: Counts activity attempts, so a retry is visible rather than silent.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RunEvent(Base, PrimaryKey, TenantOwned):
    """What happened, in order. Append-only by trigger and by withheld privilege.

    This is what a run's evidence is made of. `kind` is a dotted string rather than an enum on
    purpose: the runtime will learn new events every gate, and a migration to add a value to a
    check constraint is a migration nobody will write at the moment they need the event.
    """

    __tablename__ = "run_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_run_events_run",
            ondelete="CASCADE",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    #: Null for an event about the run itself rather than one of its steps.
    run_step_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Null for the runtime's own events, which is most of them.
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
