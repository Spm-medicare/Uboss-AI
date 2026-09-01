"""The three schedule paths that changed something with no guard, or lied about it.

A schedule decides when a job runs by itself, on whose timezone, and against which published
version. Every other state change in this system carries `expected_version`; these did not.

* **Replacing** one checked the version only when a version was sent, so a caller that omitted the
  field overwrote the recurrence, the timezone and the pinned version with no conflict and no sign
  of what had been there. Creating the first one genuinely has no version to send, so the rule has
  to be by case rather than a blanket requirement — which is what these first two tests pin.
* **Removing** one took no version at all: the single destructive operation on a schedule, with no
  optimistic guard.
* **Releasing** a held occurrence refused anything not `awaiting_approval`, so a release that
  succeeded and then lost its connection came back, on retry, as *"That occurrence is not waiting
  to be released"* — a refusal about work that had been done. That route commits mid-request so its
  `Idempotency-Key` cannot be replayed from a stored response, which is why the idempotence has to
  live in the operation. Covered in `test_schedule_firing.py`, beside the release it belongs to.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import Workspace
from tests.integration.test_job_publish import _complete_job, _context
from uboss.core.errors import Conflict
from uboss.db.base import build_sessionmaker
from uboss.modules.jobs import schedule_service


def _schedule(**overrides: object) -> dict[str, object]:
    """A schedule that would actually fire, so a refusal is about the guard and nothing else."""
    return {
        "auto_run": True,
        "timezone": "Asia/Kolkata",
        "frequency": "daily",
        "interval": 1,
        "at_time": "09:00",
        "requires_approval_per_run": False,
        "catch_up_policy": "skip",
        "overlap_policy": "skip",
        "skip_dates": [],
        "pinned_version_id": None,
        **overrides,
    }


async def test_the_first_schedule_needs_no_version(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """There is nothing to overwrite, so there is nothing to guard against."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)

        created = await schedule_service.set_schedule(
            session, context, job_id, _schedule(), expected_version=None
        )
        await session.flush()
        assert created.timezone == "Asia/Kolkata"
        await session.rollback()


async def test_replacing_a_schedule_without_a_version_is_refused(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The hole: a second write with no version silently replaced the first.

    Asserts the refusal *and* that the schedule still says what it said, because a guard that
    raises after writing is worse than no guard at all.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)

        await schedule_service.set_schedule(
            session, context, job_id, _schedule(), expected_version=None
        )
        await session.flush()

        with pytest.raises(Conflict) as refused:
            await schedule_service.set_schedule(
                session,
                context,
                job_id,
                _schedule(timezone="America/New_York", at_time="17:00"),
                expected_version=None,
            )
        assert "already has a schedule" in str(refused.value)

        still = await schedule_service.read(session, context, job_id)
        assert still is not None
        assert still.timezone == "Asia/Kolkata", "the refusal must not have written anyway"
        await session.rollback()


async def test_replacing_a_schedule_with_the_right_version_works(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The other direction, so the guard is not simply a wall."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)

        created = await schedule_service.set_schedule(
            session, context, job_id, _schedule(), expected_version=None
        )
        await session.flush()
        #  Read into an int before the next write. `set_schedule` returns the live row and
        #  increments it in place, so holding the object and reading `.version` afterwards reads
        #  the *new* number — which is how the stale-version case below quietly passed at first.
        first = created.version

        replaced = await schedule_service.set_schedule(
            session,
            context,
            job_id,
            _schedule(timezone="America/New_York"),
            expected_version=first,
        )
        await session.flush()
        assert replaced.timezone == "America/New_York"
        assert replaced.version == first + 1

        #  And the version that has just been spent is refused, which is the ordinary conflict.
        with pytest.raises(Conflict):
            await schedule_service.set_schedule(
                session,
                context,
                job_id,
                _schedule(timezone="Europe/London"),
                expected_version=first,
            )
        await session.rollback()


async def test_removing_a_schedule_is_guarded_by_its_version(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """A stale screen must not delete a recurrence somebody has just rewritten."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)

        created = await schedule_service.set_schedule(
            session, context, job_id, _schedule(), expected_version=None
        )
        await session.flush()
        stale = created.version  # read before the next write bumps it in place

        await schedule_service.set_schedule(
            session,
            context,
            job_id,
            _schedule(timezone="America/New_York"),
            expected_version=stale,
        )
        await session.flush()

        with pytest.raises(Conflict):
            await schedule_service.remove(
                session, context, job_id, expected_version=stale
            )

        survives = await schedule_service.read(session, context, job_id)
        assert survives is not None, "the refused removal must not have deleted it"

        await schedule_service.remove(
            session, context, job_id, expected_version=survives.version
        )
        await session.flush()
        assert await schedule_service.read(session, context, job_id) is None
        await session.rollback()


async def test_removing_a_schedule_that_is_already_gone_is_not_an_error(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The caller asked for it not to exist, and it does not exist."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)

        await schedule_service.remove(session, context, job_id, expected_version=1)
        await session.rollback()
