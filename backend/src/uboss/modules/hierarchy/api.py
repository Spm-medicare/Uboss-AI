"""The company tree over HTTP.

Every route here is thin on purpose: parse, call the service, return. The rules — who may do
what, what version they had, what gets written to the history — live in `service.py`, so a second
caller (Gate 2.3's importer) gets the same behaviour without a route in front of it.

**Every mutation carries `Idempotency-Key`.** PLAN §28, and it is not ceremony: a retry after a
dropped connection would otherwise create a second department, a duplicate position, or a second
audit row for one change. The key comes from the logical operation and is reused by the retry;
`crypto.randomUUID()` per call would defeat the whole mechanism.

**Every state change carries `expected_version`.** Two people editing one department is ordinary;
the second save silently discarding the first is not.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, Query, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, RedisDep, SessionDep, SettingsDep
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.hierarchy import invite, service
from uboss.modules.hierarchy.schemas import (
    AssignmentCreate,
    AssignmentEnd,
    InvitePerson,
    OrgUnitCreate,
    OrgUnitMove,
    OrgUnitUpdate,
    PlaceablePerson,
    PositionCreate,
    PositionUpdate,
    ReportingEdgeCreate,
    RevisionPage,
    TreeRead,
    ValidationIssue,
)

router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])

#: The date a read describes. Absent means today — but *stated* in the response either way, so a
#: cached page can never be mistaken for a current one.
AsAt = Annotated[
    date | None,
    Query(description="Show the structure as it stands on this date. Defaults to today."),
]


@router.get("", summary="The company tree")
async def read_tree(
    context: CurrentContext,
    session: SessionDep,
    as_at: AsAt = None,
    include_archived: Annotated[bool, Query()] = False,
) -> TreeRead:
    """Units and positions, flat, as at one date.

    Flat rather than nested: the client builds the nesting from `parent_id`, which means one
    response shape serves the tree, a search result and a partially expanded view. A nested
    response would also have to pick a depth limit, and every limit is wrong for somebody.

    `is_empty` distinguishes "this organisation has no tree yet" from "the request failed" — two
    states that look identical on screen and mean opposite things.
    """
    return await service.read_tree(session, context, as_at=as_at, include_archived=include_archived)


@router.get("/issues", summary="Problems worth someone's attention")
async def read_issues(
    context: CurrentContext, session: SessionDep, as_at: AsAt = None
) -> list[ValidationIssue]:
    """Orphaned managers and vacant seats.

    Not cycles or duplicate identifiers: those are refused by the database and can never be here
    to find. These are states a real restructure passes through, so they are reported rather than
    refused, and a person decides what to do about them.
    """
    return await service.validate(session, context, as_at=as_at)


@router.get("/people", summary="Who can be put in a seat")
async def read_placeable_people(
    context: CurrentContext, session: SessionDep
) -> list[PlaceablePerson]:
    """Everybody who works here, invited colleagues included.

    Wider than `/objectives/people` on purpose, and the two are not interchangeable: that route
    answers *"who may be named as owner or approver"* and is limited to active members, because an
    owner has to be able to act. Placing somebody in a seat grants them nothing — it records where
    they sit — and an invited colleague is exactly who a chart is drawn around during onboarding.
    """
    return await service.placeable_people(session, context)


@router.post(
    "/people",
    status_code=status.HTTP_201_CREATED,
    summary="Add a colleague to this workspace",
)
async def invite_person(
    body: InvitePerson,
    context: CurrentContext,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """A name and an address, so the chart can place somebody who has never signed in.

    `manage_access` — §14's own word for deciding who is in an organisation — which is high-risk,
    so this asks for a password. The invitation is queued on the outbox, never sent from here, so
    it goes if and only if this transaction commits.

    An address the workspace already has returns that person rather than failing: inviting
    somebody twice is an ordinary thing to do, and the caller wanted a person to place.
    """
    added = await invite.add_person(
        session,
        context,
        redis,
        settings,
        display_name=body.display_name,
        email=body.email,
    )
    await session.commit()
    return {
        "membership_id": str(added.membership_id),
        "display_name": added.display_name,
        "created": str(added.created).lower(),
    }


@router.get("/revisions", summary="What changed, and who changed it")
async def read_revisions(
    context: CurrentContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_revision_no: Annotated[int | None, Query(ge=1)] = None,
    entity_id: Annotated[uuid.UUID | None, Query()] = None,
) -> RevisionPage:
    """Newest first, keyset-paged.

    Paged on `revision_no` rather than an offset. Numbers are gapless and database-assigned, so
    "everything below 40" stays the same page as new revisions arrive; an offset would shift
    under the reader mid-scroll.
    """
    return await service.revisions(
        session,
        context,
        limit=limit,
        before_revision_no=before_revision_no,
        entity_id=entity_id,
    )


# ------------------------------------------------------------------------------- units


@router.post("/units", status_code=status.HTTP_201_CREATED, summary="Add a department")
async def create_unit(
    body: OrgUnitCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.unit.create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        unit = await service.create_unit(session, context, body)
        result = {"id": str(unit.id), "version": str(unit.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.patch("/units/{unit_id}", summary="Rename or re-code a department")
async def update_unit(
    unit_id: uuid.UUID,
    body: OrgUnitUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.unit.update",
        payload={"unit_id": str(unit_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        unit = await service.update_unit(session, context, unit_id, body)
        result = {"id": str(unit.id), "version": str(unit.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/units/{unit_id}/move", summary="Move a department")
async def move_unit(
    unit_id: uuid.UUID,
    body: OrgUnitMove,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Re-parent a unit, taking its whole subtree with it.

    Its own endpoint rather than a field on `PATCH`, because it is a different kind of change —
    every position and reporting line underneath moves with it — and it reads as its own line in
    the revision history, which is what somebody reviewing a restructure needs.

    A move that would make the unit its own ancestor is refused by the database.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.unit.move",
        payload={"unit_id": str(unit_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        unit = await service.move_unit(session, context, unit_id, body)
        result = {"id": str(unit.id), "version": str(unit.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/units/{unit_id}/archive", summary="Archive a department")
async def archive_unit(
    unit_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True, ge=1)] = 1,
) -> dict[str, str]:
    """Archive, never delete — PLAN §30.

    Refused while the department still contains live departments or positions. Archiving it
    anyway would leave them parented to something no longer there, which is exactly the orphan
    §5 asks the product to detect.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.unit.archive",
        payload={"unit_id": str(unit_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        unit = await service.archive_unit(session, context, unit_id, expected_version)
        result = {"id": str(unit.id), "version": str(unit.version)}
        execution.complete_json(status_code=200, body=result)
        return result


# --------------------------------------------------------------------------- positions


@router.post("/positions", status_code=status.HTTP_201_CREATED, summary="Add a position")
async def create_position(
    body: PositionCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Create a seat. It exists whether or not anybody is in it — PLAN §5's vacant positions."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.position.create",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        position = await service.create_position(session, context, body)
        result = {"id": str(position.id), "version": str(position.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.patch("/positions/{position_id}", summary="Edit a position")
async def update_position(
    position_id: uuid.UUID,
    body: PositionUpdate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.position.update",
        payload={"position_id": str(position_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        position = await service.update_position(session, context, position_id, body)
        result = {"id": str(position.id), "version": str(position.version)}
        execution.complete_json(status_code=200, body=result)
        return result


@router.post("/positions/{position_id}/archive", summary="Archive a position")
async def archive_position(
    position_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Body(embed=True, ge=1)] = 1,
) -> dict[str, str]:
    """Refused while somebody still holds it — end the assignment first."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.position.archive",
        payload={"position_id": str(position_id), "expected_version": expected_version},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        position = await service.archive_position(session, context, position_id, expected_version)
        result = {"id": str(position.id), "version": str(position.version)}
        execution.complete_json(status_code=200, body=result)
        return result


# ------------------------------------------------------------------------- assignments


@router.post(
    "/positions/{position_id}/assignments",
    status_code=status.HTTP_201_CREATED,
    summary="Put somebody in a position",
)
async def assign(
    position_id: uuid.UUID,
    body: AssignmentCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Effective from a date. Overlapping the current holder is refused by the database.

    `assign`, not `administer`: this happens every time somebody joins, moves or is promoted, and
    asking for a password each time would train people to type it without reading.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.assignment.create",
        payload={"position_id": str(position_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        assignment = await service.assign(session, context, position_id, body)
        result = {"id": str(assignment.id), "version": str(assignment.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


@router.patch("/assignments/{assignment_id}", summary="End an assignment")
async def end_assignment(
    assignment_id: uuid.UUID,
    body: AssignmentEnd,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Closes it on a date. Never a delete — they held the seat, and that stays true."""
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.assignment.end",
        payload={"assignment_id": str(assignment_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        assignment = await service.end_assignment(session, context, assignment_id, body)
        result = {"id": str(assignment.id), "version": str(assignment.version)}
        execution.complete_json(status_code=200, body=result)
        return result


# --------------------------------------------------------------------------- reporting


@router.post(
    "/positions/{position_id}/reporting",
    status_code=status.HTTP_201_CREATED,
    summary="Draw a reporting line",
)
async def add_reporting_line(
    position_id: uuid.UUID,
    body: ReportingEdgeCreate,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """A primary line or a dotted one.

    At most one primary line at a time, and a line that would close a loop in the management
    chain is refused — both by the database. Escalation walks this graph, so a loop is an
    approval that never reaches a person.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.reporting.create",
        payload={"position_id": str(position_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        edge = await service.add_reporting_line(session, context, position_id, body)
        result = {"id": str(edge.id), "version": str(edge.version)}
        execution.complete_json(status_code=status.HTTP_201_CREATED, body=result)
        return result


# ------------------------------------------------------------------------------- undo


@router.post("/revisions/{revision_id}/undo", summary="Undo a change")
async def undo(
    revision_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Reverse one recorded change — PLAN §5's undo.

    **The undo is itself a change.** It writes its own revision pointing at the one it reverses,
    so the history shows that somebody undid something rather than pretending it never happened.
    Redo follows from that at no extra cost: undoing the undo is an ordinary undo.

    Only the most recent change to an entity can be reversed. Reversing an older one would
    silently discard everything since, and there is no honest way to warn about a change the
    person cannot see.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.revision.undo",
        payload={"revision_id": str(revision_id)},
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        revision = await service.undo(session, context, revision_id)
        result = {"id": str(revision.id), "revision_no": str(revision.revision_no)}
        execution.complete_json(status_code=200, body=result)
        return result
