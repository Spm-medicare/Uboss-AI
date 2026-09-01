"""What the Copilot can read, proved rather than assumed.

Two of Gate 7's six Copilot exit criteria live here: *permission ceiling* and *cross-tenant
leakage*. Both are about the same risk from different directions — a snippet that reaches a model
prompt has left the building, and no later check can call it back.

The cross-tenant test is the one that would be easy to write badly. Asserting that a search returns
*my* objective proves nothing: it would pass on a retrieval with no tenant filter at all, because
mine is in the results either way. So it creates the same words in two workspaces and asserts the
other one's row is **absent** — the only shape that fails when the filter is missing.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.copilot import retrieval
from uboss.modules.objectives.models import Objective

#: The same distinctive phrase in both workspaces, so a leak is unmistakable.
PHRASE = "quotation turnaround"


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    from tests.integration.test_objective_analysis import _context as build

    return await build(session, workspace)


async def _objective(session: AsyncSession, workspace: Workspace, title: str) -> uuid.UUID:
    row = Objective(
        tenant_id=workspace.tenant_id,
        title=title,
        department="Sales",
        expected_result="Quotations out within one working day.",
        owner_membership_id=workspace.membership_id,
        created_by_membership_id=workspace.membership_id,
    )
    session.add(row)
    await session.flush()
    return row.id


async def test_it_finds_what_the_asker_may_read(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The baseline. Without it, a retrieval that returns nothing would pass every test below."""
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            await _objective(session, left, f"Reduce {PHRASE}")
            context = await _context(session, left)

            found = await retrieval.search(session, context, PHRASE)

            assert found, "a matching objective this person owns must be findable"
            assert any(source.kind == "objective" for source in found)
            #  Every source carries somewhere to go and check it — §18's requirement.
            assert all(source.href for source in found)
            assert all(source.label for source in found)
            await session.rollback()


async def test_another_workspaces_words_never_appear(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The leak test, written so it fails when the filter is absent.

    The same phrase exists in both workspaces. Asserting the asker's own row is present would pass
    with no tenant filter at all; asserting the *other* workspace's row is absent is the assertion
    that means something.
    """
    left, right = two_workspaces

    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, right.tenant_id):
            theirs = await _objective(session, right, f"Their {PHRASE} project")
            await session.commit()

    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            mine = await _objective(session, left, f"Our {PHRASE} project")
            context = await _context(session, left)

            found = await retrieval.search(session, context, PHRASE)
            ids = {source.id for source in found}

            assert mine in ids, "the asker's own objective is findable"
            assert theirs not in ids, "another workspace's objective must never be retrievable"
            #  And not by label either, in case an id were remapped somewhere.
            assert not any("Their" in source.label for source in found)
            await session.rollback()

    #  Clean up the row committed in the other workspace, so the next run measures the code.
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, right.tenant_id):
            row = await session.get(Objective, theirs)
            if row is not None:
                await session.delete(row)
                await session.commit()


async def test_an_empty_question_returns_nothing(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A blank question answered with the whole workspace has misunderstood what was asked.

    It is also the shape that quietly turns a Copilot into a data export: one empty string, every
    object the person may read, straight into a prompt.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            await _objective(session, left, f"Reduce {PHRASE}")
            context = await _context(session, left)

            assert await retrieval.search(session, context, "") == []
            assert await retrieval.search(session, context, "   ") == []
            await session.rollback()


async def test_the_number_of_sources_is_bounded(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A prompt stuffed with forty objects cites everything and grounds nothing.

    The bound is also a cost and latency ceiling on a request a person can repeat as fast as they
    can type.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            for index in range(20):
                await _objective(session, left, f"Reduce {PHRASE} {index}")
            context = await _context(session, left)

            found = await retrieval.search(session, context, PHRASE)
            assert len(found) <= retrieval.MAX_SOURCES
            #  Per kind as well, so one kind cannot crowd out the rest of the answer.
            assert (
                len([source for source in found if source.kind == "objective"])
                <= retrieval.PER_KIND
            )
            await session.rollback()


async def test_an_archived_object_is_not_retrieved(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Archived is off the chart, and a Copilot that quotes it is answering from last year.

    Archive never erases the row — the audit trail needs it — so this is the one place the
    distinction has to be made deliberately rather than by deletion.
    """
    from datetime import UTC, datetime

    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective_id = await _objective(session, left, f"Old {PHRASE} work")
            row = await session.get(Objective, objective_id)
            assert row is not None
            row.archived_at = datetime.now(UTC)
            await session.flush()

            context = await _context(session, left)
            found = await retrieval.search(session, context, PHRASE)

            assert objective_id not in {source.id for source in found}
            await session.rollback()
