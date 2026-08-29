"""What a caller is allowed to do, and the ceiling that caps it.

PLAN section 14 defines a chain, not a flat list:

    Company policy
      -> Department / workspace policy
        -> Objective / Job / Agent / Supervisor permission
          -> Individual action permission

and one rule that makes the chain mean something: **a lower scope can never grant more power
than the scope above it.** A department cannot hand out a permission the company withheld, and a
grant on a single Agent cannot exceed what its department allows. `effective()` below is the only
place that resolution happens, so there is one answer to "may they?" rather than one per screen.

Two further rules this module exists to hold:

* **Fail closed.** An unknown action, a missing grant, an unreadable policy — all resolve to
  refused. `Decision.allowed` is False unless something positively said yes.
* **The UI is not a check.** Menu visibility is role-based (PLAN line 94) but every route
  re-checks here. A hidden button is a courtesy; this is the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Action(StrEnum):
    """The verbs from PLAN section 14. This list is closed on purpose.

    A feature that needs a new verb adds it here and to the role matrix in the same change, so
    there is never an action the permission matrix has not considered.
    """

    VIEW = "view"
    COMMENT = "comment"
    EDIT_DRAFT = "edit_draft"
    PUBLISH = "publish"
    RUN = "run"
    APPROVE = "approve"
    ASSIGN = "assign"
    SCHEDULE = "schedule"
    MANAGE_ACCESS = "manage_access"
    EXPORT = "export"
    INTEGRATE = "integrate"
    ADMINISTER = "administer"
    AUDIT = "audit"


class PrincipalKind(StrEnum):
    """Who a permission can be granted to (PLAN section 14)."""

    USER = "user"
    TEAM = "team"
    ROLE = "role"
    GUEST = "guest"
    SERVICE_ACCOUNT = "service_account"


class Scope(StrEnum):
    """The levels of the ceiling, ordered widest first."""

    COMPANY = "company"
    DEPARTMENT = "department"
    RESOURCE = "resource"
    ACTION = "action"


#: The order the ceiling is applied in. Narrowing only.
CEILING_ORDER: tuple[Scope, ...] = (
    Scope.COMPANY,
    Scope.DEPARTMENT,
    Scope.RESOURCE,
    Scope.ACTION,
)


@dataclass(frozen=True, slots=True)
class Grant:
    """One layer's answer: the set of actions permitted at that scope."""

    scope: Scope
    actions: frozenset[Action]
    #: Recorded so a refusal can be explained to an administrator without guesswork.
    source: str = ""


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    action: Action
    #: When refused, the scope that withheld it. This is for an admin screen and the audit
    #: record — it is never returned to the refused caller, because "the department blocked
    #: this" confirms the resource exists.
    blocked_at: Scope | None = None
    reason: str = ""


def effective(grants: list[Grant]) -> frozenset[Action]:
    """Intersect the chain, widest scope first.

    Intersection — not union — is the whole point. A union would let a resource-level grant
    re-add something company policy removed, which is exactly the escalation PLAN section 14
    forbids.

    A scope that supplied no grant is skipped rather than treated as an empty set. A policy is a
    *restriction*: a company that has not written one has not taken anything away. What actually
    grants an action is the caller's role, which reaches this chain as the department layer —
    see `SecurityContext.grants_for`. An empty list still returns nothing, so a caller with no
    roles at all is refused.
    """
    by_scope = {grant.scope: grant for grant in grants}
    allowed: frozenset[Action] | None = None
    for scope in CEILING_ORDER:
        grant = by_scope.get(scope)
        if grant is None:
            # A layer that said nothing has not granted anything. Fail closed.
            continue
        allowed = grant.actions if allowed is None else allowed & grant.actions
    return allowed or frozenset()


def decide(action: Action, grants: list[Grant]) -> Decision:
    """Resolve one action against the chain and say where it stopped.

    Walks the layers in order so the *first* one that withholds the action is named. That is the
    layer an administrator has to change, and naming a later one would send them to the wrong
    screen.
    """
    running: frozenset[Action] | None = None
    for scope in CEILING_ORDER:
        grant = next((g for g in grants if g.scope is scope), None)
        if grant is None:
            continue
        running = grant.actions if running is None else running & grant.actions
        if action not in running:
            layer = grant.source or "policy"
            return Decision(
                allowed=False,
                action=action,
                blocked_at=scope,
                reason=f"{action} is not permitted by {scope} policy ({layer})",
            )
    if running is None:
        return Decision(
            allowed=False,
            action=action,
            reason="no policy applies to this principal, so nothing is permitted",
        )
    return Decision(allowed=True, action=action)


# --------------------------------------------------------------------------------------------
# The built-in role matrix.
#
# These are the defaults a tenant starts with. A tenant may narrow them; nothing may widen a role
# beyond what company policy allows, because `effective()` intersects rather than unions.
# --------------------------------------------------------------------------------------------

VIEWER: frozenset[Action] = frozenset({Action.VIEW})

CONTRIBUTOR: frozenset[Action] = VIEWER | {Action.COMMENT, Action.RUN}

BUILDER: frozenset[Action] = CONTRIBUTOR | {
    Action.EDIT_DRAFT,
    Action.ASSIGN,
    Action.SCHEDULE,
    Action.EXPORT,
}
#  A Builder designs but does not release. Publishing is a separate verb held by an approver, so
#  that no single person can both write a version and put it into operation.

APPROVER: frozenset[Action] = CONTRIBUTOR | {Action.APPROVE, Action.PUBLISH}

MANAGER: frozenset[Action] = BUILDER | APPROVER | {Action.MANAGE_ACCESS}

ADMIN: frozenset[Action] = MANAGER | {
    Action.ADMINISTER,
    Action.INTEGRATE,
    Action.AUDIT,
}

ROLE_MATRIX: dict[str, frozenset[Action]] = {
    "viewer": VIEWER,
    "contributor": CONTRIBUTOR,
    "builder": BUILDER,
    "approver": APPROVER,
    "manager": MANAGER,
    "admin": ADMIN,
}


def actions_for_roles(role_names: list[str]) -> frozenset[Action]:
    """Union across the roles one person holds — a person may hold several.

    Union is correct here and intersection is correct in `effective()`, and the difference
    matters: holding both `builder` and `approver` should give you both sets, while the company
    → department → resource chain must only ever narrow. An unknown role name contributes
    nothing rather than everything.
    """
    result: frozenset[Action] = frozenset()
    for name in role_names:
        result |= ROLE_MATRIX.get(name, frozenset())
    return result


@dataclass(frozen=True, slots=True)
class SelfApprovalRule:
    """A person may not approve their own work.

    Held here rather than in each screen because it is a governance rule, not a UI courtesy: the
    same check has to apply to an API call, a workflow step and a Copilot proposal.
    """

    submitted_by: str
    approver: str

    @property
    def is_self_approval(self) -> bool:
        return bool(self.submitted_by) and self.submitted_by == self.approver


HIGH_RISK_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.PUBLISH,
        Action.MANAGE_ACCESS,
        Action.INTEGRATE,
        Action.ADMINISTER,
    }
)
#  PLAN line 366: risky settings require an impact summary, step-up authentication and audit.
#  Listed here so the route layer can ask one question rather than each screen deciding.


AI_FORBIDDEN_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.PUBLISH,
        Action.APPROVE,
        Action.MANAGE_ACCESS,
        Action.ADMINISTER,
    }
)
#  PLAN line 300: "Claude cannot bypass policy, grant permission, perform uncontrolled retries or
#  approve high-risk actions." A proposal may be drafted for a person; it is never executed by
#  the model on their behalf.
