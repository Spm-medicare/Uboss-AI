"""Who a person is, which organisations they belong to, and how a session is proved.

The split between `User` and `Membership` is the important decision here.

**`users` holds credentials and nothing else.** An email address and a password hash. It is
global — the same person signs in once and may belong to several tenants — which is exactly why
it cannot carry a `tenant_id`, and therefore cannot be protected by tenant row-level security.
Those credentials are highly sensitive even without profile data, so application access to this
table must remain confined to the identity repository. It is never returned by any endpoint.

**`memberships` holds the person as that organisation knows them.** Display name, job title,
roles, position in the hierarchy. It is tenant-owned and RLS-protected like everything else, so
the profile data an attacker would actually want is behind the same boundary as the rest.

It is also simply more correct: the same person can be "Pranav Kumar, Operations" in one tenant
and a contractor with a different title in another.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timedelta

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
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    #: Cannot sign in anywhere. Set when a person leaves the company entirely. Deactivating a
    #: user triggers ownership reassignment for Agents, schedules and connections (PLAN §14) —
    #: that reassignment is a Gate 5 concern, but the status it keys off lives here.
    DEACTIVATED = "deactivated"


class MembershipStatus(enum.StrEnum):
    ACTIVE = "active"
    #: Invited but has not signed in yet. Counts against nothing and can do nothing.
    INVITED = "invited"
    #: Left this organisation. Their audit trail stays; their access does not.
    REMOVED = "removed"


class User(Base, PrimaryKey, Timestamps):
    """Credentials only. Never serialised to a client.

    Deliberately has no display name and no tenant. See the module docstring.
    """

    __tablename__ = "users"

    #: Stored lowercase — the application normalises before writing, and the unique index is on
    #: the stored value, so "A@x.com" and "a@x.com" cannot become two accounts.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)

    #: Argon2id. The algorithm and its parameters are encoded in the hash itself, so raising the
    #: cost later re-hashes people transparently at their next sign-in.
    #: Null for an account that exists but has no password yet — an invited person, or one who
    #: signs in through an identity provider.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )

    last_sign_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Consecutive failures since the last success. Reset on success.
    failed_sign_in_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    #: Set when the count crosses the threshold. Sign-in is refused until it passes — slowing an
    #: online guessing attack without giving an attacker a way to lock someone out permanently.
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'deactivated')", name="status_known"
        ),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("position('@' in email) > 1", name="email_shape"),
    )

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE


class Membership(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """One person, in one organisation.

    This is what the rest of the product means by "a person": tasks are assigned to a
    membership, approvals are held by a membership, and the hierarchy positions a membership.
    A `user_id` is only how they signed in.
    """

    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    #: As this organisation knows them.
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="invited"
    )

    #: Where they sit in the hierarchy. Null until the hierarchy exists (Step 4) or until
    #: someone is placed. Reporting scope is derived from it, so a person with no node sees only
    #: what is theirs — never "everything" by default.
    org_node_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )

    #: Their own choice, falling back to the tenant's. IANA name (PLAN §17).
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        #  One membership per person per tenant. Two would mean two sets of roles for the same
        #  person, and no defined answer for which applies.
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_id_user_id"),
        #  Candidate keys used by composite FKs on roles and sessions. They make copied
        #  tenant/user columns prove one membership tuple rather than three valid rows.
        UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "id",
            "user_id",
            name="uq_memberships_tenant_id_id_user_id",
        ),
        CheckConstraint(
            "status IN ('active', 'invited', 'removed')", name="status_known"
        ),
        Index("ix_memberships_tenant_id_status", "tenant_id", "status"),
    )

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE


class MembershipRole(Base, PrimaryKey, TenantOwned, Timestamps):
    """A role held by a membership.

    A separate row per role, because one person may hold several — a manager who also builds is
    both `builder` and `approver`. The permission layer unions across a person's roles and
    intersects down the company → department → resource chain; the two are not the same
    operation and conflating them is how a ceiling gets breached.
    """

    __tablename__ = "membership_roles"

    membership_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: One of the names in `core.permissions.ROLE_MATRIX`. Constrained in the database so a typo
    #: cannot create a role that silently grants nothing — an unknown role contributes no
    #: actions, which would look like a permission bug rather than a data error.
    role: Mapped[str] = mapped_column(String(40), nullable=False)

    #: Who granted it. Null for the roles created when a tenant is first set up.
    granted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_membership_roles_tenant_membership",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "granted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_membership_roles_tenant_grantor",
            ondelete="SET NULL",
        ),
        UniqueConstraint(
            "membership_id", "role", name="uq_membership_roles_membership_id_role"
        ),
        CheckConstraint(
            "role IN ('viewer', 'contributor', 'builder', 'approver', 'manager', 'admin')",
            name="role_known",
        ),
    )


class Session(Base, PrimaryKey, TenantOwned, Timestamps):
    """A signed-in session, held in the database rather than in a token.

    A self-contained token (a JWT) cannot be withdrawn before it expires. This product needs
    withdrawal to be immediate: PLAN §19 requires workspace and integration kill switches, and
    deactivating a person has to end their access now, not in thirty minutes. A row that can be
    marked revoked does that; a signed token does not.

    The cost is a database read per request. It is one indexed lookup on a primary-key-sized
    column, and it buys the ability to end a session.
    """

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: SHA-256 of the token the browser holds. The token itself is never stored: a stolen
    #: database backup then contains no usable session, only hashes of expired ones.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: One prior token remains readable briefly so requests already in flight do not fail when
    #: another request rotates the browser cookie. It can establish the same session only; it
    #: never extends the absolute or idle lifetime.
    previous_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    token_rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    #: Set when the person signs out, an administrator ends the session, or the account is
    #: deactivated. A revoked session is refused even before its expiry is checked.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Set when a second factor was proved. Publishing and other high-risk actions check this
    #: rather than re-asking, so a session that never proved one cannot perform them.
    step_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Rolled forward on use, so an idle session can be expired separately from an old one.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    #: For the person's own "where am I signed in?" list, and for an investigation. Recorded, not
    #: enforced — a changing address is normal on a mobile network, and refusing on it would
    #: sign people out on a train.
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "membership_id", "user_id"],
            ["memberships.tenant_id", "memberships.id", "memberships.user_id"],
            name="fk_sessions_tenant_membership_user",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(previous_token_hash IS NULL) = (previous_valid_until IS NULL)",
            name="previous_token_pair",
        ),
        CheckConstraint(
            "previous_token_hash IS NULL OR previous_token_hash <> token_hash",
            name="previous_token_differs",
        ),
        Index("ix_sessions_tenant_id_user_id", "tenant_id", "user_id"),
        Index("ix_sessions_previous_token_hash", "previous_token_hash"),
    )

    def is_usable(self, now: datetime, idle_timeout: timedelta) -> bool:
        return (
            self.revoked_at is None
            and self.expires_at > now
            and self.last_seen_at > now - idle_timeout
        )
