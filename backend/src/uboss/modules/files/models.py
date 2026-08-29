"""What the product knows about a file. The bytes are in object storage.

PLAN §30: "Files live in object storage; database stores metadata, classification, hashes and
references."
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import PrimaryKey, TenantOwned, Timestamps


class Classification(enum.StrEnum):
    """What the file is, for retention and for who may see it.

    A column rather than a guess made later from the file name, because PLAN §19 requires the
    privacy controls to act on it.
    """

    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PERSONAL_DATA = "personal_data"
    PUBLIC = "public"


class ScanState(enum.StrEnum):
    """Where a file is in the malware scan.

    `PENDING` blocks download. A file that has been uploaded and not yet scanned is not a file
    anyone should be handed, and the safe default is the one that refuses.
    """

    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    #: The scanner ran and could not decide. Treated exactly like `PENDING` for access — a file
    #: nobody could check is not a file to serve.
    FAILED = "failed"


class File(Base, PrimaryKey, TenantOwned, Timestamps):
    __tablename__ = "files"

    #: The object's key in the bucket, tenant-prefixed (`t/<tenant>/<uuid>`). Stored rather than
    #: derived, so changing the naming scheme later cannot orphan everything uploaded before it.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    #: As the person named it. **Never** used to build the storage key — a filename arrives from
    #: a browser and may contain anything, `../` included.
    original_name: Mapped[str] = mapped_column(String(400), nullable=False)
    content_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: Computed from the bytes as they were stored, not taken from the client. It says what was
    #: actually written, which is the only version worth having.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    classification: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="internal"
    )
    scan_state: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    scan_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    uploaded_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    #: What it is attached to. Null while a file is uploaded before the thing it belongs to
    #: exists — a draft being written, for instance.
    owner_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_files_tenant_uploader",
            #  Column-specific: plain SET NULL clears every column in the key, `tenant_id`
            #  included, and that column is NOT NULL. Migration 0010 has the whole story.
            ondelete="SET NULL (uploaded_by_membership_id)",
        ),
        UniqueConstraint("storage_key", name="uq_files_storage_key"),
        CheckConstraint(
            "classification IN ('internal', 'confidential', 'personal_data', 'public')",
            name="classification_known",
        ),
        CheckConstraint(
            "scan_state IN ('pending', 'clean', 'infected', 'failed')",
            name="scan_state_known",
        ),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
        #  The key must carry this tenant's own prefix. Belt and braces with row-level security:
        #  a row that passed the policy but pointed at another tenant's object would hand over
        #  its bytes, and a policy cannot see inside a string.
        CheckConstraint(
            "storage_key LIKE 't/' || tenant_id::text || '/%'",
            name="key_is_tenant_prefixed",
        ),
        Index("ix_files_tenant_id_owner", "tenant_id", "owner_type", "owner_id"),
    )

    @property
    def is_downloadable(self) -> bool:
        """Only a scanned, clean file may be handed to anybody."""
        return self.scan_state == ScanState.CLEAN
