"""The one place a Supervisor action is allowed or refused.

Two checks, both required, neither substituting for the other:

1. **The workspace guard** — does this person hold the verb at all, after the company → department
   → resource → action chain has narrowed it? `identity.guard.authorise` answers, and it records
   its own refusal.
2. **The handler role** — does their role on *this* Supervisor allow it? `roles.permits` answers.

The order matters. The workspace check runs first, so somebody who does not hold `run` anywhere is
refused for that reason rather than being told they are not a handler — a message that would have
implied they would be fine if only somebody added them.

**Nothing here grants anything.** §10: *"Claude cannot bypass policy, grant permission, perform
uncontrolled retries or approve high-risk actions."* A role can only ever remove possibilities
from the set the workspace already allowed, which is why `authorise_handler` calls the workspace
guard rather than replacing it.

**A refusal is written down before it is raised**, naming which of the two layers withheld the
action. The caller gets none of that — a refusal that explains itself confirms the Supervisor
exists.
"""

from __future__ import annotations

import uuid
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import PermissionDenied
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.audit.models import AuditOutcome
from uboss.modules.identity import guard as workspace_guard
from uboss.modules.supervisors import roles
from uboss.modules.supervisors.models import (
    HandlerRole,
    Supervisor,
    SupervisorHandler,
)

#: What a refused caller is told, whatever actually happened. One message, because "you are not a
#: handler" and "your role does not go that far" describe an organisation's arrangements to
#: somebody outside them.
REFUSED = "You do not have permission to do this."


async def role_for(
    session: AsyncSession, supervisor: Supervisor, membership_id: uuid.UUID | None
) -> HandlerRole | None:
    """This person's role on this Supervisor, or nothing.

    **The owner is always Owner**, with or without a handler row. Requiring the owner to appear in
    their own handler list would mean a Supervisor could be locked out of by deleting one row, and
    it would make the row the source of truth for something the `owner_membership_id` column
    already says.
    """
    if membership_id is None:
        return None
    if supervisor.owner_membership_id == membership_id:
        return HandlerRole.OWNER

    found = (
        await session.execute(
            select(SupervisorHandler.role).where(
                SupervisorHandler.supervisor_id == supervisor.id,
                SupervisorHandler.membership_id == membership_id,
            )
        )
    ).scalar_one_or_none()
    return HandlerRole(found) if found else None


async def authorise_handler(
    session: AsyncSession,
    context: SecurityContext,
    supervisor: Supervisor,
    action: Action,
    *,
    ip_address: str | None = None,
) -> HandlerRole:
    """Allow the action on this Supervisor, or refuse it and leave a record.

    Returns the caller's role when permitted, because every caller that needs this also needs to
    know what else the person may do — and asking twice invites the two answers to disagree.
    """
    #  The workspace first. It records its own refusal and raises.
    await workspace_guard.authorise(
        session,
        context,
        action,
        resource=workspace_guard.Resource(type="supervisor", id=supervisor.id),
        ip_address=ip_address,
    )

    #  A verb no role can ever confer. Refused for everybody including the Owner, which is what
    #  stops a Supervisor from becoming a route to workspace administration.
    if action not in roles.GOVERNED:
        await _refuse(
            session,
            context,
            supervisor,
            action,
            reason=f"{action} is not an action any handler role confers on a supervisor",
            ip_address=ip_address,
        )

    role = await role_for(session, supervisor, context.membership_id)
    if role is None:
        await _refuse(
            session,
            context,
            supervisor,
            action,
            reason="not a handler on this supervisor",
            ip_address=ip_address,
        )
    if not roles.permits(role, action):
        await _refuse(
            session,
            context,
            supervisor,
            action,
            reason=f"handler role {role} does not permit {action}",
            ip_address=ip_address,
        )
    return role


async def refuse_granting_above_your_own_role(
    session: AsyncSession,
    context: SecurityContext,
    supervisor: Supervisor,
    *,
    holder: HandlerRole,
    granted: HandlerRole,
    to_membership_id: uuid.UUID,
    ip_address: str | None = None,
) -> None:
    """Two refusals that together stop a handler list becoming an escalation path.

    **Nobody grants a role above their own.** Without it a Manager could make somebody Owner and
    then be removed by them — a privilege escalation with two extra steps.

    **Nobody changes their own role.** Separation of duty, the same rule the publish routes apply:
    the person who benefits is not the person who decides.
    """
    if to_membership_id == context.membership_id:
        await _refuse(
            session,
            context,
            supervisor,
            Action.MANAGE_ACCESS,
            reason="a handler cannot change their own role",
            ip_address=ip_address,
        )
    if not roles.outranks_or_equals(holder, granted):
        await _refuse(
            session,
            context,
            supervisor,
            Action.MANAGE_ACCESS,
            reason=f"handler role {holder} cannot grant {granted}",
            ip_address=ip_address,
        )


async def _refuse(
    session: AsyncSession,
    context: SecurityContext,
    supervisor: Supervisor,
    action: Action,
    *,
    reason: str,
    ip_address: str | None,
) -> NoReturn:
    """Write it down, then raise. Never returns — `NoReturn` is what lets the callers above narrow
    without a bare `assert`, which `-O` would strip.

    The audit row is staged in the caller's transaction, which the error handler commits before
    returning the refusal — an audit trail that only records successes cannot show an attack.
    """
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action=f"supervisor.{action}.denied",
        resource_type="supervisor",
        resource_id=supervisor.id,
        outcome=AuditOutcome.DENIED,
        actor=context,
        denial_reason=reason,
        ip_address=ip_address,
        detail={"requested_action": str(action), "supervisor": supervisor.name},
    )
    raise PermissionDenied(REFUSED)
