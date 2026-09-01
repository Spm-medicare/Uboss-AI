"""Approvals, as SQLAlchemy sees them.

Mirrors migration 0033. The reasoning for each column is there; this is the mapping.

Enum columns are `String` and typed `str`, following the rest of the schema — the enum below is
the vocabulary, not the storage.
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


class ApprovalState(enum.StrEnum):
    """Where an approval is.

    `WITHDRAWN` is not a refusal. Nobody said no — the question stopped being asked, because the
    run was cancelled or the task was handed back and replaced. Collapsing it into `REJECTED`
    would put a refusal nobody made into somebody's record.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    WITHDRAWN = "withdrawn"

    @classmethod
    def decided(cls) -> frozenset[str]:
        """The states in which somebody made a decision."""
        return frozenset({cls.APPROVED, cls.REJECTED, cls.CHANGES_REQUESTED})

    @classmethod
    def refusals(cls) -> frozenset[str]:
        """Decisions that must say why. Enforced by the database as well as here."""
        return frozenset({cls.REJECTED, cls.CHANGES_REQUESTED})

    @classmethod
    def closed(cls) -> frozenset[str]:
        return cls.decided() | {cls.WITHDRAWN}


class Approval(Base, PrimaryKey, TenantOwned):
    """One decision a run is waiting on, and everything an audit asks about it."""

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_approvals_one_per_task"),
        UniqueConstraint("tenant_id", "id", name="uq_approvals_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_approvals_task",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_approvals_run",
            ondelete="CASCADE",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_step_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    #: Who set the work going, and therefore who is asking. Never null — an approval nobody
    #: requested has no separation of duty to enforce.
    requested_by_membership_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    #: Who was entitled to decide, resolved when the approval was raised. Null when §8's rules
    #: matched nobody.
    approver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: §9's Approval column, frozen with the version — the question, in the author's words.
    question: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: One of `ApprovalState`.
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ApprovalState.PENDING
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Free text, because the Job's `escalation_to` is free text. Copied rather than resolved:
    #: pretending a label is a route would be a route that goes nowhere.
    escalation_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    escalated_to_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
