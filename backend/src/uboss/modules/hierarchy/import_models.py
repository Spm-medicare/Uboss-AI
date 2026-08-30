"""The staging tables an import lives in until somebody applies it.

PLAN §5's rule is the whole design: *"Claude never writes the live hierarchy directly."* An
upload lands here, is parsed, mapped, validated and shown to a person, and only a separate,
deliberate act moves it into `org_units` and `positions` — in one transaction that either
produces the whole tree or none of it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class ImportStatus(enum.StrEnum):
    """Where an import has got to. Forward only, and never back from `APPLIED`."""

    UPLOADED = "uploaded"
    PARSED = "parsed"
    #: The columns have a meaning a person has seen. Separate from `PARSED` because the review
    #: between them is PLAN §5 step 4 — collapsing the two would make that review invisible.
    MAPPED = "mapped"
    VALIDATED = "validated"
    APPLIED = "applied"
    FAILED = "failed"
    ABANDONED = "abandoned"


class RowKind(enum.StrEnum):
    ORG_UNIT = "org_unit"
    POSITION = "position"
    ASSIGNMENT = "assignment"
    #: Recognised and deliberately not applied. Kept so "we skipped 12 rows" is visible rather
    #: than discovered by counting.
    IGNORED = "ignored"


class MappingSource(enum.StrEnum):
    """How a column's meaning was decided.

    Recorded per column so the audit can answer "who decided this" — and specifically so a
    model's suggestion is never indistinguishable from a person's choice.
    """

    #: The header matched a known field outright. No model was involved.
    EXACT = "exact"
    #: A model proposed it. Not applied until a person accepts it.
    PROPOSED = "proposed"
    #: A person picked it, overriding whatever was suggested.
    CHOSEN = "chosen"


class HierarchyImport(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    __tablename__ = "hierarchy_imports"

    #: The uploaded file. It stays `pending` in `files` for its whole life — an import source is
    #: never served back to a browser, so it never needs to leave quarantine.
    file_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="uploaded")

    #: Null for CSV, which has exactly one sheet.
    sheet_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    #: The header row as it arrived. Kept so a re-map never needs the file again.
    source_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    ignored_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    #: What the model was asked and what it answered. Null when every column matched exactly and
    #: no model was called — the common case, and worth being able to prove.
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("org_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["files.tenant_id", "files.id"],
            name="fk_imports_tenant_file",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_imports_tenant_creator",
            ondelete="SET NULL (created_by_membership_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_imports_tenant_id"),
        CheckConstraint(
            "(status <> 'applied') OR (applied_at IS NOT NULL AND applied_revision_id IS NOT NULL)",
            name="ck_imports_applied_has_evidence",
        ),
        Index("ix_imports_tenant_status", "tenant_id", "status"),
    )

    @property
    def can_apply(self) -> bool:
        """Validated, with nothing wrong in it, and not already applied."""
        return self.status == ImportStatus.VALIDATED and self.error_count == 0


class HierarchyImportRow(Base, PrimaryKey, TenantOwned, Timestamps):
    """One spreadsheet row, before it is anything."""

    __tablename__ = "hierarchy_import_rows"

    import_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    #: 1-based, as the spreadsheet numbers them, so an error names the row a person can see.
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The cells exactly as they arrived, keyed by source column.
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="org_unit")
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    #: Problems that stop this row being applied. Any of these stops the whole import.
    errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    #: Things worth saying that do not stop it.
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")

    applied_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "import_id"],
            ["hierarchy_imports.tenant_id", "hierarchy_imports.id"],
            #  The one CASCADE in this schema. A staged row has no meaning without its import,
            #  and it is not evidence of anything until applied — at which point the import
            #  itself is RESTRICT and cannot be deleted.
            name="fk_import_rows_tenant_import",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "import_id", "row_number", name="uq_import_rows_number"),
        Index("ix_import_rows_import", "tenant_id", "import_id", "row_number"),
    )
