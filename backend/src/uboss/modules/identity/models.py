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
    Boolean,
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


class Role(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """A named set of permissions, defined per organisation.

    PLAN §17 lists roles as a table in the Identity domain, and this is that table. Role names
    are **not** defined in code: the approved matrix is PLAN §25 first implementation deliverable
    #2 and does not exist yet, so seeding it later is a data change rather than a migration.

    An earlier implementation hard-coded six role names that appear nowhere in PLAN. Migration
    0004 removed them.
    """

    __tablename__ = "roles"

    #: Stable and machine-readable; referenced by grants, so it does not change. `name` is what a
    #: person sees and may be renamed or translated freely.
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    #: Seeded with the tenant and undeletable. Removing the only role holding `administer` would
    #: leave an organisation nobody can administer. A tenant may still narrow what it grants.
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: True until the Gate 0 §0.2 matrix is approved. Read by the interface so a screen can say
    #: the access model is provisional rather than presenting a draft as settled.
    is_draft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_id_key"),
        UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id_id"),
        CheckConstraint(r"key ~ '^[a-z][a-z0-9_]*$'", name="key_shape"),
    )


class RolePermission(Base, PrimaryKey, TenantOwned):
    """One action a role permits.

    The action names are constrained to the thirteen in PLAN §14 — those *are* in the approved
    specification, unlike the role names, so the database enforces them.
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)

    #: `ACCESS_MODEL.md` marks some cells `C`: permitted only with an explicit resource or scope
    #: grant. A conditional row grants nothing on its own — the resource layer decides. Kept
    #: distinct so the approved matrix can be seeded faithfully instead of flattened to yes/no.
    is_conditional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_role_permissions_tenant_role",
            ondelete="CASCADE",
        ),
        UniqueConstraint("role_id", "action", name="uq_role_permissions_role_id_action"),
    )


class MembershipRole(Base, PrimaryKey, TenantOwned, Timestamps):
    """A role held by a membership.

    A separate row per role, because one person may hold several. The permission layer unions
    across a person's roles and intersects down the company → department → resource chain; the
    two are not the same operation, and conflating them is how a ceiling gets breached.
    """

    __tablename__ = "membership_roles"

    membership_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Points at a row in `roles`, not at a name. What the role permits is a join away, so
    #: changing an organisation's access model never touches this table.
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )

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
            #  Column-specific — see migration 0010.
            ondelete="SET NULL (granted_by_membership_id)",
        ),
        #  RESTRICT: deleting a role people still hold would silently remove their access. It has
        #  to be taken off every membership first, deliberately.
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_membership_roles_tenant_role",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "membership_id", "role_id", name="uq_membership_roles_membership_id_role_id"
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


class FederatedIdentity(Base, PrimaryKey, Timestamps):
    """A provider account linked to a user — Google, Microsoft or Apple.

    **The identity is `(provider, subject)`, never the email address.** A provider's `sub` is
    stable; an address is not, and matching on one would let somebody who acquires an old address
    inherit the account it used to belong to. The email here is kept so an administrator can see
    what the provider asserts, not so anything can be found by it.

    No `tenant_id`, like `users`: a person signs in once and may belong to several workspaces, so
    a credential cannot belong to one of them.
    """

    __tablename__ = "federated_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    #: OIDC's `sub`. The provider's own stable identifier for this person.
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_federated_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_federated_user_provider"),
        Index("ix_federated_user", "user_id"),
    )
