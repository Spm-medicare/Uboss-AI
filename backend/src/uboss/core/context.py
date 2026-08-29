"""Who is calling, and what they are allowed to reach.

Everything a request is permitted to do is derived from the verified session token and nothing
else. Not from a request body, not from a query parameter, not from the `Host` header — all three
are attacker-controlled, and each has been the root of a real multi-tenant breach somewhere.

`SecurityContext` is built once per request, immediately after the token is verified, and is then
the single thing services ask. A service that needs the tenant takes it from here; there is no
second path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from uboss.core.errors import PermissionDenied
from uboss.core.permissions import Action, Grant, Scope, actions_for_roles, decide


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """The verified caller.

    Frozen: nothing downstream may widen a caller's reach mid-request. A service that wants a
    narrower view builds a new context rather than mutating this one.
    """

    tenant_id: UUID
    user_id: UUID
    #: The membership, not the user. The same person in two tenants is two memberships with
    #: different roles, and the roles below always belong to *this* tenant.
    membership_id: UUID
    session_id: UUID
    email: str
    display_name: str
    roles: tuple[str, ...]
    #: The hierarchy node this person sits at. Reporting scope is derived from it, so a person
    #: sees their own subtree and no more.
    org_node_id: UUID | None = None
    #: True when the session was established with a second factor. Step-up actions check this
    #: rather than re-asking, so a session that never proved a second factor cannot publish.
    step_up_at: datetime | None = None
    #: Calculated from the server policy when the session is resolved. Storing the expiry in the
    #: verified context makes every high-risk route use the same window and prevents the browser
    #: from choosing how long its proof remains valid.
    step_up_expires_at: datetime | None = None
    is_service_account: bool = False
    #: Policy layers above the role, resolved when the context is built. Empty means nothing
    #: above the role narrowed anything — not that everything is allowed.
    policy_grants: tuple[Grant, ...] = field(default=())

    @property
    def actions(self) -> frozenset[Action]:
        """What this caller may do anywhere in the tenant, before resource-level checks."""
        return actions_for_roles(list(self.roles))

    def grants_for(self, resource_grant: Grant | None = None) -> list[Grant]:
        """Assemble the ceiling chain for one decision.

        Two different things are happening in this chain, and keeping them apart is what makes
        the ceiling correct:

        * **Roles grant.** Everything this person may do comes from the roles their organisation
          gave them. If no role grants an action, nothing else can hand it to them.
        * **Scope policies narrow.** A company or department policy is a *restriction* — it can
          take an action away from every role beneath it. A scope with no policy configured has
          not restricted anything, so it is simply absent from the chain rather than
          contributing an empty set.

        That distinction is why a brand-new tenant works: nobody has written a company policy
        yet, so nothing is narrowed, and a manager's role still grants what a manager's role
        grants. Failing closed applies to a *missing grant*, which is refused. It does not mean
        treating an unwritten optional restriction as a total prohibition — that would make an
        unconfigured system indistinguishable from a locked-out one.
        """
        chain: list[Grant] = [
            grant for grant in self.policy_grants if grant.scope is not Scope.DEPARTMENT
        ]
        chain.append(Grant(scope=Scope.DEPARTMENT, actions=self.actions, source="role"))
        if resource_grant is not None:
            chain.append(resource_grant)
        return chain

    def may(self, action: Action, resource_grant: Grant | None = None) -> bool:
        return decide(action, self.grants_for(resource_grant)).allowed

    def require(self, action: Action, resource_grant: Grant | None = None) -> None:
        """Refuse the request unless the action is permitted.

        The message says nothing about *why*, and nothing about the target. A refusal that
        explains itself is a refusal that confirms a record exists. The full reason goes to the
        audit trail, where an administrator can read it.
        """
        decision = decide(action, self.grants_for(resource_grant))
        if not decision.allowed:
            raise PermissionDenied("You do not have permission to do this.")

    def has_stepped_up(self, now: datetime | None = None) -> bool:
        """Whether recent re-authentication still covers this request."""
        checked_at = now or datetime.now(UTC)
        return (
            self.step_up_at is not None
            and self.step_up_expires_at is not None
            and checked_at < self.step_up_expires_at
        )


@dataclass(frozen=True, slots=True)
class AnonymousContext:
    """Present on the routes that run before sign-in.

    A distinct type rather than `None`, so a service that forgets to require authentication
    fails at the type level instead of silently treating "no caller" as "any caller".
    """

    tenant_id: None = None
    user_id: None = None
