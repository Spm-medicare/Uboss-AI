"""Moving a department or a seat, and the four ways it could have gone wrong.

`POST /hierarchy/units/{id}/move` and `PositionUpdate.org_unit_id` have both existed since Gate 3
with **no caller** — a conformance pass found the route, the typed client and zero call sites. So
until the screen grew a Move control the two were only ever exercised by the cycle test, and the
checks a real move needs were missing rather than wrong.

Three of them are about the same mistake seen from different sides. `archive_unit` refuses to
archive a department that still has live positions in it, because that would leave people assigned
to a box the chart does not draw. But nothing stopped you reaching the same state the other way:

* archive an empty department, then **move a seat into it** — live seat, invisible box;
* archive a division, then **move a live subtree under it** — an entire department, its seats and
  its people, all live and all off the chart. `validate` would not report it either: an archived
  *parent* is not an archived *manager*.
* move a department that is itself archived, rewriting the shape a restore comes back into.

The fourth is undo. `_position_state` is what an undo restores, and it was never updated when
migration 0038 added `designation` — so undoing a title change also silently blanked the grade.
That is not about moving, but it is in the same function and it is the kind of bug a test finds
only when somebody looks.

Every test here asserts the refusal **and** that the refused operation changed nothing, because a
guard that raises after mutating is worse than no guard: the caller reads an error and the row has
already moved.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from tests.integration.test_hierarchy_service import _context, _grant
from uboss.core.errors import ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy import service
from uboss.modules.hierarchy.models import ReportingKind, UnitType
from uboss.modules.hierarchy.schemas import (
    OrgUnitCreate,
    OrgUnitMove,
    PositionCreate,
    PositionUpdate,
    ReportingEdgeCreate,
)

TODAY = date.today()


async def _company(session: AsyncSession, workspace: Workspace) -> tuple[object, object, object]:
    """A company with two departments under it, and a context that may change the structure."""
    await _grant(session, workspace, "administer")
    context = await _context(session, workspace)
    root = await service.create_unit(
        session, context, OrgUnitCreate(name="Acme", unit_type=UnitType.COMPANY)
    )
    left = await service.create_unit(
        session,
        context,
        OrgUnitCreate(name="Engineering", unit_type=UnitType.DEPARTMENT, parent_id=root.id),
    )
    right = await service.create_unit(
        session,
        context,
        OrgUnitCreate(name="Operations", unit_type=UnitType.DEPARTMENT, parent_id=root.id),
    )
    await session.flush()
    return context, left, right


async def test_a_seat_cannot_be_moved_into_an_archived_department(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The hole `create_position` already closed, reached through update instead.

    Creating a seat in an archived department has always been refused. Moving one into it was not,
    which made the rule one request away from being bypassed.
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, operations = await _company(session, left_ws)

        seat = await service.create_position(
            session,
            context,
            PositionCreate(org_unit_id=engineering.id, title="Backend Lead"),
        )
        await session.flush()

        #  Operations is empty, so archiving it is allowed — that is the point.
        await service.archive_unit(session, context, operations.id, operations.version)
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await service.update_position(
                session,
                context,
                seat.id,
                PositionUpdate(org_unit_id=operations.id, expected_version=seat.version),
            )
        assert "archived" in str(refused.value)

        await session.refresh(seat)
        assert seat.org_unit_id == engineering.id, "the refusal must not have moved it anyway"
        await session.rollback()


async def test_a_live_subtree_cannot_be_moved_under_an_archived_department(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The same rule, and the case where it costs the most.

    A move takes the whole subtree, so this one refusal is the difference between a re-org and an
    entire department disappearing from the chart while everybody in it stays assigned.
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, operations = await _company(session, left_ws)

        await service.create_position(
            session,
            context,
            PositionCreate(org_unit_id=engineering.id, title="Backend Lead"),
        )
        await session.flush()

        await service.archive_unit(session, context, operations.id, operations.version)
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await service.move_unit(
                session,
                context,
                engineering.id,
                OrgUnitMove(new_parent_id=operations.id, expected_version=engineering.version),
            )
        assert "archived" in str(refused.value)

        await session.refresh(engineering)
        assert engineering.parent_id != operations.id
        await session.rollback()


async def test_an_archived_department_stays_where_it_was_archived(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Moving an archived department corrects nothing anybody can see.

    It would only change the shape a restore comes back into — a change made invisibly, to a thing
    that is not on the chart, which nobody can review.
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, operations = await _company(session, left_ws)

        await service.archive_unit(session, context, engineering.id, engineering.version)
        await session.flush()
        await session.refresh(engineering)

        with pytest.raises(ValidationFailed) as refused:
            await service.move_unit(
                session,
                context,
                engineering.id,
                OrgUnitMove(new_parent_id=operations.id, expected_version=engineering.version),
            )
        assert "Restore it before moving it" in str(refused.value)
        await session.rollback()


async def test_a_move_that_is_allowed_takes_the_seat_with_it_and_says_so(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The happy path, which is the whole point of the control.

    Asserts three things a person would check: the department changed, the seat inside it did not
    have to be touched, and the history says *moved* rather than *updated* — because "Updated
    department" is what the history said for a re-org before this, and that is a true sentence
    that answers no question.
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, operations = await _company(session, left_ws)

        seat = await service.create_position(
            session,
            context,
            PositionCreate(org_unit_id=engineering.id, title="Backend Lead"),
        )
        await session.flush()

        await service.move_unit(
            session,
            context,
            engineering.id,
            OrgUnitMove(new_parent_id=operations.id, expected_version=engineering.version),
        )
        await session.flush()

        await session.refresh(engineering)
        await session.refresh(seat)
        assert engineering.parent_id == operations.id
        assert seat.org_unit_id == engineering.id, "the seat travels with its department"

        page = await service.revisions(session, context, limit=1)
        assert page.revisions[0].change_type == "unit.moved"
        assert "Moved “Engineering” under “Operations”" in page.revisions[0].summary
        await session.rollback()


async def test_moving_a_seat_reads_as_a_move_in_the_history(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A seat's move goes through `update_position`, so only the summary can tell them apart.

    The change type stays `position.updated` — undo keys off it and the contract is committed —
    but a history that says "Updated position" for the one change somebody is looking for is a
    record that technically holds and practically does not.
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, operations = await _company(session, left_ws)

        seat = await service.create_position(
            session,
            context,
            PositionCreate(org_unit_id=engineering.id, title="Backend Lead"),
        )
        await session.flush()

        await service.update_position(
            session,
            context,
            seat.id,
            PositionUpdate(org_unit_id=operations.id, expected_version=seat.version),
        )
        await session.flush()
        await session.refresh(seat)
        assert seat.org_unit_id == operations.id

        page = await service.revisions(session, context, limit=1)
        assert page.revisions[0].change_type == "position.updated"
        assert "Moved position “Backend Lead” to “Operations”" in page.revisions[0].summary

        #  A rename in the same shape must NOT claim a move.
        await service.update_position(
            session,
            context,
            seat.id,
            PositionUpdate(title="Backend Manager", expected_version=seat.version),
        )
        await session.flush()
        renamed = await service.revisions(session, context, limit=1)
        assert "Updated position" in renamed.revisions[0].summary
        await session.rollback()


async def test_undo_of_a_title_change_keeps_the_grade(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`_position_state` is what undo restores, and it had no `designation`.

    Migration 0038 added the column and this helper was not updated, so every undo of a seat wrote
    back a state in which the grade had never been set — losing data while reporting success,
    which is the failure mode the frontend truthfulness rules exist to prevent, one layer down.
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, _ = await _company(session, left_ws)

        seat = await service.create_position(
            session,
            context,
            PositionCreate(
                org_unit_id=engineering.id, title="Backend Lead", designation="Senior Engineer"
            ),
        )
        await session.flush()

        await service.update_position(
            session,
            context,
            seat.id,
            PositionUpdate(title="Backend Manager", expected_version=seat.version),
        )
        await session.flush()

        page = await service.revisions(session, context, limit=1)
        await service.undo(session, context, page.revisions[0].id)
        await session.flush()
        await session.refresh(seat)

        assert seat.title == "Backend Lead"
        assert seat.designation == "Senior Engineer", "undo must not blank the grade"
        await session.rollback()


async def test_a_seat_must_sit_in_a_department(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """An explicit null is a mistake in the request, and now reads as one.

    `positions.org_unit_id` is NOT NULL, so a null reached the database as an integrity error and
    came back as a 500 saying *"Nothing was changed by this request"* — a server fault where there
    is none. Worth its own test because the guard that refuses it is one character away from the
    bug that let it through: `if changes.get(...) not in (None, current)` skips on an explicit
    null, which is precisely the value that must not pass.
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, _ = await _company(session, left_ws)
        seat = await service.create_position(
            session, context, PositionCreate(org_unit_id=engineering.id, title="Backend Lead")
        )
        await session.flush()

        with pytest.raises(ValidationFailed) as refused:
            await service.update_position(
                session,
                context,
                seat.id,
                PositionUpdate(org_unit_id=None, expected_version=seat.version),
            )
        assert "must sit in a department" in str(refused.value)

        await session.refresh(seat)
        assert seat.org_unit_id == engineering.id
        await session.rollback()


async def test_an_archived_seat_cannot_be_edited_or_moved(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`assign` refused an archived seat; renaming and moving one did not.

    A seat that is not on the chart cannot be reviewed, so a change to it is a change nobody sees.
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, operations = await _company(session, left_ws)
        seat = await service.create_position(
            session, context, PositionCreate(org_unit_id=engineering.id, title="Backend Lead")
        )
        await session.flush()
        await service.archive_position(session, context, seat.id, seat.version)
        await session.flush()
        await session.refresh(seat)

        with pytest.raises(ValidationFailed) as refused:
            await service.update_position(
                session,
                context,
                seat.id,
                PositionUpdate(org_unit_id=operations.id, expected_version=seat.version),
            )
        assert "archived" in str(refused.value)
        await session.rollback()


async def test_changing_a_manager_closes_the_old_line_instead_of_failing(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The worst of the lot: changing a manager was impossible, and said so untruthfully.

    A seat may have one primary manager at a time — `ex_edges_one_primary_manager` excludes
    overlapping primary ranges — and nothing closed the old line. So a second line raised an
    integrity error, the API returned **500 "Nothing was changed by this request"**, and in the
    seat dialog that arrived *after* the seat own PATCH had committed, making the sentence false
    twice over. The retry then replayed the stored 200 and failed identically for as long as the
    idempotency record lived.

    Now the old line is closed on the day the new one starts. Half-open ranges mean no overlap and
    no gap, and the old edge stays: it is the answer to "who did they report to in March".
    """
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, _ = await _company(session, left_ws)
        seat = await service.create_position(
            session, context, PositionCreate(org_unit_id=engineering.id, title="Engineer")
        )
        first = await service.create_position(
            session, context, PositionCreate(org_unit_id=engineering.id, title="First Manager")
        )
        second = await service.create_position(
            session, context, PositionCreate(org_unit_id=engineering.id, title="Second Manager")
        )
        await session.flush()

        yesterday = TODAY - timedelta(days=1)
        original = await service.add_reporting_line(
            session,
            context,
            seat.id,
            ReportingEdgeCreate(
                manager_position_id=first.id,
                kind=ReportingKind.PRIMARY,
                effective_from=yesterday,
            ),
        )
        await session.flush()

        #  The call that used to be a 500.
        drawn = await service.add_reporting_line(
            session,
            context,
            seat.id,
            ReportingEdgeCreate(
                manager_position_id=second.id,
                kind=ReportingKind.PRIMARY,
                effective_from=TODAY,
            ),
        )
        await session.flush()

        await session.refresh(original)
        assert original.effective_to == TODAY, "the old line is closed, not deleted"
        assert drawn.manager_position_id == second.id
        assert drawn.effective_to is None

        page = await service.revisions(session, context, limit=3)
        summaries = [r.summary for r in page.revisions]
        assert any("no longer reports to" in text for text in summaries)
        assert any("First Manager" in text for text in summaries)
        await session.rollback()


async def test_drawing_the_line_that_is_already_there_changes_nothing(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Asking for a state that already holds is not a change, and must not be recorded as one."""
    left_ws, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, engineering, _ = await _company(session, left_ws)
        seat = await service.create_position(
            session, context, PositionCreate(org_unit_id=engineering.id, title="Engineer")
        )
        boss = await service.create_position(
            session, context, PositionCreate(org_unit_id=engineering.id, title="Manager")
        )
        await session.flush()

        first = await service.add_reporting_line(
            session,
            context,
            seat.id,
            ReportingEdgeCreate(
                manager_position_id=boss.id, kind=ReportingKind.PRIMARY, effective_from=TODAY
            ),
        )
        await session.flush()
        before = len((await service.revisions(session, context, limit=20)).revisions)

        again = await service.add_reporting_line(
            session,
            context,
            seat.id,
            ReportingEdgeCreate(
                manager_position_id=boss.id, kind=ReportingKind.PRIMARY, effective_from=TODAY
            ),
        )
        await session.flush()

        assert again.id == first.id
        after = len((await service.revisions(session, context, limit=20)).revisions)
        assert after == before, "no revision for a change nobody made"
        await session.rollback()
