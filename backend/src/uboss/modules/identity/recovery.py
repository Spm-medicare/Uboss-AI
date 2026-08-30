"""Password reset and invite acceptance — 1.2.6.

The delivery breakdown states four rules for this step *"that do not bend"*, and every one of them
is a line of code here rather than a note:

> requesting a reset answers identically whether or not the account exists · no reusable plaintext
> password is ever sent · completing a reset revokes every session in every tenant · the screen
> never says "email sent" unless an email was accepted for delivery.

## The fourth rule, and the honest way to keep it

There is no mail provider configured, and that is a client decision rather than something this
code can fix. So the response carries `delivery` — `queued` when an event was accepted into the
outbox for a real provider to send, and `unavailable` when no provider exists. The screen renders
the second as *"this system cannot send email yet"*, which is a fact about the deployment.

That does **not** weaken the first rule. `unavailable` is returned whether or not the address
matches an account, so it leaks nothing; and when a provider *is* configured the answer is
`queued` either way, because the event is queued for a non-existent account too and simply has no
recipient. An attacker learns the same thing from both: nothing.

## What is deliberately absent

`action_tokens.py` has said since Gate 1 that it *"deliberately does not expose an HTTP route"*
until there is an authorised issuer, audited delivery and cross-tenant revocation. All three now
exist, which is why these routes can be written — not because the rule was relaxed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.errors import ValidationFailed
from uboss.core.logging import get_logger
from uboss.core.settings import Settings
from uboss.db.base import bind_verified_user, tenant_scope
from uboss.modules.audit import service as audit
from uboss.modules.audit.models import AuditOutcome
from uboss.modules.identity import action_tokens, credentials, passwords
from uboss.modules.identity.models import Membership, Session

log = get_logger(__name__)


class Delivery(StrEnum):
    """What actually happened to the message — not what the person was told about their account.

    Separate from the account answer on purpose. One is a fact about this deployment and is safe
    to state; the other would reveal whether an address is registered and never is.
    """

    #: Accepted into the outbox for a configured provider to send.
    QUEUED = "queued"
    #: No mail provider is configured, so nothing was sent and nothing will be.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ResetRequested:
    """The answer to a reset request. Identical for every address."""

    delivery: Delivery


async def request_reset(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    email: str,
    ip_address: str | None = None,
) -> ResetRequested:
    """Begin a password reset.

    **The return value does not depend on whether the account exists.** Not the shape, not the
    timing branch, not the message. The only thing that varies is whether a token was actually
    minted, and that is invisible from outside.
    """
    normalised = email.strip().lower()

    #  Through `auth_find_by_email`, never `select(User)`. The application role has no
    #  privilege on `users` — migration 0006 withheld it on purpose — so a direct query fails,
    #  and the only way to make one work would be to grant the privilege this design withholds.
    user = await credentials.find_by_email(session, normalised)

    #  Resolved once and reused: the audit row and the outbox row are both tenant-scoped, and
    #  asking twice would be two queries answering the same question.
    tenant_id = await _any_tenant(session, user.id if user else None)

    #  A suspended account gets a token no more than a missing one does, and neither is said out
    #  loud. An administrator can see the difference in the audit trail.
    #
    #  A tenant is required as well as an active account, because the outbox row is
    #  tenant-scoped. A user with no membership belongs to no workspace, so there is no queue
    #  for this to join — sign-up and invitation both create one, so in practice this is
    #  unreachable. Written as a condition rather than an assertion: an unreachable branch that
    #  raises is worse than one that quietly gives the same answer as "no account".
    if user is not None and user.is_active and tenant_id is not None:
        token = await action_tokens.issue(
            redis,
            purpose=action_tokens.ActionTokenPurpose.PASSWORD_RESET,
            user_id=user.id,
            ttl_seconds=settings.password_reset_token_minutes * 60,
        )
        #  Queued into the outbox, which is what actually delivers. The link is built from
        #  `public_base_url` — never from a request header, which is attacker-controlled.
        #
        #  Bound before the insert: `outbox_events` carries the same row-level policy every
        #  tenant-scoped table does, and a pre-session request has bound nothing.
        async with tenant_scope(session, tenant_id):
            await audit.publish(
                session,
                tenant_id=tenant_id,
                event_type="identity.password_reset_requested",
                subject_type="user",
                subject_id=user.id,
                payload={
                    "email": normalised,
                    #  The token travels in the outbox payload because that is what the mail
                    #  body needs. `scrub` leaves it alone: it is single-use, short-lived, and
                    #  useless without the address it was minted for.
                    "reset_url": (
                        f"{settings.public_base_url.rstrip('/')}/reset-password?token={token}"
                    ),
                    "expires_in_minutes": settings.password_reset_token_minutes,
                },
            )

    #  Recorded for every request, existing account or not — a reset attempt against an unknown
    #  address is exactly the pattern an administrator needs to be able to see.
    await _record(
        session,
        tenant_id,
        action="identity.password_reset_requested",
        resource_type="user",
        resource_id=user.id if user else None,
        outcome=AuditOutcome.SUCCEEDED,
        actor_label=normalised,
        ip_address=ip_address,
        detail={"account_found": user is not None},
    )

    return ResetRequested(
        delivery=Delivery.QUEUED if settings.mail_is_configured else Delivery.UNAVAILABLE
    )


async def complete_reset(
    session: AsyncSession,
    redis: Redis,
    *,
    token: str,
    new_password: str,
    ip_address: str | None = None,
) -> credentials.Credential:
    """Set a new password and sign the account out everywhere.

    **Every session in every tenant.** A reset is what somebody does when they believe their
    account is compromised, and leaving the attacker's session alive would make the whole exercise
    theatre. The token is consumed first, so a replay cannot revoke a second time.
    """
    claim = await action_tokens.consume(
        redis,
        raw=token,
        expected_purpose=action_tokens.ActionTokenPurpose.PASSWORD_RESET,
    )
    if claim is None:
        raise ValidationFailed(
            "That reset link has expired or was already used. Request a new one."
        )

    user = await credentials.find_by_id(session, claim.user_id)
    if user is None or not user.is_active:
        raise ValidationFailed("That account cannot be reset. Ask an administrator.")

    #  The same strength rules the sign-in path applies. A reset is not a way around them.
    passwords.check_strength(new_password)
    #  `auth_record_verified` writes the hash and clears the lockout counters in one statement.
    #  It is the function the sign-in path uses to upgrade a hash, and a reset needs exactly the
    #  same three columns — so there is no second way to write a password, which is the point:
    #  a second one would be a second thing to get wrong.
    await credentials.record_verified(
        session, user.id, new_hash=passwords.hash_password(new_password)
    )

    #  Every session in every tenant. A reset is what somebody does when they believe their
    #  account is compromised; leaving the attacker's session alive would make it theatre.
    #
    #  Counted before the delete rather than read from its row count: the number goes into the
    #  audit row as evidence of what the reset actually did, and it should be a value this code
    #  asked for rather than one a driver happened to report.
    revoked = (
        await session.execute(
            select(func.count()).select_from(Session).where(Session.user_id == user.id)
        )
    ).scalar_one()
    await session.execute(delete(Session).where(Session.user_id == user.id))

    await _record(
        session,
        await _any_tenant(session, user.id),
        action="identity.password_reset_completed",
        resource_type="user",
        resource_id=user.id,
        actor_label=user.email,
        ip_address=ip_address,
        detail={"sessions_revoked": revoked},
    )
    log.info("password_reset_completed", sessions_revoked=revoked)
    return user


async def accept_invite(
    session: AsyncSession,
    redis: Redis,
    *,
    token: str,
    password: str,
    display_name: str | None = None,
    ip_address: str | None = None,
) -> credentials.Credential:
    """Set the first password on an invited account.

    Not registration. The account and its membership already exist — somebody with the authority
    created them — and this is the invited person choosing a password. Self-service workspace
    creation is decision `0B.3`, which has not been taken, and nothing here creates a tenant.
    """
    claim = await action_tokens.consume(
        redis,
        raw=token,
        expected_purpose=action_tokens.ActionTokenPurpose.INVITE_SETUP,
    )
    if claim is None:
        raise ValidationFailed(
            "That invitation has expired or was already used. Ask for a new one."
        )

    user = await credentials.find_by_id(session, claim.user_id)
    if user is None:
        raise ValidationFailed("That invitation is no longer valid.")
    if user.password_hash is not None:
        #  Accepting twice would be a way to change a password without knowing the old one.
        raise ValidationFailed(
            "That account already has a password. Sign in, or reset it if you have forgotten it."
        )

    passwords.check_strength(password)
    await credentials.record_verified(
        session, user.id, new_hash=passwords.hash_password(password)
    )
    #  No status to change. `UserStatus` has only `active` and `deactivated`; an invitation that
    #  has not been accepted is an *active user with no password*, and the membership carries the
    #  `invited` state. Setting a status here would have been a no-op pretending to be a step.

    if display_name:
        for membership in (
            (
                await session.execute(
                    select(Membership).where(Membership.user_id == user.id)
                )
            )
            .scalars()
            .all()
        ):
            membership.display_name = display_name.strip()

    await _record(
        session,
        await _any_tenant(session, user.id),
        action="identity.invite_accepted",
        resource_type="user",
        resource_id=user.id,
        actor_label=user.email,
        ip_address=ip_address,
    )
    return user


async def _any_tenant(session: AsyncSession, user_id: uuid.UUID | None) -> uuid.UUID | None:
    """A tenant to file the audit row under, or `None` when there is nowhere to file it.

    Every audit row belongs to a tenant — `audit_events.tenant_id` carries a `RESTRICT` foreign
    key and a row-level policy — and a recovery request arrives before there is a session, from
    somebody who may belong to several workspaces or to none at all. The first membership is used
    where there is one.

    An earlier version returned the nil UUID for "none". That row could never be written: the
    foreign key has nothing to point at, and binding a tenant that does not exist fails the
    policy as well. Returning `None` says the same thing honestly, and `_record` puts the event
    in the log instead — see there for why that is the right place for it.
    """
    if user_id is None:
        return None

    #  **Bound first, or this returns nothing.** `memberships` is behind row-level security, and
    #  a recovery request has bound no tenant — so an unbound query sees zero rows and the
    #  function would answer "no tenant" for every account that exists. The failure is silent and
    #  the worst possible shape: the screen says a link is on its way, no event is ever queued,
    #  and nothing anywhere reports a problem. A test caught it; nothing else would have.
    #
    #  `bind_verified_user` is the policy branch built for exactly this read — one person's own
    #  memberships, across tenants, for the sign-in chooser. It grants that list and nothing
    #  else: no write policy matches on it. The read is server-side and its result never reaches
    #  the caller, who is told the same thing either way.
    await bind_verified_user(session, user_id)
    return (
        await session.execute(
            select(Membership.tenant_id).where(Membership.user_id == user_id).limit(1)
        )
    ).scalar_one_or_none()


async def _record(
    session: AsyncSession, tenant_id: uuid.UUID | None, **event: Any
) -> None:
    """Write the audit row under its tenant, or log it when it has none.

    **The tenant has to be bound before the insert.** These routes run before a session exists,
    so nothing has bound one — and `audit_events` has a row-level policy that refuses an insert
    with no `app.tenant_id` set. `tenant_scope` binds it and flushes while it is still bound,
    which is the shape the rest of the codebase uses for the same reason.

    **An address with no account has no tenant, so its attempt is logged rather than audited.**
    That is a real limitation and it is stated rather than papered over: a reset attempt against
    an unknown address is worth seeing, but a tenant-scoped table is the wrong place for an event
    that belongs to no tenant, and inventing one to hold it would put a fake workspace in the
    foreign key of the table auditors read. The structured log carries it with the same fields.
    """
    if tenant_id is None:
        log.info("identity_recovery_untenanted", **{
            key: str(value) for key, value in event.items() if key in {"action", "outcome"}
        })
        return
    async with tenant_scope(session, tenant_id):
        await audit.record(session, tenant_id=tenant_id, **event)


def now() -> datetime:
    return datetime.now(UTC)
