"""Managing scope 2 — who may control a Supervisor.

Every rule here is a refusal, and each one closes a way the handler list could otherwise become a
route to more authority than somebody started with:

* **You need `manage_access` in the workspace *and* a role that confers it.** Two independent
  checks, asked by `guard.authorise_handler`.
* **You cannot grant a role above your own.** Otherwise a Manager makes somebody Owner and is then
  removed by them.
* **You cannot change your own role.** The person who benefits is not the person who decides —
  the same separation of duty the publish routes apply.
* **You cannot remove the owner.** They are Owner by virtue of the `owner_membership_id` column,
  not a row, so there is nothing to remove; a request to is refused rather than silently ignored.
* **Handlers are explicit people.** The plan's decision table: *"Department Supervisor handlers |
  Explicit selected people; no automatic department-wide control."* Nothing here reads a
  department.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.identity.models import Membership
from uboss.modules.supervisors import guard
from uboss.modules.supervisors.models import (
    HandlerRole,
    Supervisor,
    SupervisorHandler,
)

#: Past this, nobody reviews a control list properly. The same reasoning as every other ceiling
#: in this codebase.
MAX_HANDLERS = 50


def _now() -> datetime:
    return datetime.now(UTC)


async def list_handlers(
    session: AsyncSession, context: SecurityContext, supervisor_id: uuid.UUID
) -> list[tuple[SupervisorHandler, str | None]]:
    """Who controls this Supervisor, with their names. `view` and a role that confers it."""
    supervisor = await get(session, supervisor_id)
    await guard.authorise_handler(session, context, supervisor, Action.VIEW)

    rows = (
        await session.execute(
            select(SupervisorHandler, Membership.display_name)
            .outerjoin(Membership, Membership.id == SupervisorHandler.membership_id)
            .where(SupervisorHandler.supervisor_id == supervisor_id)
            .order_by(SupervisorHandler.granted_at)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def set_handler(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    membership_id: uuid.UUID,
    role: HandlerRole,
    *,
    expected_version: int,
) -> SupervisorHandler:
    """Add somebody to scope 2, or change the role they already hold."""
    supervisor = await get(session, supervisor_id)
    if supervisor.version != expected_version:
        raise Conflict("Somebody else changed this supervisor. Reload it and try again.")

    holder = await guard.authorise_handler(
        session, context, supervisor, Action.MANAGE_ACCESS
    )
    await guard.refuse_granting_above_your_own_role(
        session,
        context,
        supervisor,
        holder=holder,
        granted=role,
        to_membership_id=membership_id,
    )

    if membership_id == supervisor.owner_membership_id:
        raise ValidationFailed(
            "The owner already holds every handler permission. Reassign the supervisor instead."
        )
    await _require_member(session, membership_id)

    existing = (
        await session.execute(
            select(SupervisorHandler).where(
                SupervisorHandler.supervisor_id == supervisor_id,
                SupervisorHandler.membership_id == membership_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        count = (
            await session.execute(
                select(SupervisorHandler).where(
                    SupervisorHandler.supervisor_id == supervisor_id
                )
            )
        ).scalars()
        if len(list(count)) >= MAX_HANDLERS:
            raise ValidationFailed(
                f"A supervisor may have up to {MAX_HANDLERS} handlers."
            )
        existing = SupervisorHandler(
            tenant_id=context.tenant_id,
            supervisor_id=supervisor_id,
            membership_id=membership_id,
        )
        session.add(existing)

    previous = existing.role if existing.role else None
    existing.role = role
    #  Stamped from the caller and the clock. A grant somebody could attribute elsewhere is not
    #  a record of who decided.
    existing.granted_by_membership_id = context.membership_id
    existing.granted_at = _now()

    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.handler_set",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        detail={
            "membership_id": str(membership_id),
            "role": str(role),
            "previous_role": str(previous) if previous else None,
        },
    )
    return existing


async def remove_handler(
    session: AsyncSession,
    context: SecurityContext,
    supervisor_id: uuid.UUID,
    membership_id: uuid.UUID,
    *,
    expected_version: int,
) -> None:
    """Take somebody out of scope 2.

    Removing yourself is allowed — walking away from a responsibility is not an escalation, and
    refusing it would strand somebody who no longer wants it. Removing the *owner* is not, because
    there is no row to remove and pretending otherwise would report a change that did not happen.
    """
    supervisor = await get(session, supervisor_id)
    if supervisor.version != expected_version:
        raise Conflict("Somebody else changed this supervisor. Reload it and try again.")

    holder = await guard.authorise_handler(
        session, context, supervisor, Action.MANAGE_ACCESS
    )

    if membership_id == supervisor.owner_membership_id:
        raise ValidationFailed(
            "The owner is not a handler row. Reassign the supervisor to change who owns it."
        )

    existing = (
        await session.execute(
            select(SupervisorHandler).where(
                SupervisorHandler.supervisor_id == supervisor_id,
                SupervisorHandler.membership_id == membership_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise NotFound("That person is not a handler on this supervisor.")

    #  You cannot remove somebody who outranks you, for the same reason you cannot promote past
    #  your own role: a Manager removing the Owner is the escalation read backwards.
    if membership_id != context.membership_id:
        await guard.refuse_granting_above_your_own_role(
            session,
            context,
            supervisor,
            holder=holder,
            granted=HandlerRole(existing.role),
            to_membership_id=membership_id,
        )

    await session.delete(existing)
    supervisor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="supervisor.handler_removed",
        resource_type="supervisor",
        resource_id=supervisor.id,
        actor=context,
        detail={"membership_id": str(membership_id), "role": str(existing.role)},
    )


async def get(session: AsyncSession, supervisor_id: uuid.UUID) -> Supervisor:
    supervisor = (
        await session.execute(select(Supervisor).where(Supervisor.id == supervisor_id))
    ).scalar_one_or_none()
    if supervisor is None:
        raise NotFound("No such supervisor.")
    return supervisor


async def _require_member(session: AsyncSession, membership_id: uuid.UUID) -> None:
    member = (
        await session.execute(select(Membership).where(Membership.id == membership_id))
    ).scalar_one_or_none()
    if member is None:
        raise ValidationFailed("That person is not a member of this workspace.")
