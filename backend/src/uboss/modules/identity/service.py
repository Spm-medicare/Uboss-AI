"""Signing in, staying signed in, and signing out.

The rules this file exists to hold, all of which are easy to get subtly wrong:

* **A wrong address and a wrong password share one public contract.** Same message and status;
  a password verification also runs when no account exists to reduce the simplest timing signal.
  Exact constant-time HTTP responses are not claimed because tenant audit work can differ.
* **A refusal is refused before anything else is read.** A locked account, a removed membership,
  a suspended tenant — each ends the attempt without revealing which one applied.
* **Every attempt is recorded, including the failures.** A run of denials against one
  organisation is what an attack looks like from the inside, and an organisation cannot see one
  it was never told about.
* **The session establishes the tenant.** Nothing in a request body or a header selects it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import NotAuthenticated, ValidationFailed
from uboss.core.permissions import Action, Grant, actions_from_rows
from uboss.core.settings import Settings
from uboss.db.base import bind_session_lookup, bind_tenant, bind_verified_user
from uboss.modules.audit import service as audit
from uboss.modules.audit.models import AuditOutcome
from uboss.modules.identity import credentials, passwords, policies, tokens
from uboss.modules.identity.credentials import Credential
from uboss.modules.identity.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
    RolePermission,
    Session,
)
from uboss.modules.identity.schemas import CurrentUser, ProfileUpdate, WorkspaceSummary

#  Imported for one line: the digest reads its own copy of a person's timezone, and
#  `update_profile` keeps the two from diverging. See the note there.
from uboss.modules.notifications.models import NotificationSettings
from uboss.modules.tenancy.models import Tenant

#: Consecutive failures before the account is held closed for a while. High enough that a person
#: mistyping their password a few times is unaffected; low enough that online guessing is
#: hopeless. Offline guessing is Argon2's problem, not this counter's.
MAX_FAILED_ATTEMPTS = 10

#: How long the account stays closed. A window, not a permanent lock: a permanent one would let
#: anyone lock a colleague out by typing the wrong password ten times.
LOCKOUT_DURATION = timedelta(minutes=15)

#: `last_seen_at` is only written when it is at least this stale. Without the threshold every
#: request would write a row, turning a read-mostly workload into a write-heavy one for no gain.
LAST_SEEN_THROTTLE = timedelta(minutes=5)

#: The one message every failed sign-in returns. It names neither the address nor the password,
#: because saying which was wrong turns the form into an account-existence oracle.
SIGN_IN_FAILED = "That email address and password do not match an account."


class SignInRefused(NotAuthenticated):
    """A sign-in that did not succeed, for any reason.

    One exception type on purpose: separate types invite separate messages, and separate messages
    are exactly what must not reach the client.
    """

    def __init__(self) -> None:
        super().__init__(SIGN_IN_FAILED)


# ---------------------------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------------------------


async def authenticate(
    session: AsyncSession, *, email: str, password: str
) -> Credential:
    """Check the credentials and return the account, or refuse.

    Reaches `users` only through `credentials`, which calls the narrow database functions from
    migration 0006. The application role has no privilege on the table itself, so there is no
    query here that could be widened into a list.
    """
    now = datetime.now(UTC)
    account = await credentials.find_by_email(session, email)

    #  The verification runs whether or not the account exists, against a dummy hash when it does
    #  not. Returning early here would make "no such account" measurably faster than "wrong
    #  password", and that difference is enough to enumerate a company's staff list.
    matched = passwords.verify_password(
        account.password_hash if account else None, password
    )

    if account is None:
        raise SignInRefused()

    if account.is_locked(now):
        # Refused even with the right password. Saying so would confirm the password — turning a
        # lockout into a way to *test* passwords rather than a way to stop it.
        raise SignInRefused()

    if not matched:
        await credentials.record_failure(
            session,
            account.id,
            max_attempts=MAX_FAILED_ATTEMPTS,
            lockout=LOCKOUT_DURATION,
        )
        raise SignInRefused()

    if not account.is_active:
        raise SignInRefused()

    return account


async def record_verified_password(
    session: AsyncSession, account: Credential, password: str
) -> None:
    """Reset the failure counters and upgrade the hash after a proof succeeds.

    This may happen before workspace selection. It deliberately does not touch
    `last_sign_in_at`: proving a password is not a completed sign-in until a session exists.

    Argon2's cost may have been raised since this hash was written. The plaintext is in hand for
    exactly this moment and nowhere else, so re-hashing here upgrades people over time with no
    reset email and nobody locked out. The strength rules are not re-applied: they may have
    tightened since, and refusing a password that has just verified correctly would lock someone
    out of their own account at the moment they signed in successfully.
    """
    fresher = (
        passwords.rehash(password)
        if account.password_hash and passwords.needs_rehash(account.password_hash)
        else None
    )
    await credentials.record_verified(session, account.id, new_hash=fresher)


async def record_completed_sign_in(
    session: AsyncSession, *, account: Credential, now: datetime
) -> None:
    """Record success only when a selected workspace is about to receive a session."""
    await credentials.record_sign_in(session, account.id)


async def user_for_workspace_challenge(
    session: AsyncSession, *, user_id: uuid.UUID
) -> Credential | None:
    """Resolve the identity named by an already-verified, single-use challenge.

    The status is re-checked here rather than trusted from the challenge: an account can be
    deactivated in the seconds between proving a password and choosing a workspace.
    """
    account = await credentials.find_by_id(session, user_id)
    return account if account and account.is_active else None


async def workspaces_for(
    session: AsyncSession, account: Credential
) -> list[tuple[Membership, Tenant]]:
    """The organisations this person can actually sign in to.

    The only cross-tenant read in the product, and it is narrow by construction: the verified
    user id is bound first, and the `memberships` policy's alternative branch matches only
    `user_id = app_current_user()`. The *write* policies carry no such branch, so this yields a
    list and nothing more.

    Removed memberships and suspended tenants are filtered here rather than later, so a person
    is never offered a workspace they will then be refused from.
    """
    await bind_verified_user(session, account.id)
    rows = await session.execute(
        select(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.user_id == account.id,
            Membership.status == MembershipStatus.ACTIVE,
            Tenant.status.in_(["active", "restricted"]),
        )
        .order_by(Tenant.name)
    )
    return [(membership, tenant) for membership, tenant in rows.all()]


def summarise_workspaces(
    pairs: list[tuple[Membership, Tenant]],
) -> list[WorkspaceSummary]:
    return [
        WorkspaceSummary(
            slug=tenant.slug, name=tenant.name, display_name=membership.display_name
        )
        for membership, tenant in pairs
    ]


async def start_session(
    session: AsyncSession,
    settings: Settings,
    *,
    user: Credential,
    membership: Membership,
    tenant: Tenant,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[tokens.MintedToken, Session, SecurityContext]:
    """Create the session row and mint its token.

    The tenant is bound first, so the insert is written under the same row-level security policy
    as every other write. The raw token is returned to the caller to be put in a cookie and is
    never stored — only its hash reaches the database.
    """
    await bind_tenant(session, tenant.id)

    minted = tokens.mint(timedelta(days=settings.refresh_token_days))
    row = Session(
        tenant_id=tenant.id,
        user_id=user.id,
        membership_id=membership.id,
        token_hash=minted.hashed,
        expires_at=minted.expires_at,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:400] or None,
    )
    session.add(row)

    await audit.record(
        session,
        tenant_id=tenant.id,
        action="identity.session.signed_in",
        resource_type="session",
        actor_membership_id=membership.id,
        actor_label=membership.display_name,
        ip_address=ip_address,
        detail={"workspace": tenant.slug},
    )

    #  Flushed so the row has its generated id before a context is built around it. Not
    #  committed — the caller commits, and the audit row goes with it.
    await session.flush()

    roles, granted, ceiling = await access_for(session, membership)

    context = SecurityContext(
        tenant_id=tenant.id,
        user_id=user.id,
        membership_id=membership.id,
        session_id=row.id,
        email=user.email,
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        policy_grants=ceiling,
        org_node_id=membership.org_node_id,
        step_up_at=row.step_up_at,
        step_up_expires_at=(
            row.step_up_at + timedelta(minutes=settings.step_up_minutes)
            if row.step_up_at is not None
            else None
        ),
    )
    return minted, row, context


async def record_failed_attempt_by_email(
    session: AsyncSession, *, email: str, ip_address: str | None
) -> None:
    """Write a denied audit row to every organisation this person belongs to.

    Each organisation has a legitimate interest in knowing that someone tried to sign in as one
    of its members and failed; a burst of these is what an attack looks like from the inside.

    When the address matches no account there is no organisation to tell, so nothing is written
    here — that attempt is in the security log, with no tenant to attribute it to. Writing it
    somewhere would mean inventing an attribution.

    **Each row is bound and then flushed before the next.** `session.add()` only stages a row;
    the INSERT happens later, under whatever tenant is bound *at that moment*. Staging several
    rows for several tenants and letting them all insert at commit means every one of them is
    written under the last tenant bound — and row-level security correctly refuses the ones that
    do not match. The flush is what makes each row's binding the one it is actually inserted
    under. This applies to any multi-tenant write, not just this one.
    """
    account = await credentials.find_by_email(session, email)
    if account is None:
        return

    await bind_verified_user(session, account.id)
    rows = await session.execute(
        select(Membership.tenant_id, Membership.id, Membership.display_name).where(
            Membership.user_id == account.id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    for tenant_id, membership_id, display_name in rows.all():
        await bind_tenant(session, tenant_id)
        await audit.record(
            session,
            tenant_id=tenant_id,
            action="identity.session.sign_in_failed",
            resource_type="membership",
            resource_id=membership_id,
            outcome=AuditOutcome.DENIED,
            actor_membership_id=membership_id,
            actor_label=display_name,
            ip_address=ip_address,
            denial_reason="credentials did not match",
            detail={"email": email},
        )
        # Inserted now, while this row's tenant is the bound one. See the docstring.
        await session.flush()


async def record_authenticated_sign_in_denial(
    session: AsyncSession,
    *,
    user: Credential,
    ip_address: str | None,
    denial_reason: str,
) -> None:
    """Audit a refusal that happened after the password was verified.

    This covers an account with no usable workspace and a requested workspace that is not in the
    verified account's active list. The client still receives the ordinary sign-in refusal; the
    precise reason remains tenant audit evidence.
    """
    await bind_verified_user(session, user.id)
    rows = await session.execute(
        select(Membership.tenant_id, Membership.id, Membership.display_name).where(
            Membership.user_id == user.id
        )
    )
    for tenant_id, membership_id, display_name in rows.all():
        await bind_tenant(session, tenant_id)
        await audit.record(
            session,
            tenant_id=tenant_id,
            action="identity.session.sign_in_denied",
            resource_type="membership",
            resource_id=membership_id,
            outcome=AuditOutcome.DENIED,
            actor_membership_id=membership_id,
            actor_label=display_name,
            ip_address=ip_address,
            denial_reason=denial_reason,
        )
        # Multi-tenant inserts must execute while their own tenant is bound.
        await session.flush()


async def access_for(
    session: AsyncSession, membership: Membership
) -> tuple[tuple[str, ...], frozenset[Action], tuple[Grant, ...]]:
    """Everything a caller may do: their roles, what those grant, and what narrows it.

    One query joining `membership_roles` → `roles` → `role_permissions`, because roles are a
    table (PLAN §17) and their permissions are rows, not a dictionary in code.

    A role with no permission rows contributes nothing. That is the correct answer while the
    Gate 0 §0.2 matrix is unapproved: a carried-over role grants nothing, visibly, instead of
    falling back to a set somebody invented.

    An outer join, so a role with no permissions still appears in the names — a person's roles
    should be shown even when they currently grant nothing.

    The third return value is PLAN §14 chain above the role: the company and department policies
    that narrow what those roles grant. Resolved here, once, at the moment the session is
    verified — so one request cannot answer "may they?" two different ways.
    """
    rows = (
        await session.execute(
            select(Role.key, RolePermission.action, RolePermission.is_conditional)
            .select_from(MembershipRole)
            .join(Role, Role.id == MembershipRole.role_id)
            .outerjoin(RolePermission, RolePermission.role_id == Role.id)
            .where(MembershipRole.membership_id == membership.id)
        )
    ).all()

    keys = {key for key, _action, _conditional in rows}
    permissions = [
        (action, conditional) for _key, action, conditional in rows if action is not None
    ]
    granted = actions_from_rows(permissions)

    ceiling = await policies.grants_above_role(
        session,
        tenant_id=membership.tenant_id,
        org_node_id=membership.org_node_id,
        role_actions=granted,
    )
    return tuple(sorted(keys)), granted, ceiling


# ---------------------------------------------------------------------------------------------
# Staying signed in
# ---------------------------------------------------------------------------------------------


async def resolve_session(
    session: AsyncSession, raw_token: str, settings: Settings
) -> tuple[SecurityContext, Session, tokens.MintedToken | None]:
    """Turn a cookie into a verified caller, or refuse.

    The order matters. The session row is found by hash, then the tenant is bound, and only then
    is anything else read. Every check afterwards runs inside the tenant boundary.

    Every refusal raises the same exception with the same message. A client that could tell
    "expired" from "revoked" from "your membership was removed" would learn things about an
    account it has no token for.
    """
    now = datetime.now(UTC)
    token_hash = tokens.hash_token(raw_token)

    await bind_session_lookup(session, token_hash)
    row = (
        await session.execute(
            select(Session).where(
                or_(
                    Session.token_hash == token_hash,
                    and_(
                        Session.previous_token_hash == token_hash,
                        Session.previous_valid_until > now,
                    ),
                )
            )
        )
    ).scalar_one_or_none()

    idle_timeout = timedelta(minutes=settings.session_idle_minutes)
    if row is None or not row.is_usable(now, idle_timeout):
        raise NotAuthenticated("Your session has ended. Sign in again.")

    await bind_tenant(session, row.tenant_id)

    #  Two queries rather than one join: `users` is no longer joinable by the application role
    #  (migration 0006), so the membership and its organisation are read from tenant-owned
    #  tables and the account is fetched by id through the narrow function.
    loaded = (
        await session.execute(
            select(Membership, Tenant)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(Membership.id == row.membership_id)
        )
    ).first()

    if loaded is None:
        raise NotAuthenticated("Your session has ended. Sign in again.")

    membership, tenant = loaded
    user = await credentials.find_by_id(session, membership.user_id)
    if user is None:
        raise NotAuthenticated("Your session has ended. Sign in again.")

    #  Re-checked on every request, not just at sign-in. Deactivating a person, removing them
    #  from an organisation or suspending a tenant has to take effect now — which is the reason
    #  sessions live in the database rather than in a self-contained token.
    if (
        membership.status != MembershipStatus.ACTIVE
        or not user.is_active
        or not tenant.allows_sign_in
    ):
        raise NotAuthenticated("Your session has ended. Sign in again.")

    rotated: tokens.MintedToken | None = None
    rotation_due = row.token_rotated_at <= now - timedelta(
        minutes=settings.session_rotation_minutes
    )
    # Only the current token initiates routine rotation. A previous-token request was already in
    # flight when another request rotated; accepting it during grace avoids a random logout, but
    # it does not churn the token again.
    if row.token_hash == token_hash and rotation_due:
        locked = (
            await session.execute(
                select(Session).where(Session.id == row.id).with_for_update()
            )
        ).scalar_one()
        still_due = locked.token_rotated_at <= now - timedelta(
            minutes=settings.session_rotation_minutes
        )
        if (
            locked.token_hash == token_hash
            and still_due
            and locked.is_usable(now, idle_timeout)
        ):
            rotated = tokens.mint_until(locked.expires_at)
            locked.previous_token_hash = locked.token_hash
            locked.previous_valid_until = now + timedelta(
                seconds=settings.session_rotation_grace_seconds
            )
            locked.token_hash = rotated.hashed
            locked.token_rotated_at = now
            row = locked

    roles, granted, ceiling = await access_for(session, membership)

    if row.last_seen_at < now - LAST_SEEN_THROTTLE:
        await session.execute(
            update(Session).where(Session.id == row.id).values(last_seen_at=now)
        )

    context = SecurityContext(
        tenant_id=tenant.id,
        user_id=user.id,
        membership_id=membership.id,
        session_id=row.id,
        email=user.email,
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        policy_grants=ceiling,
        org_node_id=membership.org_node_id,
        step_up_at=row.step_up_at,
        step_up_expires_at=(
            row.step_up_at + timedelta(minutes=settings.step_up_minutes)
            if row.step_up_at is not None
            else None
        ),
    )
    return context, row, rotated


async def prove_password_for_step_up(
    session: AsyncSession,
    settings: Settings,
    *,
    context: SecurityContext,
    password: str,
    ip_address: str | None,
) -> datetime | None:
    """Re-check the signed-in user's password and open a short high-risk-action window.

    ``None`` means the proof failed. The denied audit row is still staged so the API can commit
    it before returning a refusal. A successful proof updates only the current session: another
    browser does not inherit it, and password proof never widens the caller's permissions.
    """
    account = await credentials.find_by_id(session, context.user_id)
    if account is None or not passwords.verify_password(account.password_hash, password):
        await audit.record(
            session,
            tenant_id=context.tenant_id,
            action="identity.step_up.denied",
            resource_type="session",
            resource_id=context.session_id,
            outcome=AuditOutcome.DENIED,
            actor=context,
            denial_reason="password proof was not accepted",
            ip_address=ip_address,
        )
        return None

    now = datetime.now(UTC)
    updated_session_id = (
        await session.execute(
        update(Session)
        .where(
            Session.id == context.session_id,
            Session.tenant_id == context.tenant_id,
            Session.user_id == context.user_id,
            Session.revoked_at.is_(None),
        )
        .values(step_up_at=now)
        .returning(Session.id)
        )
    ).scalar_one_or_none()
    if updated_session_id is None:
        raise NotAuthenticated("Your session has ended. Sign in again.")

    if account.password_hash and passwords.needs_rehash(account.password_hash):
        await credentials.record_verified(
            session, account.id, new_hash=passwords.rehash(password)
        )

    expires_at = now + timedelta(minutes=settings.step_up_minutes)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="identity.step_up.completed",
        resource_type="session",
        resource_id=context.session_id,
        actor=context,
        detail={"method": "password", "expires_at": expires_at.isoformat()},
        ip_address=ip_address,
    )
    return expires_at


async def update_profile(
    session: AsyncSession,
    context: SecurityContext,
    payload: ProfileUpdate,
) -> Membership:
    """Change what a person is called, what they do, and which zone they read times in.

    **The membership owns a person's timezone**, and until now nothing wrote it. `describe()` has
    always read `membership.timezone or tenant.timezone`, and the whole frontend formats every
    instant with what it returns — so somebody working in Dubai read a workspace of Kolkata times
    and had no way to change it. The one control that looked like it should was the notification
    digest's own timezone, which only decides when a digest is sent.

    Both are written here, deliberately. The membership is the owner; the notification settings'
    own copy is kept in step because `digest_worker.send_due` reads that one, and a person whose
    screen shows
    Dubai must not receive their digest at Kolkata's eight o'clock. One column is the right
    end state and belongs with the rest of the Settings work; two that cannot diverge is the honest
    version of it today.

    No permission check beyond being signed in: this is a person editing themselves. Changing
    *somebody else's* name is a different act, needs `manage_access`, and has no route.
    """
    membership = await session.get(Membership, context.membership_id)
    if membership is None:  # pragma: no cover — the session was resolved from this row
        raise NotAuthenticated("Your session has ended. Sign in again.")

    changed: list[str] = []

    if payload.display_name is not None and payload.display_name.strip():
        name = payload.display_name.strip()
        if name != membership.display_name:
            membership.display_name = name
            changed.append("display_name")

    if payload.job_title is not None:
        title = payload.job_title.strip() or None
        if title != membership.job_title:
            membership.job_title = title
            changed.append("job_title")

    if payload.timezone is not None:
        zone = payload.timezone.strip()
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as cause:
            #  Validated against the system's zone database rather than a list kept in the code.
            #  The same rule `jobs/recurrence.py` applies to a schedule, and the same wording.
            raise ValidationFailed(
                f"“{zone}” is not a timezone this system knows. Use an IANA name such as "
                "“Asia/Kolkata”."
            ) from cause
        if zone != membership.timezone:
            membership.timezone = zone
            changed.append("timezone")
        #  Kept in step, for the reason in this function's docstring.
        settings_row = (
            await session.execute(
                select(NotificationSettings).where(
                    NotificationSettings.tenant_id == context.tenant_id,
                    NotificationSettings.membership_id == context.membership_id,
                )
            )
        ).scalar_one_or_none()
        if settings_row is not None and settings_row.timezone != zone:
            settings_row.timezone = zone

    if changed:
        await session.flush()
        await audit.record(
            session,
            tenant_id=context.tenant_id,
            action="profile.updated",
            resource_type="membership",
            resource_id=context.membership_id,
            actor=context,
            #  Which fields, not their values. A name is personal data, and an audit trail that
            #  copies it is a second place it lives with none of the retention rules of the first.
            detail={"fields": changed},
        )

    return membership


def describe(
    context: SecurityContext,
    *,
    membership: Membership,
    tenant: Tenant,
    session_row: Session,
) -> CurrentUser:
    """What the interface is told about the signed-in person."""
    return CurrentUser(
        membership_id=context.membership_id,
        display_name=context.display_name,
        email=context.email,
        job_title=membership.job_title,
        roles=list(context.roles),
        actions=sorted(action.value for action in context.actions),
        workspace_slug=tenant.slug,
        workspace_name=tenant.name,
        timezone=membership.timezone or tenant.timezone,
        org_node_id=context.org_node_id,
        stepped_up=context.has_stepped_up(),
        session_expires_at=session_row.expires_at,
    )


# ---------------------------------------------------------------------------------------------
# Signing out
# ---------------------------------------------------------------------------------------------


async def end_session(
    session: AsyncSession, *, context: SecurityContext, session_id: uuid.UUID
) -> None:
    """Revoke a session immediately.

    Sets `revoked_at` rather than deleting the row: the audit trail refers to a session id, and
    a deleted row would leave those references pointing at nothing.
    """
    await session.execute(
        update(Session)
        .where(Session.id == session_id, Session.tenant_id == context.tenant_id)
        .values(revoked_at=datetime.now(UTC))
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="identity.session.signed_out",
        resource_type="session",
        resource_id=session_id,
        actor=context,
    )
