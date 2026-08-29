"""Column patterns every table repeats.

Kept in one place so that "every tenant-owned row has tenant_id" (PLAN §17) is a mixin a model
either has or has not, rather than a convention someone has to remember. A table with business
data and no `TenantOwned` is immediately visible in review.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class PrimaryKey:
    """An opaque UUID primary key (PLAN §28).

    Generated in the database so a row created by a migration, a worker or the API all get one
    the same way. UUIDv4 rather than a sequence: a sequential id in a URL tells the reader how
    many objects exist and lets them walk to the neighbouring one.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class Timestamps:
    """When the row was written and last changed.

    Both are set by the database clock, not the application's. Two API processes on machines
    whose clocks differ by a second would otherwise write timestamps that order events wrongly,
    and ordering is what an audit trail is for.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantOwned:
    """The tenant this row belongs to.

    Every RLS policy in the schema compares this column against the transaction's
    `app.tenant_id`. `ON DELETE RESTRICT` is deliberate: removing a tenant must be a considered
    operation with an export and a retention decision behind it, never a cascade that silently
    erases audit evidence (PLAN §30).
    """

    @declared_attr
    @classmethod
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            PG_UUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )


class OptimisticVersion:
    """Guards against a silent overwrite (PLAN §28).

    The client sends the version it read; the update matches on it and fails if someone else
    changed the row first. Without this, two people editing the same draft means the second save
    quietly discards the first — with no error, and no way to notice.
    """

    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
