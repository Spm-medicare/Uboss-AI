"""Reading and changing the company tree.

Every mutation here does the same four things, in the same order, and none of them is optional:

1. **Authorise** through `identity.guard` — the one place a request is allowed or refused.
2. **Match the version** the caller read. A change that does not match is a `Conflict`, never a
   silent overwrite of whatever the other person just saved.
3. **Write a revision** in the same transaction, holding the before and after state. That is what
   makes PLAN §5's undo possible without a second system.
4. **Write an audit event**, also in the same transaction. If the change commits, the evidence
   commits with it; if it rolls back, so does the claim that it happened.

**Which permission covers what.** PLAN §14 fixes the vocabulary and this module invents nothing:

* Reading the tree is `view`.
* Changing its *shape* — creating, renaming, moving or archiving a unit or a position, and
  drawing a reporting line — is `administer`. Structure decides reporting scope, and reporting
  scope decides who can see and approve what, so it is a permission change wearing a different
  hat. `administer` is high-risk, so it needs a recent password proof; that is once per step-up
  window, not once per rename.
* Putting a person into a seat, or taking them out, is `assign` — literally the verb PLAN uses,
  and deliberately not high-risk, because it happens every time somebody joins or moves.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Select, and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.hierarchy.models import (
    OrgRevision,
    OrgUnit,
    Position,
    PositionAssignment,
    ReportingEdge,
    ReportingKind,
)
from uboss.modules.hierarchy.schemas import (
    AssignmentCreate,
    AssignmentEnd,
    OrgUnitCreate,
    OrgUnitMove,
    OrgUnitRead,
    OrgUnitUpdate,
    PersonInSeat,
    PlaceablePerson,
    PositionCreate,
    PositionRead,
    PositionUpdate,
    ReportingEdgeCreate,
    RevisionPage,
    RevisionRead,
    TreeRead,
    ValidationIssue,
)
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership

#: What `undo` knows how to reverse. Anything else is reported as `can_undo: false` rather than
#: attempted — an undo that half-works is worse than one that declines.
UNDOABLE: frozenset[str] = frozenset(
    {
        "unit.created",
        "unit.updated",
        "unit.moved",
        "unit.archived",
        "unit.restored",
        "position.created",
        "position.updated",
        "position.archived",
        "position.restored",
        "assignment.created",
        "assignment.ended",
        "reporting.created",
        "reporting.ended",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


def _effective_on(as_at: date) -> Any:
    """Rows whose date range covers `as_at`. `effective_to` is exclusive."""
    return and_(
        text("effective_from <= :as_at").bindparams(as_at=as_at),
        or_(
            text("effective_to IS NULL"),
            text("effective_to > :as_at").bindparams(as_at=as_at),
        ),
    )


# ------------------------------------------------------------------------------- reading


async def read_tree(
    session: AsyncSession,
    context: SecurityContext,
    *,
    as_at: date | None = None,
    include_archived: bool = False,
) -> TreeRead:
    """The whole tree as at one date.

    One date for the entire response, so it is a consistent picture rather than a mixture of
    "now" for one department and "then" for another. Somebody looking at next month's structure
    needs every part of it to agree.
    """
    await guard.authorise(session, context, Action.VIEW)
    on = as_at or _now().date()

    units = list(
        (
            await session.execute(
                _visible(select(OrgUnit), include_archived, OrgUnit).order_by(OrgUnit.name)
            )
        )
        .scalars()
        .all()
    )
    positions = list(
        (
            await session.execute(
                _visible(select(Position), include_archived, Position).order_by(Position.title)
            )
        )
        .scalars()
        .all()
    )

    holders = await _holders_on(session, on)
    primary, dotted = await _reporting_on(session, on)

    by_unit: dict[uuid.UUID, list[PositionRead]] = {}
    for position in positions:
        by_unit.setdefault(position.org_unit_id, []).append(
            PositionRead(
                id=position.id,
                org_unit_id=position.org_unit_id,
                title=position.title,
                designation=position.designation,
                level=position.level,
                location=position.location,
                external_ref=position.external_ref,
                archived_at=position.archived_at,
                version=position.version,
                holder=holders.get(position.id),
                reports_to_position_id=primary.get(position.id),
                dotted_line_position_ids=dotted.get(position.id, []),
            )
        )

    return TreeRead(
        as_at=on,
        units=[
            OrgUnitRead(
                id=unit.id,
                parent_id=unit.parent_id,
                name=unit.name,
                unit_type=unit.unit_type,
                external_ref=unit.external_ref,
                location=unit.location,
                archived_at=unit.archived_at,
                version=unit.version,
                positions=by_unit.get(unit.id, []),
            )
            for unit in units
        ],
        is_empty=not units,
    )


def _visible(
    statement: Select[Any], include_archived: bool, model: type[OrgUnit] | type[Position]
) -> Select[Any]:
    """Archived rows are hidden unless asked for.

    Hidden, never deleted. An archived department is the context for every run recorded against
    it, and PLAN §30 is explicit: *"Archive without silently erasing audit evidence."*
    """
    if include_archived:
        return statement
    return statement.where(model.archived_at.is_(None))


async def placeable_people(
    session: AsyncSession, context: SecurityContext
) -> list[PlaceablePerson]:
    """Everybody who can be put in a seat, invited people included.

    **Deliberately wider than `objectives.people`.** That one answers "who may be named as owner
    or approver" and is limited to `active`, because an owner has to be able to act. This answers
    "who works here", and putting somebody in a seat grants them nothing — it records where they
    sit. A picker limited to active members could offer two of the twenty-seven people already
    visible on the chart, which is what it did.

    `deactivated` is excluded: somebody who has left should not be placed into a new seat, and
    §14 already makes deactivation trigger ownership reassignment rather than new assignments.
    """
    await guard.authorise(session, context, Action.VIEW)
    members = (
        (
            await session.execute(
                select(Membership)
                .where(Membership.status != "deactivated")
                .order_by(Membership.display_name)
            )
        )
        .scalars()
        .all()
    )
    return [
        PlaceablePerson(
            membership_id=member.id,
            display_name=member.display_name,
            job_title=member.job_title,
            status=member.status,
        )
        for member in members
    ]


async def _holders_on(session: AsyncSession, on: date) -> dict[uuid.UUID, PersonInSeat]:
    """Who is in which seat on this date. Absent means vacant, which is a fact worth showing."""
    rows = (
        await session.execute(
            select(PositionAssignment, Membership)
            .join(Membership, Membership.id == PositionAssignment.membership_id)
            .where(_effective_on(on))
        )
    ).all()

    return {
        assignment.position_id: PersonInSeat(
            membership_id=assignment.membership_id,
            display_name=member.display_name,
            job_title=member.job_title,
            effective_from=assignment.effective_from,
            effective_to=assignment.effective_to,
            assignment_id=assignment.id,
            assignment_version=assignment.version,
        )
        for assignment, member in rows
    }


async def _reporting_on(
    session: AsyncSession, on: date
) -> tuple[dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, list[uuid.UUID]]]:
    edges = list(
        (await session.execute(select(ReportingEdge).where(_effective_on(on)))).scalars().all()
    )
    primary = {
        edge.position_id: edge.manager_position_id
        for edge in edges
        if edge.kind == ReportingKind.PRIMARY
    }
    dotted: dict[uuid.UUID, list[uuid.UUID]] = {}
    for edge in edges:
        if edge.kind == ReportingKind.DOTTED:
            dotted.setdefault(edge.position_id, []).append(edge.manager_position_id)
    return primary, dotted


async def validate(
    session: AsyncSession, context: SecurityContext, *, as_at: date | None = None
) -> list[ValidationIssue]:
    """Problems worth telling somebody about that are not worth refusing a write over.

    Cycles and duplicate identifiers are refused outright by the database — they can never be in
    the data to find. Orphans are different: a position whose manager was archived is a state a
    real restructure passes through, and refusing it would mean refusing the restructure. So it
    is reported, and a person decides.
    """
    await guard.authorise(session, context, Action.VIEW)
    on = as_at or _now().date()
    issues: list[ValidationIssue] = []

    orphans = (
        await session.execute(
            select(Position.id, Position.title)
            .join(ReportingEdge, ReportingEdge.position_id == Position.id)
            .join(
                Position.__table__.alias("manager"),
                text("manager.id = reporting_edges.manager_position_id"),
            )
            .where(
                Position.archived_at.is_(None),
                ReportingEdge.kind == ReportingKind.PRIMARY,
                _effective_on(on),
                text("manager.archived_at IS NOT NULL"),
            )
        )
    ).all()
    issues.extend(
        ValidationIssue(
            kind="orphan_manager",
            entity_type="position",
            entity_id=position_id,
            detail=f"{title} reports to a position that has been archived.",
        )
        for position_id, title in orphans
    )

    #  A position in no unit cannot exist — the foreign key sees to that. A *unit* with no
    #  positions is normal. What is worth flagging is an active position nobody holds, because
    #  work routed to it goes nowhere.
    vacant = (
        await session.execute(
            select(Position.id, Position.title).where(
                Position.archived_at.is_(None),
                ~select(PositionAssignment.id)
                .where(PositionAssignment.position_id == Position.id, _effective_on(on))
                .exists(),
            )
        )
    ).all()
    issues.extend(
        ValidationIssue(
            kind="vacant_position",
            entity_type="position",
            entity_id=position_id,
            detail=f"{title} has nobody in it on this date.",
        )
        for position_id, title in vacant
    )

    return issues


# ------------------------------------------------------------------------------- writing


async def _revise(
    session: AsyncSession,
    context: SecurityContext,
    *,
    change_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    summary: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reverts: uuid.UUID | None = None,
) -> OrgRevision:
    """One row in the history, and one audit event, both in the caller's transaction."""
    revision = OrgRevision(
        tenant_id=context.tenant_id,
        change_type=change_type,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        before=before,
        after=after,
        actor_membership_id=context.membership_id,
        reverts_revision_id=reverts,
    )
    session.add(revision)

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action=change_type,
        resource_type=entity_type,
        resource_id=entity_id,
        actor=context,
        detail={"summary": summary},
    )
    return revision


def _unit_state(unit: OrgUnit) -> dict[str, Any]:
    return {
        "parent_id": str(unit.parent_id) if unit.parent_id else None,
        "name": unit.name,
        "unit_type": unit.unit_type,
        "external_ref": unit.external_ref,
        "location": unit.location,
        "archived_at": unit.archived_at.isoformat() if unit.archived_at else None,
    }


def _position_state(position: Position) -> dict[str, Any]:
    return {
        "org_unit_id": str(position.org_unit_id),
        "title": position.title,
        #  Added when 0038 added the column, which this helper was not updated for — so an undo
        #  of a title change silently dropped the grade back to nothing. Every field that can be
        #  edited has to be in here, because this dict *is* what undo restores.
        "designation": position.designation,
        "level": position.level,
        "location": position.location,
        "external_ref": position.external_ref,
        "archived_at": position.archived_at.isoformat() if position.archived_at else None,
    }


def _check_version(current: int, expected: int, what: str) -> None:
    if current != expected:
        raise Conflict(
            f"This {what} was changed by somebody else while you were editing. "
            "Reload it and apply your change again."
        )


async def _get_unit(session: AsyncSession, unit_id: uuid.UUID) -> OrgUnit:
    unit = (
        await session.execute(select(OrgUnit).where(OrgUnit.id == unit_id))
    ).scalar_one_or_none()
    if unit is None:
        #  Not found and not permitted are the same response on purpose. Row-level security has
        #  already made another organisation's rows invisible, so "no such unit" is the truth
        #  here as well as the safe answer.
        raise NotFound("No such org unit.")
    return unit


async def _get_position(session: AsyncSession, position_id: uuid.UUID) -> Position:
    position = (
        await session.execute(select(Position).where(Position.id == position_id))
    ).scalar_one_or_none()
    if position is None:
        raise NotFound("No such position.")
    return position


async def create_unit(
    session: AsyncSession, context: SecurityContext, payload: OrgUnitCreate
) -> OrgUnit:
    await guard.authorise(session, context, Action.ADMINISTER)

    if payload.parent_id is not None:
        await _get_unit(session, payload.parent_id)

    unit = OrgUnit(
        tenant_id=context.tenant_id,
        parent_id=payload.parent_id,
        name=payload.name,
        unit_type=payload.unit_type,
        external_ref=payload.external_ref,
        location=payload.location,
    )
    session.add(unit)
    await session.flush()

    await _revise(
        session,
        context,
        change_type="unit.created",
        entity_type="org_unit",
        entity_id=unit.id,
        summary=f"Created {payload.unit_type} “{payload.name}”",
        before=None,
        after=_unit_state(unit),
    )
    return unit


async def update_unit(
    session: AsyncSession,
    context: SecurityContext,
    unit_id: uuid.UUID,
    payload: OrgUnitUpdate,
) -> OrgUnit:
    await guard.authorise(session, context, Action.ADMINISTER)

    unit = await _get_unit(session, unit_id)
    _check_version(unit.version, payload.expected_version, "department")
    before = _unit_state(unit)

    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    for field, value in changes.items():
        setattr(unit, field, value)
    unit.version += 1
    await session.flush()

    await _revise(
        session,
        context,
        change_type="unit.updated",
        entity_type="org_unit",
        entity_id=unit.id,
        summary=f"Updated “{unit.name}”",
        before=before,
        after=_unit_state(unit),
    )
    return unit


async def move_unit(
    session: AsyncSession,
    context: SecurityContext,
    unit_id: uuid.UUID,
    payload: OrgUnitMove,
) -> OrgUnit:
    """Re-parent a unit. The database refuses a move that would make it its own ancestor."""
    await guard.authorise(session, context, Action.ADMINISTER)

    unit = await _get_unit(session, unit_id)
    _check_version(unit.version, payload.expected_version, "department")
    parent = await _get_unit(session, payload.new_parent_id)

    #  The same rule as the seat above, and it matters more here: a move takes the whole subtree,
    #  so re-parenting a live division under an archived one would hide every department, seat and
    #  person below it from the chart while leaving them live and assigned. Nothing else in the
    #  system can produce that state, and `validate` would not report it — an archived *parent* is
    #  not an archived manager.
    if parent.archived_at is not None:
        raise ValidationFailed("That department is archived. Restore it first.")
    #  And an archived unit stays where it was archived. Moving one is not a correction to
    #  anything anybody can see, and it would rewrite the shape a restore comes back into.
    if unit.archived_at is not None:
        raise ValidationFailed("This department is archived. Restore it before moving it.")

    #  A cycle, refused here rather than by the trigger.
    #
    #  `org_units_refuse_cycle` (migration 0011) is the real boundary and stays the real boundary
    #  — it also guards the importer and anything that reaches the table another way. But a
    #  trigger raises `check_violation`, nothing maps that to a status, and the caller was handed
    #  a **500 with "Nothing was changed by this request"**: a server fault where there is none,
    #  and untrue besides. Refusing before the flush gives the same answer as a sentence, and
    #  leaves the transaction alive rather than poisoned.
    ancestor: OrgUnit | None = parent
    hops = 0
    while ancestor is not None:
        if ancestor.id == unit.id:
            raise ValidationFailed(
                f"“{parent.name}” is already inside “{unit.name}”. "
                "A department cannot sit inside itself."
            )
        hops += 1
        if hops > 100:
            #  The same ceiling the trigger uses. Reached only by data the trigger would also
            #  refuse, so this is a guard against looping here, not a rule of its own.
            break
        ancestor = (
            await session.get(OrgUnit, ancestor.parent_id)
            if ancestor.parent_id is not None
            else None
        )

    before = _unit_state(unit)

    unit.parent_id = parent.id
    unit.version += 1
    #  The cycle trigger fires here, not on commit. Flushing now means the caller gets the
    #  refusal at the point of the move rather than at the end of an unrelated request.
    await session.flush()

    await _revise(
        session,
        context,
        change_type="unit.moved",
        entity_type="org_unit",
        entity_id=unit.id,
        summary=f"Moved “{unit.name}” under “{parent.name}”",
        before=before,
        after=_unit_state(unit),
    )
    return unit


async def archive_unit(
    session: AsyncSession, context: SecurityContext, unit_id: uuid.UUID, expected_version: int
) -> OrgUnit:
    """Archive, never delete.

    A unit with active children is refused: archiving a division would otherwise leave its
    departments visible and parented to something that no longer exists, which is the "orphan"
    PLAN §5 asks to detect. Empty it first, deliberately.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    unit = await _get_unit(session, unit_id)
    _check_version(unit.version, expected_version, "department")

    live_children = (
        await session.execute(
            select(OrgUnit.id).where(OrgUnit.parent_id == unit_id, OrgUnit.archived_at.is_(None))
        )
    ).first()
    if live_children is not None:
        raise ValidationFailed(
            "Archive or move the departments inside this one first — archiving it now would "
            "leave them without a parent."
        )

    live_positions = (
        await session.execute(
            select(Position.id).where(
                Position.org_unit_id == unit_id, Position.archived_at.is_(None)
            )
        )
    ).first()
    if live_positions is not None:
        raise ValidationFailed("Archive or move the positions in this department first.")

    before = _unit_state(unit)
    unit.archived_at = _now()
    unit.version += 1
    await session.flush()

    await _revise(
        session,
        context,
        change_type="unit.archived",
        entity_type="org_unit",
        entity_id=unit.id,
        summary=f"Archived “{unit.name}”",
        before=before,
        after=_unit_state(unit),
    )
    return unit


async def create_position(
    session: AsyncSession, context: SecurityContext, payload: PositionCreate
) -> Position:
    await guard.authorise(session, context, Action.ADMINISTER)

    unit = await _get_unit(session, payload.org_unit_id)
    if unit.archived_at is not None:
        raise ValidationFailed("That department is archived. Restore it first.")

    position = Position(
        tenant_id=context.tenant_id,
        org_unit_id=payload.org_unit_id,
        title=payload.title,
        designation=(payload.designation or "").strip() or None,
        level=payload.level,
        location=payload.location,
        external_ref=payload.external_ref,
    )
    session.add(position)
    await session.flush()

    await _revise(
        session,
        context,
        change_type="position.created",
        entity_type="position",
        entity_id=position.id,
        summary=f"Created position “{payload.title}” in “{unit.name}”",
        before=None,
        after=_position_state(position),
    )
    return position


async def update_position(
    session: AsyncSession,
    context: SecurityContext,
    position_id: uuid.UUID,
    payload: PositionUpdate,
) -> Position:
    await guard.authorise(session, context, Action.ADMINISTER)

    position = await _get_position(session, position_id)
    _check_version(position.version, payload.expected_version, "position")
    before = _position_state(position)

    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})

    #  Moving a seat is one of these fields, so this is where a move is refused. `create_position`
    #  has always refused an archived department; without the same check here the rule was one
    #  request away from being bypassed — archive an empty department, then move a seat into it,
    #  and the seat is live inside a box the chart does not draw. That is exactly the orphan state
    #  `archive_unit` refuses to create, arrived at from the other direction.
    #  An archived seat is not on the chart, so a change to it is a change nobody can review.
    #  `assign` has always refused one; renaming or moving one was not checked.
    if position.archived_at is not None:
        raise ValidationFailed("This position is archived. Restore it before changing it.")

    moved_to: OrgUnit | None = None
    if "org_unit_id" in changes:
        #  Sent, and sent as null. `positions.org_unit_id` is NOT NULL, so letting this through
        #  reached the database as an integrity error and came back as a 500 saying "Nothing was
        #  changed by this request" — a server fault, and a false one, for what is a plain
        #  mistake in the request. Refused here, in words, as the 422 it is.
        if changes["org_unit_id"] is None:
            raise ValidationFailed("A position must sit in a department.")
        if changes["org_unit_id"] != position.org_unit_id:
            moved_to = await _get_unit(session, changes["org_unit_id"])
            if moved_to.archived_at is not None:
                raise ValidationFailed("That department is archived. Restore it first.")

    for field, value in changes.items():
        setattr(position, field, value)
    position.version += 1
    await session.flush()

    await _revise(
        session,
        context,
        change_type="position.updated",
        entity_type="position",
        entity_id=position.id,
        #  A move and a rename are both "updated" to the contract, and undo treats them the same
        #  way, so the type stays. The *summary* is what a person reads in the history, and
        #  "Updated position" for a seat that changed department tells them nothing about the one
        #  change they are most likely looking for.
        summary=(
            f"Moved position “{position.title}” to “{moved_to.name}”"
            if moved_to is not None
            else f"Updated position “{position.title}”"
        ),
        before=before,
        after=_position_state(position),
    )
    return position


async def archive_position(
    session: AsyncSession,
    context: SecurityContext,
    position_id: uuid.UUID,
    expected_version: int,
) -> Position:
    """Archive a seat.

    Refused while somebody still holds it. Archiving an occupied position would leave a person
    assigned to something that no longer exists — and the assignment is the record of what they
    do, so it cannot simply be dropped.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    position = await _get_position(session, position_id)
    _check_version(position.version, expected_version, "position")

    held = (
        await session.execute(
            select(PositionAssignment.id).where(
                PositionAssignment.position_id == position_id,
                _effective_on(_now().date()),
            )
        )
    ).first()
    if held is not None:
        raise ValidationFailed("End the current assignment before archiving this position.")

    before = _position_state(position)
    position.archived_at = _now()
    position.version += 1
    await session.flush()

    await _revise(
        session,
        context,
        change_type="position.archived",
        entity_type="position",
        entity_id=position.id,
        summary=f"Archived position “{position.title}”",
        before=before,
        after=_position_state(position),
    )
    return position


async def assign(
    session: AsyncSession,
    context: SecurityContext,
    position_id: uuid.UUID,
    payload: AssignmentCreate,
) -> PositionAssignment:
    """Put somebody in a seat.

    Overlap is refused by the database, not checked here. Two people assigned to one position on
    one day is not a validation nicety — it is two different answers to "who approves this", and
    an application check cannot hold it under two concurrent requests.
    """
    await guard.authorise(session, context, Action.ASSIGN)

    position = await _get_position(session, position_id)
    if position.archived_at is not None:
        raise ValidationFailed("That position is archived.")

    member = (
        await session.execute(select(Membership).where(Membership.id == payload.membership_id))
    ).scalar_one_or_none()
    if member is None:
        raise NotFound("No such person in this workspace.")

    assignment = PositionAssignment(
        tenant_id=context.tenant_id,
        position_id=position_id,
        membership_id=payload.membership_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
    )
    session.add(assignment)
    await session.flush()

    await _revise(
        session,
        context,
        change_type="assignment.created",
        entity_type="position_assignment",
        entity_id=assignment.id,
        summary=(
            f"{member.display_name} holds “{position.title}” from "
            f"{payload.effective_from.isoformat()}"
        ),
        before=None,
        after={
            "position_id": str(position_id),
            "membership_id": str(payload.membership_id),
            "effective_from": payload.effective_from.isoformat(),
            "effective_to": (payload.effective_to.isoformat() if payload.effective_to else None),
        },
    )
    return assignment


async def end_assignment(
    session: AsyncSession,
    context: SecurityContext,
    assignment_id: uuid.UUID,
    payload: AssignmentEnd,
) -> PositionAssignment:
    """Close an assignment. The row stays — they held it, and that remains true."""
    await guard.authorise(session, context, Action.ASSIGN)

    assignment = (
        await session.execute(
            select(PositionAssignment).where(PositionAssignment.id == assignment_id)
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise NotFound("No such assignment.")
    _check_version(assignment.version, payload.expected_version, "assignment")

    #  `<`, not `<=`. Ending on the day it started is a **correction** — "the wrong person was
    #  put in this seat, take them out" — and with an exclusive `effective_to` it is the only date
    #  that empties the seat today. The row stays, so both facts are in the history. See migration
    #  0039; this check and the constraint have to agree or one of them is decoration.
    if payload.effective_to < assignment.effective_from:
        raise ValidationFailed("An assignment cannot end before it started.")

    before = {
        "effective_from": assignment.effective_from.isoformat(),
        "effective_to": (assignment.effective_to.isoformat() if assignment.effective_to else None),
    }
    assignment.effective_to = payload.effective_to
    assignment.version += 1
    await session.flush()

    await _revise(
        session,
        context,
        change_type="assignment.ended",
        entity_type="position_assignment",
        entity_id=assignment.id,
        summary=f"Assignment ends {payload.effective_to.isoformat()}",
        before=before,
        after={
            "effective_from": assignment.effective_from.isoformat(),
            "effective_to": payload.effective_to.isoformat(),
        },
    )
    return assignment


async def add_reporting_line(
    session: AsyncSession,
    context: SecurityContext,
    position_id: uuid.UUID,
    payload: ReportingEdgeCreate,
) -> ReportingEdge:
    """Draw a reporting line.

    `administer` rather than `assign`, because a primary line is where an approval goes. Changing
    it changes who signs off on work, which is a permission decision however it is spelled.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    position = await _get_position(session, position_id)
    manager = await _get_position(session, payload.manager_position_id)

    #  A seat has one primary manager at a time, and until now nothing closed the old line.
    #
    #  `ex_edges_one_primary_manager` (migration 0011) excludes overlapping primary ranges for one
    #  position, so drawing a second open-ended line raised an integrity error the API turned into
    #  a **500 with "Nothing was changed by this request"**. In the seat dialog that lands after
    #  the seat's own PATCH has already committed, so the sentence is false twice: it is not a
    #  server fault, and something *was* changed. Then the retry replays the stored 200 for the
    #  PATCH and 500s again on this call, identically, for as long as the idempotency record
    #  lives. Changing a manager was simply not possible.
    #
    #  So the old line is closed on the day the new one starts. The range is half-open — `[)` in
    #  the constraint — so ending one where the next begins leaves no overlap and no gap: on that
    #  date the seat reports to the new manager, and to the old one on every day before it. The
    #  edge is not deleted. Who reported to whom last March is the question this table exists to
    #  answer, and `reporting.ended` is already in `UNDOABLE` waiting for a producer.
    if payload.kind == ReportingKind.PRIMARY:
        existing = (
            await session.execute(
                select(ReportingEdge).where(
                    ReportingEdge.position_id == position_id,
                    ReportingEdge.kind == ReportingKind.PRIMARY,
                    ReportingEdge.effective_to.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.manager_position_id == payload.manager_position_id:
                #  The line that is already drawn. Returning it rather than raising: the caller
                #  asked for a state that holds, and a second identical edge would be a change
                #  the history records and nobody made.
                return existing
            if existing.effective_from > payload.effective_from:
                raise ValidationFailed(
                    "This seat's current manager starts after that date. "
                    "Choose a date on or after "
                    f"{existing.effective_from.isoformat()}."
                )
            old_manager = await session.get(Position, existing.manager_position_id)
            existing.effective_to = payload.effective_from
            existing.version += 1
            await session.flush()
            await _revise(
                session,
                context,
                change_type="reporting.ended",
                entity_type="reporting_edge",
                entity_id=existing.id,
                summary=(
                    f"“{position.title}” no longer reports to "
                    f"“{old_manager.title if old_manager is not None else 'a removed seat'}” "
                    f"from {payload.effective_from.isoformat()}"
                ),
                before={"effective_to": None},
                after={"effective_to": payload.effective_from.isoformat()},
            )

    edge = ReportingEdge(
        tenant_id=context.tenant_id,
        position_id=position_id,
        manager_position_id=payload.manager_position_id,
        kind=payload.kind,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
    )
    session.add(edge)
    #  The cycle trigger fires on this flush.
    await session.flush()

    await _revise(
        session,
        context,
        change_type="reporting.created",
        entity_type="reporting_edge",
        entity_id=edge.id,
        summary=(
            f"“{position.title}” reports to “{manager.title}” "
            f"({payload.kind} line, from {payload.effective_from.isoformat()})"
        ),
        before=None,
        after={
            "position_id": str(position_id),
            "manager_position_id": str(payload.manager_position_id),
            "kind": payload.kind,
            "effective_from": payload.effective_from.isoformat(),
            "effective_to": (payload.effective_to.isoformat() if payload.effective_to else None),
        },
    )
    return edge


# ----------------------------------------------------------------------------- history


async def revisions(
    session: AsyncSession,
    context: SecurityContext,
    *,
    limit: int = 50,
    before_revision_no: int | None = None,
    entity_id: uuid.UUID | None = None,
) -> RevisionPage:
    """The history, newest first.

    Keyset paging on `revision_no` rather than an offset. Numbers are gapless and assigned by the
    database, so a page identified by "everything below 40" stays the same page as new revisions
    arrive — an offset would shift under the reader.
    """
    await guard.authorise(session, context, Action.VIEW)

    statement = (
        select(OrgRevision, Membership.display_name)
        .outerjoin(Membership, Membership.id == OrgRevision.actor_membership_id)
        .order_by(OrgRevision.revision_no.desc())
        .limit(limit + 1)
    )
    if before_revision_no is not None:
        statement = statement.where(OrgRevision.revision_no < before_revision_no)
    if entity_id is not None:
        statement = statement.where(OrgRevision.entity_id == entity_id)

    rows = (await session.execute(statement)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return RevisionPage(
        revisions=[
            RevisionRead(
                id=revision.id,
                revision_no=revision.revision_no,
                change_type=revision.change_type,
                entity_type=revision.entity_type,
                entity_id=revision.entity_id,
                summary=revision.summary,
                actor_membership_id=revision.actor_membership_id,
                actor_display_name=actor_name,
                created_at=revision.created_at,
                can_undo=revision.change_type in UNDOABLE and revision.reverts_revision_id is None,
            )
            for revision, actor_name in rows
        ],
        next_before_revision_no=rows[-1][0].revision_no if has_more and rows else None,
    )


async def undo(
    session: AsyncSession, context: SecurityContext, revision_id: uuid.UUID
) -> OrgRevision:
    """Reverse one recorded change.

    **Undo is a new change, not an erasure.** It writes its own revision pointing at the one it
    reverses, so the history shows that somebody undid something rather than pretending it never
    happened. That is also what gives PLAN §5's redo for free: undoing the undo is an ordinary
    undo of an ordinary revision.

    Only the most recent revision for an entity can be reversed. Reversing an older one would
    silently discard everything that happened to that entity since, and there is no honest way to
    ask "are you sure" about a change somebody cannot see.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    revision = (
        await session.execute(select(OrgRevision).where(OrgRevision.id == revision_id))
    ).scalar_one_or_none()
    if revision is None:
        raise NotFound("No such revision.")

    if revision.change_type not in UNDOABLE:
        raise ValidationFailed(f"“{revision.summary}” cannot be undone automatically.")

    latest = (
        await session.execute(
            select(OrgRevision.id)
            .where(OrgRevision.entity_id == revision.entity_id)
            .order_by(OrgRevision.revision_no.desc())
            .limit(1)
        )
    ).scalar_one()
    if latest != revision.id:
        raise ValidationFailed(
            "Something else has changed since. Undo the most recent change first."
        )

    if revision.entity_type == "org_unit":
        await _undo_unit(session, revision)
    elif revision.entity_type == "position":
        await _undo_position(session, revision)
    elif revision.entity_type == "position_assignment":
        await _undo_assignment(session, revision)
    elif revision.entity_type == "reporting_edge":
        await _undo_edge(session, revision)
    else:  # pragma: no cover - the list above matches UNDOABLE exactly
        raise ValidationFailed("That change cannot be undone automatically.")

    await session.flush()
    return await _revise(
        session,
        context,
        change_type=f"{revision.entity_type}.undone",
        entity_type=revision.entity_type,
        entity_id=revision.entity_id,
        summary=f"Undid: {revision.summary}",
        before=revision.after,
        after=revision.before,
        reverts=revision.id,
    )


def _date_or_none(value: object) -> date | None:
    """A date read back out of a revision's JSON.

    The column is `JSONB`, so everything comes back as `object`. Anything that is not a string is
    a corrupted revision rather than an absent date, and treating it as absent would quietly
    reopen a closed assignment.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationFailed("That revision cannot be read back; its stored dates are invalid.")
    return date.fromisoformat(value)


def _restore(row: Any, state: dict[str, Any], fields: Sequence[str]) -> None:
    for field in fields:
        value = state.get(field)
        if field.endswith("_id") and isinstance(value, str):
            setattr(row, field, uuid.UUID(value))
        elif field == "archived_at":
            row.archived_at = datetime.fromisoformat(value) if value else None
        else:
            setattr(row, field, value)
    row.version += 1


async def _undo_unit(session: AsyncSession, revision: OrgRevision) -> None:
    unit = await _get_unit(session, revision.entity_id)
    if revision.before is None:
        #  It was created. Undoing a creation archives it rather than deleting it: something may
        #  already reference it, and a delete would fail or, worse, cascade.
        unit.archived_at = _now()
        unit.version += 1
        return
    _restore(
        unit,
        revision.before,
        ("parent_id", "name", "unit_type", "external_ref", "location", "archived_at"),
    )


async def _undo_position(session: AsyncSession, revision: OrgRevision) -> None:
    position = await _get_position(session, revision.entity_id)
    if revision.before is None:
        position.archived_at = _now()
        position.version += 1
        return
    _restore(
        position,
        revision.before,
        ("org_unit_id", "title", "level", "location", "external_ref", "archived_at"),
    )


async def _undo_assignment(session: AsyncSession, revision: OrgRevision) -> None:
    assignment = (
        await session.execute(
            select(PositionAssignment).where(PositionAssignment.id == revision.entity_id)
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise NotFound("No such assignment.")

    if revision.before is None:
        #  Undoing "this person took this seat" is the one deletion here, and it is safe: an
        #  assignment nothing has happened under is a statement of fact that turned out to be
        #  wrong, not a historical record worth keeping.
        await session.delete(assignment)
        return

    assignment.effective_to = _date_or_none(revision.before.get("effective_to"))
    assignment.version += 1


async def _undo_edge(session: AsyncSession, revision: OrgRevision) -> None:
    edge = (
        await session.execute(select(ReportingEdge).where(ReportingEdge.id == revision.entity_id))
    ).scalar_one_or_none()
    if edge is None:
        raise NotFound("No such reporting line.")

    if revision.before is None:
        await session.delete(edge)
        return

    edge.effective_to = _date_or_none(revision.before.get("effective_to"))
    edge.version += 1
