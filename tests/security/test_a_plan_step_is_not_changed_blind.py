"""The two plan mutations that overwrote a step without looking at it first.

Every mutation on a plan step carried `expected_version` except the two that change the most:
**merge**, which deletes the step it absorbs, and **set_dependencies**, which replaces a step's
whole dependency set rather than adding to it. So a merge could swallow a step somebody had
rewritten a moment earlier and take the rewrite with it, and a dependency edit made against an
older view of the list silently dropped whatever had appeared in between.

Two of the six were already sound and are left alone, which is worth recording because "add a
version everywhere" would have been the easy and wrong answer:

* **`reorder`** takes the whole order and refuses one whose id set does not match the plan. That
  catches the concurrent add or remove it is actually exposed to — a version would be ceremony on
  top of a real guard.
* **`add` and `duplicate`** create. There is nothing to overwrite; their fault was an idempotency
  key too loose to tell two presses apart, which is a client concern and fixed there.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict
from uboss.db.base import build_sessionmaker
from uboss.modules.objectives import graph
from uboss.modules.objectives.proposal_models import ObjectiveStep


async def _plan(
    session: AsyncSession, context: SecurityContext, objective_id: uuid.UUID
) -> list[ObjectiveStep]:
    """Three steps, in order, so a merge has something to absorb and something to keep."""
    for title in ("Read the enquiry", "Price it", "Send the quotation"):
        await graph.add(session, context, objective_id, kind="human", title=title)
    await session.flush()
    return list(
        (
            await session.execute(
                select(ObjectiveStep)
                .where(ObjectiveStep.objective_id == objective_id)
                .order_by(ObjectiveStep.position)
            )
        )
        .scalars()
        .all()
    )


async def _objective(
    session: AsyncSession, workspace: Workspace
) -> tuple[SecurityContext, uuid.UUID]:
    from tests.integration.test_objective_analysis import _context, _ready_objective

    context = await _context(session, workspace)
    objective_id = await _ready_objective(session, context)
    return context, objective_id


async def test_merging_a_step_somebody_has_since_changed_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A merge deletes what it absorbs, so a stale view of it destroys an edit.

    Asserts the refusal and that both steps are still there, because a guard that raises after
    writing is worse than no guard.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, objective_id = await _objective(session, left)
        steps = await _plan(session, context, objective_id)
        stale = steps[1].version

        #  Somebody edits the step that is about to be absorbed.
        await graph.update(
            session,
            context,
            steps[1].id,
            expected_version=stale,
            changes={"detail": "Use the contract price list, not the published one."},
        )
        await session.flush()

        with pytest.raises(Conflict) as refused:
            await graph.merge(
                session, context, steps[1].id, steps[0].id, expected_version=stale
            )
        assert "changed by somebody else" in str(refused.value)

        survivors = await session.execute(
            select(ObjectiveStep).where(ObjectiveStep.objective_id == objective_id)
        )
        assert len(list(survivors.scalars().all())) == 3, "the refusal deleted nothing"
        await session.rollback()


async def test_merging_with_the_current_version_still_works(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The other direction, so the guard is not simply a wall."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, objective_id = await _objective(session, left)
        steps = await _plan(session, context, objective_id)

        merged = await graph.merge(
            session,
            context,
            steps[1].id,
            steps[0].id,
            expected_version=steps[1].version,
        )
        await session.flush()

        assert merged.id == steps[0].id
        remaining = list(
            (
                await session.execute(
                    select(ObjectiveStep).where(ObjectiveStep.objective_id == objective_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining) == 2
        await session.rollback()


async def test_dependencies_written_against_an_older_view_are_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The set is replaced, so a stale edit drops whatever appeared in between."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, objective_id = await _objective(session, left)
        steps = await _plan(session, context, objective_id)
        stale = steps[2].version

        await graph.set_dependencies(
            session, context, steps[2].id, [steps[0].id], expected_version=stale
        )
        await session.flush()

        #  A second edit that never saw the first would erase it.
        with pytest.raises(Conflict):
            await graph.set_dependencies(
                session, context, steps[2].id, [steps[1].id], expected_version=stale
            )

        await session.refresh(steps[2])
        current = await graph.set_dependencies(
            session,
            context,
            steps[2].id,
            [steps[0].id, steps[1].id],
            expected_version=steps[2].version,
        )
        assert current is None  # returns nothing; the assertion is that it did not raise
        await session.rollback()


async def test_reordering_still_needs_no_version_because_it_checks_the_plan(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The guard `reorder` already had, pinned so nobody replaces it with a version.

    It takes the whole order and refuses one whose id set does not match — which catches the
    concurrent add or remove that a positional rewrite is actually exposed to.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context, objective_id = await _objective(session, left)
        steps = await _plan(session, context, objective_id)

        await graph.reorder(
            session, context, objective_id, [steps[2].id, steps[0].id, steps[1].id]
        )
        await session.flush()

        #  An order that names a step the plan no longer has, or omits one it does.
        with pytest.raises(Exception) as refused:
            await graph.reorder(session, context, objective_id, [steps[0].id, steps[1].id])
        assert "does not match the plan" in str(refused.value)
        await session.rollback()
