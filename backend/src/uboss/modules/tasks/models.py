"""Tasks, as SQLAlchemy sees them.

Mirrors migration 0032. The reasoning for each column is there; this is the mapping.

Enum columns are `String` and typed `str`, following the rest of the schema — the enums below are
the vocabulary, not the storage. Declaring a column as its enum type-checks and then hands back a
plain string at runtime, which is the worst of both.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from uboss.db.base import Base
from uboss.db.mixins import PrimaryKey, TenantOwned


class TaskKind(enum.StrEnum):
    """What a person is being asked for — §11's first three tabs."""

    WORK = "work"
    INPUT = "input"
    APPROVAL = "approval"


class TaskState(enum.StrEnum):
    """Where a task is.

    `DELEGATED` is an end state of its own rather than `DONE`: the task was passed on, not
    performed, and a report that counted delegations as completions would overstate what got done.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DECLINED = "declined"
    DELEGATED = "delegated"
    CANCELLED = "cancelled"

    @classmethod
    def open(cls) -> frozenset[str]:
        """The states that still need somebody. This is what the sidebar counts."""
        return frozenset({cls.PENDING, cls.IN_PROGRESS})

    @classmethod
    def closed(cls) -> frozenset[str]:
        return frozenset({cls.DONE, cls.DECLINED, cls.DELEGATED, cls.CANCELLED})


class TaskOutcome(enum.StrEnum):
    """What somebody actually did.

    `APPROVED` and `REJECTED` belong to an approval; `COMPLETED` and `PROVIDED` to the other two
    kinds. Separate from `TaskState` because "it is finished" and "what was decided" are different
    questions, and a single column answering both would collapse a rejection into a completion.
    """

    COMPLETED = "completed"
    PROVIDED = "provided"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"

    @classmethod
    def needs_reason(cls) -> frozenset[str]:
        """Outcomes that must say why. Enforced by the database as well as here."""
        return frozenset({cls.REJECTED, cls.CHANGES_REQUESTED})


class Task(Base, PrimaryKey, TenantOwned):
    """One thing a run is waiting on a person for."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tasks_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_tasks_run",
            ondelete="CASCADE",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_step_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    #: One of `TaskKind`.
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Null when §8's WHO rules resolved to nobody. Visible and obviously unassigned, which is a
    #: state somebody can fix — unlike a task quietly given to the wrong person.
    assignee_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: Set when a person assigned it; null when a rule did.
    assigned_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: Which WHO rule decided, in §8's own vocabulary, or `unresolved`. Recorded so "why me?" has
    #: an answer that does not require reading the version.
    assigned_via: Mapped[str] = mapped_column(String(30), nullable=False, default="unresolved")

    #: One of `TaskState`.
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskState.PENDING)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: One of `TaskOutcome`, or null while it is open.
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskFollower(Base, PrimaryKey, TenantOwned):
    """Somebody watching a task they were not given — §11's *Following* tab."""

    __tablename__ = "task_followers"
    __table_args__ = (
        UniqueConstraint("task_id", "membership_id", name="uq_task_followers_once"),
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_task_followers_task",
            ondelete="CASCADE",
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskComment(Base, PrimaryKey, TenantOwned):
    """Append-only, because a decision may have been taken on the strength of one."""

    __tablename__ = "task_comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_task_comments_task",
            ondelete="CASCADE",
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskEvidence(Base, PrimaryKey, TenantOwned):
    """A file attached as proof — a join to `files`, never a second copy of one."""

    __tablename__ = "task_evidence"
    __table_args__ = (
        UniqueConstraint("task_id", "file_id", name="uq_task_evidence_once"),
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_task_evidence_task",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["files.tenant_id", "files.id"],
            name="fk_task_evidence_file",
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    attached_by_membership_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
