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


def effective(baseline: frozenset[Action], grants: list[Grant]) -> frozenset[Action]:
    """What a caller may do: what their roles grant, narrowed by every configured scope.

    Two different things, kept apart because conflating them is how a ceiling gets breached:

    * **`baseline` grants.** The union of the actions the caller's roles hold. A role is a
      *principal* in PLAN §14, not a scope — it is what puts an action on the table at all.
      Nothing below can add to it.
    * **`grants` narrow.** Each is one link of PLAN §14's chain — company, department, resource,
      action — holding what that link permits. Intersected, so a link can only take away.

    Intersection is the whole point. A union would let a resource grant re-add something company
    policy removed, which is precisely the escalation the ceiling exists to prevent.

    A scope that supplied no grant is **skipped**, not treated as empty: a company that has
    written no policy has not taken anything away. An empty baseline still returns nothing, so a
    caller with no roles is refused everything — that is where failing closed applies.
    """
    by_scope = {grant.scope: grant for grant in grants}
    allowed = baseline
    for scope in CEILING_ORDER:
        grant = by_scope.get(scope)
        if grant is None:
            # This layer has restricted nothing.
            continue
        allowed &= grant.actions
    return allowed


def decide(action: Action, baseline: frozenset[Action], grants: list[Grant]) -> Decision:
    """Resolve one action, and say exactly where it stopped.

    Walks the layers in order so the *first* one that withholds the action is named. That is the
    layer an administrator has to change; naming a later one sends them to the wrong screen.

    The reason is written for an administrator and for the audit trail. It is never returned to
    the caller who was refused — "the department blocked this" confirms the resource exists.
    """
    if action not in baseline:
        return Decision(
            allowed=False,
            action=action,
            reason=f"no role held by this principal grants {action}",
        )

    running = baseline
    for scope in CEILING_ORDER:
        grant = next((g for g in grants if g.scope is scope), None)
        if grant is None:
            continue
        running &= grant.actions
        if action not in running:
            layer = grant.source or "policy"
            return Decision(
                allowed=False,
                action=action,
                blocked_at=scope,
                reason=f"{action} is withheld by {scope} policy ({layer})",
            )
    return Decision(allowed=True, action=action)


# --------------------------------------------------------------------------------------------
# Roles are data, not code.
#
# PLAN §17 lists the Identity domain as "tenants, users, memberships, teams, **roles**,
# **permissions**, resource grants, sessions, guests and service accounts". Roles are a table.
#
# An earlier version of this file held a `ROLE_MATRIX` dictionary naming six roles — viewer,
# contributor, builder, approver, manager, admin — that appear nowhere in PLAN. They were invented
# while implementing, and a role name invented in code becomes a role name in a CHECK constraint,
# then in an API response, then in a screen, and by then changing it is a migration nobody wants
# to run.
#
# The approved matrix is PLAN §25 first implementation deliverable #2 and does not exist yet.
# When it is approved it is seeded as rows, which is a data change. Nothing below needs editing.
#
# The thirteen actions above stay in code, because unlike the role names they *are* in the
# approved specification (PLAN §14). An action the code does not know is a permission bug; a role
# the code does not know is simply a tenant's own configuration.


def actions_from_rows(rows: list[tuple[str, bool]]) -> frozenset[Action]:
    """Resolve one person's permitted actions from their role rows.

    `rows` is `(action, is_conditional)` for every permission on every role the person holds,
    read from `role_permissions`.

    Union across the rows, because one person may hold several roles and holding both a builder
    role and an approver role should give both sets. Union here and intersection in
    `effective()` are deliberately different operations: a person's own roles add up, while the
    company → department → resource chain may only narrow.

    A **conditional** permission is skipped. `ACCESS_MODEL.md` marks these `C`: allowed only
    with an explicit resource or scope grant, which the resource layer supplies through
    `decide()`. Treating one as an unconditional grant here would hand out tenant-wide access
    that the matrix says is scope-limited — the escalation the ceiling exists to prevent.

    An action name the enum does not recognise is ignored rather than guessed at. The database
    constrains the column to the thirteen, so this only fires if the two ever disagree, and
    ignoring is the fail-closed answer.
    """
    permitted: set[Action] = set()
    for action_name, is_conditional in rows:
        if is_conditional:
            continue
        try:
            permitted.add(Action(action_name))
        except ValueError:
            continue
    return frozenset(permitted)


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
