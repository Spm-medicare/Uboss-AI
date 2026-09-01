"""Who a human step goes to — §8's WHO rules, resolved once when the task is created.

## Resolved once, and that is the design

The rule is evaluated when the task is made and the answer is written into
`tasks.assignee_membership_id`. It is never re-evaluated. Somebody who moves department does not
silently lose work already given to them; the task is theirs until a person reassigns it, and that
reassignment is a decision with an actor rather than a side effect of an org change somebody made
for another reason.

The alternative — resolving on every read — has a worse failure: two people open the same To-do
list on either side of a transfer and see different work, with nothing recorded about why.

## `unresolved` is an answer

A rule can match nobody: a role with no holder, a position that is vacant, a department that was
archived. The task is created **unassigned** and says so. It appears in the run, in the Job's
list of waiting work, and to anybody who may reassign it. It does not appear in somebody's To-do
list, because it is not theirs — and inventing an assignee to avoid an empty state would put the
work on a person nobody chose.

## What is not resolved here

`dynamic_group` names a condition rather than a row, and there is nothing yet that evaluates a
condition — §8 defines the type, and the Job Builder stores the description a person wrote. It
resolves to nobody, with `assigned_via = 'dynamic_group'` recorded so the reason is visible on the
task rather than inferred from an empty field.

`all_must_act` is likewise carried and not yet honoured: one task goes to the first match. Several
tasks for one step is a shape `uq_tasks_one_open_per_step` deliberately refuses, and widening it
belongs with the approval rules in 7.3 rather than as a quiet exception here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.logging import get_logger
from uboss.modules.hierarchy.models import OrgUnit, Position, PositionAssignment
from uboss.modules.identity.models import Membership, MembershipRole, MembershipStatus, Role

log = get_logger(__name__)

#: When a rule matches nobody. A value rather than a null, so the task can say *why* it is
#: unassigned instead of only that it is.
UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class Assignee:
    """Who the step goes to, and which rule said so."""

    membership_id: uuid.UUID | None
    #: One of §8's `who_type` values, or `unresolved`.
    via: str


async def resolve(
    session: AsyncSession, rules: list[dict[str, object]], *, position: int
) -> Assignee:
    """The person a step's WHO rules point at.

    Rules are tried in their own order and the first that resolves to somebody wins. Order is the
    author's: §8 lets a Job carry several rules with a `condition_note` on each, and the order
    they were written in is the only expression of precedence the form offers.

    `rules` comes from the version's frozen snapshot, so this reads plain dictionaries rather than
    the `JobAssignmentRule` rows — the rows may have changed since the version was published, and
    the version is what the run executes.
    """
    for rule in rules:
        who_type = str(rule.get("who_type") or "")
        target = rule.get("target_id")
        target_id = uuid.UUID(str(target)) if target else None

        found = await _resolve_one(session, who_type, target_id)
        if found is not None:
            return Assignee(membership_id=found, via=who_type)

    #  Nothing matched. Recorded as such rather than guessed at.
    log.info("task_unassigned", position=position, rules=len(rules))
    return Assignee(membership_id=None, via=UNRESOLVED)


async def _resolve_one(
    session: AsyncSession, who_type: str, target_id: uuid.UUID | None
) -> uuid.UUID | None:
    """One rule, or `None` when it matches nobody.

    Every branch returns an **active** membership. A task assigned to somebody who has left is a
    task nobody will do, and it is better to fall through to the next rule — or to unassigned —
    than to give work to a deactivated account.
    """
    if who_type == "user":
        #  Already a membership. Checked rather than trusted: the version froze the id, and the
        #  person may have left since.
        if target_id is None:
            return None
        return await _if_active(session, target_id)

    if who_type == "role":
        if target_id is None:
            return None
        #  The first active holder of the role. `order_by` on the id rather than nothing at all:
        #  an arbitrary-but-stable choice is better than one that changes between reads.
        return (
            await session.execute(
                select(Membership.id)
                .join(MembershipRole, MembershipRole.membership_id == Membership.id)
                .join(Role, Role.id == MembershipRole.role_id)
                .where(
                    Role.id == target_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
                .order_by(Membership.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    if who_type == "hierarchy_position":
        if target_id is None:
            return None
        #  Whoever currently holds the seat. A vacant seat resolves to nobody, which is the
        #  honest answer — and exactly the state the org chart draws as Vacant.
        return (
            await session.execute(
                select(PositionAssignment.membership_id)
                .join(Position, Position.id == PositionAssignment.position_id)
                .where(
                    Position.id == target_id,
                    PositionAssignment.effective_to.is_(None),
                    Position.archived_at.is_(None),
                )
                .order_by(PositionAssignment.effective_from.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if who_type in {"department", "hierarchy_subtree"}:
        if target_id is None:
            return None
        #  The most senior person in the unit — `level` ascending, because 1 is the most senior.
        #  A department's work goes to whoever runs it unless a rule said otherwise, which is
        #  what a reader of the form expects "Department: Finance" to mean.
        return (
            await session.execute(
                select(PositionAssignment.membership_id)
                .join(Position, Position.id == PositionAssignment.position_id)
                .join(OrgUnit, OrgUnit.id == Position.org_unit_id)
                .where(
                    OrgUnit.id == target_id,
                    PositionAssignment.effective_to.is_(None),
                    Position.archived_at.is_(None),
                )
                .order_by(Position.level.asc().nulls_last(), Position.title)
                .limit(1)
            )
        ).scalar_one_or_none()

    if who_type in {"team", "dynamic_group"}:
        #  `team` has no table yet and `dynamic_group` names a condition nothing evaluates. Both
        #  resolve to nobody *and say which rule it was*, so the task carries the reason.
        return None

    return None


async def _if_active(session: AsyncSession, membership_id: uuid.UUID) -> uuid.UUID | None:
    return (
        await session.execute(
            select(Membership.id).where(
                Membership.id == membership_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()


async def is_active(
    session: AsyncSession, membership_id: uuid.UUID, *, tenant_id: uuid.UUID
) -> bool:
    """Whether somebody in **this workspace** can be given work.

    Public because reassignment, delegation and escalation need the same answer this module
    already computes for every rule: work handed to a deactivated account is work nobody will do.

    `tenant_id` is compared explicitly rather than left to row-level security, and the reason is
    concrete. RLS does not apply to the table's owner unless the table is `FORCE`d, so a caller
    connected as an owning role — a migration, a script, a test — sees every workspace's
    memberships and would happily accept an id from another one. It would be written without
    complaint, because these columns are plain UUIDs with no foreign key, and would then resolve
    to no name on every screen that read it: work addressed to somebody who does not exist here.

    This is defence in depth rather than a replacement. The policy still refuses another
    workspace's row for the application role; this makes the answer independent of which role
    happens to be connected.
    """
    return (
        await session.execute(
            select(Membership.id).where(
                Membership.id == membership_id,
                Membership.tenant_id == tenant_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none() is not None
