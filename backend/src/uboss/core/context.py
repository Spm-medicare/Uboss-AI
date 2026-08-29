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
from uboss.core.permissions import Action, Decision, Grant, decide, effective


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
    #: The role keys this membership holds, for display and for the audit trail. Names only —
    #: what they *permit* is resolved from `role_permissions` into `granted_actions` below,
    #: because PLAN §17 makes roles a table and no role name is defined in code.
    roles: tuple[str, ...]
    #: Resolved once, when the session is verified, from the permissions attached to those roles.
    #: Carried on the context rather than recomputed, so one request cannot answer "may they?"
    #: two different ways.
    granted_actions: frozenset[Action] = frozenset()
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
    #: The configured links of PLAN §14 chain — company and department — resolved when the
    #: session is verified. Empty means no scope has restricted anything, which is not the same
    #: as nothing being allowed.
    policy_grants: tuple[Grant, ...] = field(default=())

    @property
    def actions(self) -> frozenset[Action]:
        """What this caller may actually do anywhere in the tenant.

        Their roles' actions **after** every configured scope has narrowed them. This is what a
        screen should show and what "can they?" means everywhere outside this class.

        It is deliberately not `granted_actions`. That is the baseline — what the roles put on
        the table before company and department policy take things away — and reporting it would
        show a person a `publish` button that every attempt to use would refuse.

        Empty when their roles grant nothing, or when they hold no role at all. That is the
        fail-closed answer, and the honest one while the Gate 0 §0.2 matrix is unapproved: a
        carried-over role with no permission rows grants nothing, visibly, rather than falling
        back to a set someone invented.
        """
        return effective(self.granted_actions, self.grants_for())

    def grants_for(self, resource_grant: Grant | None = None) -> list[Grant]:
        """The narrowing layers for one decision.

        Only restrictions live here. What *grants* is `granted_actions`, resolved from the
        caller's roles — a role is a principal in PLAN §14, not a scope, so it does not belong
        in the chain. An earlier version put it at the department link, which worked only for as
        long as no real department policy existed to collide with it.
        """
        chain = list(self.policy_grants)
        if resource_grant is not None:
            chain.append(resource_grant)
        return chain

    def may(self, action: Action, resource_grant: Grant | None = None) -> bool:
        return self.explain(action, resource_grant).allowed

    def explain(self, action: Action, resource_grant: Grant | None = None) -> Decision:
        """The full answer, including which layer refused.

        For the audit trail and an administrator's screen. The caller who was refused never
        sees it.
        """
        #  The *baseline* goes in, not `actions` — that property has already applied the chain,
        #  and narrowing an already-narrowed set would still be correct but would lose the
        #  ability to say which layer refused.
        return decide(action, self.granted_actions, self.grants_for(resource_grant))

    def require(self, action: Action, resource_grant: Grant | None = None) -> None:
        """Refuse the request unless the action is permitted.

        The message says nothing about *why*, and nothing about the target. A refusal that
        explains itself is a refusal that confirms a record exists. The full reason goes to the
        audit trail, where an administrator can read it.
        """
        if not self.may(action, resource_grant):
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
