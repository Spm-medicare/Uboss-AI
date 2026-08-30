"""What each handler role may do, and why it is a ceiling rather than a grant.

`PLAN.md` §10 lists six roles and describes four of them:

> - Viewer
> - Operator: pause/resume and safe retry
> - Reviewer: review output/request changes
> - Approver
> - Manager: manage scope/policy
> - Owner

**This is not a second permission system.** §14's `Action` vocabulary decides what a person may do
in the workspace, and it is closed. A handler role narrows that **further** for one Supervisor; it
never widens it. So the answer to *"may this person pause this Supervisor"* is always the
conjunction of two independent checks — the workspace grant, and the role — and neither substitutes
for the other. That is the same shape as the backend-authorisation-and-RLS rule in CLAUDE.md, for
the same reason: one boundary is one boundary.

## The one reading this file makes, stated plainly

§10 lists the roles in increasing authority and ends with Owner. The natural reading — and the one
taken here — is that the list is **cumulative**: an Approver may do what a Reviewer may, a Manager
what an Approver may, and so on. The alternative, six unrelated sets, would mean an Approver who
cannot read what they are approving, which is not a thing anybody would design.

The mapping of a role onto §14's verbs is a design decision, so each one is derived from §10's own
description and nothing more:

| Role | §10 says | Verbs added |
|---|---|---|
| Viewer | *(named only)* | `view` |
| Operator | *"pause/resume and safe retry"* | `run` |
| Reviewer | *"review output/request changes"* | `comment` |
| Approver | *(named only)* | `approve` |
| Manager | *"manage scope/policy"* | `manage_access`, `schedule`, `assign` |
| Owner | *(named only)* | `edit_draft`, `publish` |

`administer` and `audit` appear nowhere: they are workspace-wide verbs and a Supervisor's Owner is
not a workspace administrator. `export` and `integrate` likewise — §10 gives a Supervisor no
authority over either.
"""

from __future__ import annotations

from uboss.core.permissions import Action
from uboss.modules.supervisors.models import HandlerRole

#: What each role adds to the one before it. The order is §10's, and it is load-bearing.
_ADDS: dict[HandlerRole, frozenset[Action]] = {
    HandlerRole.VIEWER: frozenset({Action.VIEW}),
    HandlerRole.OPERATOR: frozenset({Action.RUN}),
    HandlerRole.REVIEWER: frozenset({Action.COMMENT}),
    HandlerRole.APPROVER: frozenset({Action.APPROVE}),
    HandlerRole.MANAGER: frozenset({Action.MANAGE_ACCESS, Action.SCHEDULE, Action.ASSIGN}),
    HandlerRole.OWNER: frozenset({Action.EDIT_DRAFT, Action.PUBLISH}),
}

#: The roles in §10's order — increasing authority.
ORDER: tuple[HandlerRole, ...] = tuple(_ADDS)


def _cumulative() -> dict[HandlerRole, frozenset[Action]]:
    """Each role's full set: its own verbs plus every role below it."""
    running: set[Action] = set()
    built: dict[HandlerRole, frozenset[Action]] = {}
    for role in ORDER:
        running |= _ADDS[role]
        built[role] = frozenset(running)
    return built


#: Role → every verb it permits on its Supervisor. Computed once; never mutated.
PERMITS: dict[HandlerRole, frozenset[Action]] = _cumulative()

#: The verbs a handler role can ever confer. Anything outside this set is refused for every role,
#: which is what stops a Supervisor from becoming a route to workspace administration.
GOVERNED: frozenset[Action] = PERMITS[HandlerRole.OWNER]


def rank(role: HandlerRole) -> int:
    """Where a role sits in §10's order. Used to refuse granting above your own."""
    return ORDER.index(role)


def permits(role: HandlerRole, action: Action) -> bool:
    """Whether this role allows the action **on its own Supervisor**.

    Says nothing about whether the person holds the action in the workspace. That is a separate
    question with a separate answer, and `guard.authorise_handler` asks both.
    """
    return action in PERMITS[role]


def outranks_or_equals(holder: HandlerRole, granted: HandlerRole) -> bool:
    """Whether `holder` may hand out `granted`.

    Nobody grants a role above their own. Without this, a Manager could make somebody Owner and
    then be removed by them — which is a privilege escalation with two extra steps.
    """
    return rank(holder) >= rank(granted)
