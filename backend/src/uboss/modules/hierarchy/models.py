"""The company tree: units, positions, who sits in them and who they report to.

PLAN §5 asks for one editable company tree, and the shape it asks for is the reason this is four
tables rather than one:

* **"Preserve vacant positions."** A position is a seat, not a person. If a person and their job
  were the same row, resigning would delete the job — and the organisation would forget that the
  Regional Manager seat exists and is empty, which is precisely the thing a hierarchy is for.
* **"Effective-dated assignments."** Somebody moves seats on a date. Both facts — who was in it
  and who is in it — have to be true at once, so an assignment carries a range rather than
  overwriting the previous holder.
* **"Primary manager plus optional dotted-line reporting."** Reporting is an edge between
  positions, and there can be more than one, so it cannot be a `manager_id` column.
* **"Detect cycles, orphan managers and duplicate identifiers."** Cycles are refused in the
  database by trigger, not in the service, because an import applies rows in bulk and a check the
  application performs is a check a bulk path can skip.

Reporting edges are between **positions**, not people. A person leaving does not orphan their
whole reporting line — the seat still reports where it reported, and whoever fills it inherits
that. Modelling it person-to-person means every resignation silently detaches a subtree.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class UnitType(enum.StrEnum):
    """What a node in the tree is.

    A closed list, because reporting scope and permission scope both read it. A free-text
    "department type" would mean two organisations spelling the same level differently and a
    scope query that silently matches neither.
    """

    COMPANY = "company"
    DIVISION = "division"
    DEPARTMENT = "department"
    TEAM = "team"


class ReportingKind(enum.StrEnum):
    """PLAN §5: "Primary manager plus optional dotted-line reporting.\""""

    #: The one that matters for approvals and escalation. At most one at any moment.
    PRIMARY = "primary"
    #: An advisory or matrix line. Any number, and never used to route an approval.
    DOTTED = "dotted"


class OrgUnit(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """A company, division, department or team."""

    __tablename__ = "org_units"

    #: Null for the root. A tenant has exactly one, enforced by a partial unique index.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(20), nullable=False)

    #: The identifier this unit has in the customer's own systems — a cost centre, an HR code.
    #: Unique per tenant where present, which is how PLAN §5's "duplicate identifiers" are
    #: detected: at the point of writing, not by a report afterwards.
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    #: Archived, never deleted. PLAN §30: "Archive without silently erasing audit evidence." A
    #: department that ran for three years is the context for every run recorded against it.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["org_units.tenant_id", "org_units.id"],
            name="fk_org_units_tenant_parent",
            #  RESTRICT, not CASCADE. Deleting a division must not silently take its departments,
            #  their positions and the history attached to them. Archiving is the supported move.
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_org_units_tenant_id"),
        Index(
            "uq_org_units_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
        Index("ix_org_units_tenant_parent", "tenant_id", "parent_id"),
        CheckConstraint(
            "unit_type IN ('company', 'division', 'department', 'team')",
            name="ck_org_units_type_known",
        ),
        CheckConstraint("id <> parent_id", name="ck_org_units_not_own_parent"),
    )


class Position(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """A seat in the tree. It exists whether or not anybody is in it."""

    __tablename__ = "positions"

    org_unit_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    #: Seniority as the customer counts it, for filtering by level (PLAN §5). Not a permission:
    #: what a person may do comes from their roles and grants, never from a number here.
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "org_unit_id"],
            ["org_units.tenant_id", "org_units.id"],
            name="fk_positions_tenant_org_unit",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_positions_tenant_id"),
        Index(
            "uq_positions_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
        Index("ix_positions_tenant_unit", "tenant_id", "org_unit_id"),
    )


class PositionAssignment(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """Who holds a position, and between which dates.

    `effective_to` is exclusive and null means open-ended. Two assignments to the same position
    may not overlap — a database exclusion constraint refuses it, because "who is the Regional
    Manager today" must have one answer and an application check cannot hold that under a bulk
    import.

    Dates, not timestamps. Somebody starts a job on a day, in their own timezone; a moment would
    be more precise and less true.
    """

    __tablename__ = "position_assignments"

    position_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "position_id"],
            ["positions.tenant_id", "positions.id"],
            name="fk_assignments_tenant_position",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_assignments_tenant_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_assignments_range_ordered",
        ),
        Index("ix_assignments_tenant_position", "tenant_id", "position_id"),
        Index("ix_assignments_tenant_membership", "tenant_id", "membership_id"),
    )


class ReportingEdge(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """One position reports to another, from a date.

    Cycles are refused by a trigger on this table. A reporting loop is not a cosmetic problem:
    escalation walks this graph, and a loop means an approval that never reaches anybody and a
    query that never terminates.
    """

    __tablename__ = "reporting_edges"

    position_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    manager_position_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "position_id"],
            ["positions.tenant_id", "positions.id"],
            name="fk_edges_tenant_position",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "manager_position_id"],
            ["positions.tenant_id", "positions.id"],
            name="fk_edges_tenant_manager",
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('primary', 'dotted')", name="ck_edges_kind_known"),
        CheckConstraint("position_id <> manager_position_id", name="ck_edges_not_self_managed"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_edges_range_ordered",
        ),
        Index("ix_edges_tenant_position", "tenant_id", "position_id"),
        Index("ix_edges_tenant_manager", "tenant_id", "manager_position_id"),
    )


class OrgRevision(Base, PrimaryKey, TenantOwned):
    """One recorded change to the tree — PLAN §5's "Revision history, undo/redo".

    Every mutation writes one, in the same transaction as the change itself, holding both the
    before and after state of what it touched. That is what makes undo possible without a second
    system: the inverse of a recorded change is computable from the row.

    Append-only, like `audit_events`. A revision history somebody can edit is not a history.
    """

    __tablename__ = "org_revisions"

    #: No `updated_at`. The row is append-only — the trigger refuses UPDATE outright — so a
    #: column recording when it last changed would be a column that can only ever be wrong.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    #: Per tenant, gapless, assigned by a BEFORE INSERT trigger. Gaps would be indistinguishable
    #: from deletions, which is the one thing this table exists to make impossible.
    #:
    #: `FetchedValue` tells SQLAlchemy the database produces this, so the number is read back
    #: after the insert rather than left as the `None` that was sent.
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=FetchedValue())

    #: What changed: `unit.created`, `position.moved`, `assignment.ended`, and so on.
    change_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    #: Enough to render the change and to reverse it. `null` in `before` means it was created;
    #: `null` in `after` means it was archived.
    before: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    #: One line for a person reading the history, written at the time. Reconstructing it later
    #: from the two JSON blobs gives a worse sentence and a false timestamp.
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: Ties this to the request that caused it and to its `AuditEvent`.
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Set when this revision was applied to undo another. Prevents an undo of an undo of an
    #: undo from looking like three unrelated edits.
    reverts_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("org_revisions.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_revisions_tenant_actor",
            ondelete="SET NULL (actor_membership_id)",
        ),
        UniqueConstraint("tenant_id", "revision_no", name="uq_revisions_tenant_no"),
        Index("ix_revisions_tenant_entity", "tenant_id", "entity_type", "entity_id"),
    )
