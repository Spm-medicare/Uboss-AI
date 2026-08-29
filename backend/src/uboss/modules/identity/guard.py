"""The one place a request is allowed or refused.

Every route asks this and nothing else. One path means one answer: a check written into a screen,
a service and a workflow separately is three checks that will eventually disagree, and the one
that disagrees quietly is the one that lets something through.

Four things happen here, in this order, and the order matters:

1. **The resource layer is resolved**, if the action names an object.
2. **The chain decides** — the caller's roles narrowed by company, department and resource.
3. **High-risk actions need a live step-up.** Holding the permission is not enough for the small
   set of actions that change who can do what.
4. **A refusal is recorded before it is raised**, naming the layer that caused it. The caller
   gets none of that — a refusal that explains itself confirms the resource exists.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import PermissionDenied
from uboss.core.permissions import HIGH_RISK_ACTIONS, Action, SelfApprovalRule
from uboss.modules.audit import service as audit
from uboss.modules.audit.models import AuditOutcome
from uboss.modules.identity import policies

#: What a refused caller is told, whatever actually happened. One message, because "you lack
#: `publish`" and "your company withheld `publish` on this object" are different sentences that
#: together describe an organisation's policy to someone outside it.
REFUSED = "You do not have permission to do this."

#: What someone is told when they hold the permission but have not proved their password
#: recently. Distinct from a refusal on purpose — it is not a denial, it is a prompt, and telling
#: them to re-enter their password is the only way they can proceed.
STEP_UP_REQUIRED = (
    "Confirm your password to continue. This action changes who can do what, so it needs a "
    "recent sign-in."
)


class StepUpRequired(PermissionDenied):
    """Permitted, but the session has not proved a password recently enough.

    A subclass of `PermissionDenied` so a route that forgets to handle it still fails closed,
    with its own code so the interface can offer the password prompt rather than a dead end.
    """

    code = "step_up_required"

    def __init__(self) -> None:
        super().__init__(STEP_UP_REQUIRED)


@dataclass(frozen=True, slots=True)
class Resource:
    """The object an action is aimed at.

    Absent for a tenant-wide action — "may they create an objective at all" has no object yet.
    """

    type: str
    id: uuid.UUID


async def authorise(
    session: AsyncSession,
    context: SecurityContext,
    action: Action,
    *,
    resource: Resource | None = None,
    ip_address: str | None = None,
) -> None:
    """Allow the request, or refuse it and leave a record.

    Raises `PermissionDenied` when refused and `StepUpRequired` when the permission is held but
    the password has not been proved recently. Returns None when the request may proceed.

    The audit row is **staged, not committed** — it goes into the caller's transaction, which the
    error handler commits before returning the refusal. An audit trail that only records
    successes is an audit trail that cannot show an attack.
    """
    resource_grant = None
    if resource is not None:
        resource_grant = await policies.grant_for_resource(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            resource_type=resource.type,
            resource_id=resource.id,
            role_actions=context.granted_actions,
        )

    decision = context.explain(action, resource_grant)

    if not decision.allowed:
        await _record_denial(
            session,
            context,
            action,
            resource=resource,
            reason=decision.reason,
            ip_address=ip_address,
        )
        raise PermissionDenied(REFUSED)

    #  Held, but not necessarily now. PLAN line 366: risky settings require step-up
    #  authentication. Checked after the permission so that someone who does not hold the action
    #  is refused outright rather than invited to re-enter their password for nothing.
    if action in HIGH_RISK_ACTIONS and not context.has_stepped_up():
        await _record_denial(
            session,
            context,
            action,
            resource=resource,
            reason="permitted, but no password proof within the step-up window",
            ip_address=ip_address,
        )
        raise StepUpRequired()


async def refuse_self_approval(
    session: AsyncSession,
    context: SecurityContext,
    *,
    submitted_by_membership_id: uuid.UUID,
    resource: Resource,
    ip_address: str | None = None,
) -> None:
    """A person may not approve their own work.

    PLAN §14 separates the author from the approver, and the whole point of an approval is that
    a second person looked. Someone who can both write a version and release it is a single
    point of failure and a single point of fraud.

    Held here rather than in each screen because it has to apply identically to an API call, a
    workflow step and a Copilot proposal.
    """
    rule = SelfApprovalRule(
        submitted_by=str(submitted_by_membership_id),
        approver=str(context.membership_id),
    )
    if not rule.is_self_approval:
        return

    await _record_denial(
        session,
        context,
        Action.APPROVE,
        resource=resource,
        reason="separation of duty: the author of a change cannot approve it",
        ip_address=ip_address,
    )
    #  This one *does* say why. The caller already knows the record exists — they wrote it — so
    #  there is nothing left to protect, and silence would just leave them clicking a button that
    #  never works.
    raise PermissionDenied(
        "You submitted this, so someone else has to approve it."
    )


async def _record_denial(
    session: AsyncSession,
    context: SecurityContext,
    action: Action,
    *,
    resource: Resource | None,
    reason: str,
    ip_address: str | None,
) -> None:
    """Write the refusal down, with the detail the caller does not get.

    `denial_reason` names the layer that withheld the action, for an administrator looking at why
    someone cannot do their job. It is never returned in a response.
    """
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action=f"access.{action}.denied",
        resource_type=resource.type if resource else "tenant",
        resource_id=resource.id if resource else None,
        outcome=AuditOutcome.DENIED,
        actor=context,
        denial_reason=reason,
        ip_address=ip_address,
        detail={"requested_action": str(action)},
    )
