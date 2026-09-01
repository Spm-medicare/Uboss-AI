"""Notifications, as SQLAlchemy sees them.

Mirrors migration 0037. The reasoning for each column is there; this is the mapping.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from uboss.db.base import Base
from uboss.db.mixins import PrimaryKey, TenantOwned


class Category(enum.StrEnum):
    """§12's six, verbatim.

    *"task/assignment, approval/input, Agent failure/result, schedule/lifecycle, mention/comment
    and security/admin"*. This is the list a person is offered when they choose what to be told
    about, so a seventh invented here would be a preference nobody asked for.
    """

    TASK_ASSIGNMENT = "task_assignment"
    APPROVAL_INPUT = "approval_input"
    AGENT_RESULT = "agent_result"
    SCHEDULE_LIFECYCLE = "schedule_lifecycle"
    MENTION_COMMENT = "mention_comment"
    SECURITY_ADMIN = "security_admin"


class Delivery(enum.StrEnum):
    """How a category reaches somebody.

    `OFF` is a choice a person made and is stored as one. The *absence* of a preference row means
    they never decided, which gets the defaults — a different thing, and worth keeping different.
    """

    IMMEDIATE = "immediate"
    DIGEST = "digest"
    OFF = "off"


class Notification(Base, PrimaryKey, TenantOwned):
    """One thing somebody is being told."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_notifications_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_notifications_membership",
            ondelete="CASCADE",
        ),
    )

    #: A membership, not a user. The same person in two workspaces has two bells.
    membership_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    #: One of `Category`.
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    #: The specific thing — `task.assigned`. Finer than the category, which is what people
    #: subscribe to; this is what the line says.
    event: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Null for anything nobody did — a schedule firing, a run failing on its own.
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: A path this app owns, never a full URL — a stored origin goes stale the day the product
    #: moves domain, and a notification that navigates somewhere else is worse than one that does
    #: not navigate at all.
    deep_link: Mapped[str] = mapped_column(String(500), nullable=False)

    #: The *Action required* tab. Decided by whoever raises it, because only they know whether
    #: this is a request or a report.
    action_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    #: "This is the same fact." Repeats fold in rather than stacking up — enforced while unread
    #: by `uq_notifications_unread_dedupe`.
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: "These belong together." Nine assignments from one run are nine facts under one heading.
    group_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: When it last happened. The honest answer to "when did this last go wrong".
    last_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NotificationPreference(Base, PrimaryKey, TenantOwned):
    """What one person wants to be told about one category.

    A row exists only where somebody chose. No row means the defaults in `policy.py`, which is
    deliberately different from a `false` nobody selected.
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "membership_id", "category", name="uq_notification_prefs_one_per_category"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_notification_prefs_membership",
            ondelete="CASCADE",
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: One of `Delivery`.
    delivery: Mapped[str] = mapped_column(
        String(20), nullable=False, default=Delivery.IMMEDIATE
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NotificationSettings(Base, PrimaryKey, TenantOwned):
    """Quiet hours and the digest hour — properties of a person, not of a category."""

    __tablename__ = "notification_settings"
    __table_args__ = (
        UniqueConstraint(
            "membership_id", name="uq_notification_settings_one_per_person"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_notification_settings_membership",
            ondelete="CASCADE",
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    quiet_hours_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: Local times, not instants: "between 22:00 and 07:00" is a statement about a clock on a
    #: wall and stays true across a daylight-saving change.
    quiet_from: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_to: Mapped[time | None] = mapped_column(Time, nullable=True)
    #: IANA, and the person's own — quiet hours mean where *they* are.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Kolkata"
    )
    digest_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    #: So the next digest covers exactly what has happened since, and a restarted worker cannot
    #: send the same summary twice.
    last_digest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
