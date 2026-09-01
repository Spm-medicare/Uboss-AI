"""Adding a colleague to the workspace, so the chart can place somebody who is not here yet.

Every piece of an invitation has existed since Gate 2 — `ActionTokenPurpose.INVITE_SETUP`,
`POST /auth/invite/accept`, and a registered publisher for `identity.invite_issued` — and
**nothing issued one**. So a workspace's people were whatever a provisioning script had inserted,
and the org chart could place only somebody already there. Typing a colleague's name into it was a
dead end, which is exactly what it was reported as.

## Why this lives beside the hierarchy

Creating an account is identity's business, and this file is deliberately thin over it: it calls
`auth_create_invited_user` (migration 0040) and the existing token and outbox paths. What it adds
is the *hierarchy's* reason for doing it — somebody drawing a company needs a name in a box before
that person has ever signed in — and the permission that matches: `manage_access`, which is
high-risk and therefore asks for a password.

## What an invited person can and cannot do

They can hold a seat, appear on the chart, and be named as a manager. They cannot sign in until
they accept, and `objectives.people` — *"who may be named as owner or approver"* — leaves them out
until they do, because an owner has to be able to act. Two different questions, two lists; see
`hierarchy.placeable_people`.

## The order, and what a failure leaves behind

Account, then membership, then the invitation. A crash after the membership leaves somebody who is
in the workspace and has had no email — visible, placeable, and re-invitable, which is a state a
person can fix. The other order would send an invitation to somebody the workspace does not have,
and there is nothing to fix that with.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import ValidationFailed
from uboss.core.logging import get_logger
from uboss.core.permissions import Action
from uboss.core.settings import Settings
from uboss.modules.audit import service as audit
from uboss.modules.identity import action_tokens, guard
from uboss.modules.identity.models import Membership
from uboss.modules.tenancy.models import Tenant

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class InvitedPerson:
    """Who was added, and whether the workspace already had them."""

    membership_id: uuid.UUID
    display_name: str
    #: False when this address was already a member — the caller gets the existing person rather
    #: than a duplicate, and can say so instead of claiming to have created somebody.
    created: bool


async def add_person(
    session: AsyncSession,
    context: SecurityContext,
    redis: Redis,
    settings: Settings,
    *,
    display_name: str,
    email: str,
) -> InvitedPerson:
    """Put a colleague in the workspace and send them an invitation.

    `manage_access`, not `administer`: this decides who is *in* the organisation, which is the
    permission §14 names for exactly that. It is high-risk, so the route asks for a password.
    """
    await guard.authorise(session, context, Action.MANAGE_ACCESS)

    name = display_name.strip()
    address = email.strip().lower()
    if not name:
        raise ValidationFailed("Give the person a name.")
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        raise ValidationFailed(f"'{email}' is not an email address.")

    #  The account. Through the definer function, because migration 0006 took `users` away from
    #  the application role and the reason has not changed.
    row = (
        await session.execute(
            text("SELECT id, created FROM auth_create_invited_user(:email)"),
            {"email": address},
        )
    ).one()
    user_id = row.id

    #  Already a member of *this* workspace? Then there is nothing to add, and returning the
    #  existing person is more useful than an error — the caller wanted somebody to place.
    existing = (
        await session.execute(
            select(Membership).where(Membership.user_id == user_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        log.info("invite_person_already_member", membership_id=str(existing.id))
        return InvitedPerson(
            membership_id=existing.id,
            display_name=existing.display_name,
            created=False,
        )

    membership = Membership(
        tenant_id=context.tenant_id,
        user_id=user_id,
        display_name=name,
        #: Invited, not active. They can hold a seat and cannot sign in until they accept — which
        #: is precisely the state an org chart needs during onboarding.
        status="invited",
    )
    session.add(membership)
    await session.flush()

    #  The invitation itself. Queued on the outbox rather than sent here, so it goes if and only
    #  if this transaction commits — the rule §12 states and the one delivery mistake nobody can
    #  undo if it is broken.
    token = await action_tokens.issue(
        redis,
        purpose=action_tokens.ActionTokenPurpose.INVITE_SETUP,
        user_id=user_id,
        tenant_id=context.tenant_id,
        membership_id=membership.id,
        ttl_seconds=settings.invite_token_minutes * 60,
    )
    workspace = await session.get(Tenant, context.tenant_id)
    await audit.publish(
        session,
        tenant_id=context.tenant_id,
        event_type="identity.invite_issued",
        subject_type="membership",
        subject_id=membership.id,
        payload={
            "email": address,
            "workspace_name": workspace.name if workspace is not None else "your workspace",
            "invited_by": context.display_name,
            #  The token is in the payload because that is what the mail body needs. It is
            #  single-use, short-lived and useless without the address it was minted for.
            "invite_url": (
                f"{settings.public_base_url.rstrip('/')}/accept-invite?token={token}"
            ),
            "expires_in_minutes": settings.invite_token_minutes,
        },
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="identity.person_invited",
        resource_type="membership",
        resource_id=membership.id,
        actor=context,
        #  The address is not in the detail. An audit trail records who did what to whom; the
        #  contact detail is in `users`, behind the grant that keeps it there.
        detail={"display_name": name},
    )
    await session.flush()

    log.info("invite_person_created", membership_id=str(membership.id))
    return InvitedPerson(
        membership_id=membership.id, display_name=name, created=True
    )
