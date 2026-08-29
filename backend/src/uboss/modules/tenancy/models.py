"""The tenant: one customer organisation.

Everything else in the product hangs off a tenant, and the tenant a request belongs to is
decided by the verified session — never by a request body, a query parameter or the `Host`
header.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, Timestamps


class TenantStatus(enum.StrEnum):
    ACTIVE = "active"
    #: Signed in but read-only — used while a billing or compliance question is open. The
    #: distinction from `suspended` matters: a person can still get their data out.
    RESTRICTED = "restricted"
    #: No access at all. Rows are kept; access is refused.
    SUSPENDED = "suspended"


class Tenant(Base, PrimaryKey, Timestamps, OptimisticVersion):
    __tablename__ = "tenants"

    #: The name in the URL and in a sign-in form. Immutable in practice — changing it breaks
    #: every saved link — so a rename is a deliberate operation, not a field edit.
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )

    #: Reporting and schedules are shown in this zone unless a person has chosen another. Stored
    #: as an IANA name, never as an offset: an offset is wrong twice a year (PLAN §17).
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Asia/Kolkata"
    )

    #: Set when the tenant was suspended, so a support conversation can start from a fact.
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'restricted', 'suspended')",
            name="status_known",
        ),
        #  Lowercase letters, digits and hyphens, not starting or ending with a hyphen. Enforced
        #  in the database because a slug reaches the schema from more than one code path.
        CheckConstraint(
            r"slug ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'",
            name="slug_shape",
        ),
    )

    @property
    def is_active(self) -> bool:
        return self.status == TenantStatus.ACTIVE

    @property
    def allows_sign_in(self) -> bool:
        """A restricted tenant can still be read; a suspended one cannot be reached at all."""
        return self.status in (TenantStatus.ACTIVE, TenantStatus.RESTRICTED)
