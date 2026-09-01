"""Schedules that fire — the rules that decide whether "every day at 09:00" is true.

`recurrence.py` has its own unit tests for the calendar arithmetic. What is tested here is the
half that acts on it: the ledger that makes firing exactly-once, the policies applied at the
moment of firing, and the DST behaviour of the whole path — not just the calculation — because
the gate's exit criteria name it: *"a schedule fires correctly across a DST boundary."*

Every test drives `service.tick` with an explicit `now`, which is why the scheduler takes a clock
instead of reading one: a test can walk a schedule across the last Sunday of March without
waiting until March.

Seven properties:

* a due occurrence fires once, and a second tick — or a second worker — cannot fire it again;
* the run pins the version, and a pinned schedule keeps its version when the Job publishes a
  new one;
* a daily 02:30 across the spring-forward gap obeys `dst_policy` — `shift` runs at 03:30, once;
* an occurrence due while a run is still going obeys the overlap policy, with the reason recorded;
* a scheduler that was down obeys `missed_run_policy` — `run_once` owes exactly the latest;
* `requires_approval_per_run` holds the occurrence, and releasing it is refused without `approve`;
* a schedule that has never run owes nothing from before it existed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.runtime.models import Run
from uboss.modules.schedules import service
from uboss.modules.schedules.models import FiringState, ScheduleFiring

pytestmark = pytest.mark.anyio


async def _scheduled_job(
    session: AsyncSession,
    workspace: Workspace,
    *,
    timezone: str = "Asia/Kolkata",
    at_time: str = "09:00",
    frequency: str = "daily",
    overlap_policy: str = "skip",
    missed_run_policy: str = "skip",
    dst_policy: str = "shift",
    requires_approval: bool = False,
    last_run_at: datetime | None = None,
    pinned: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A published job with a switched-on schedule. Returns (job_id, schedule_id)."""
    job_id = uuid.uuid4()
    version_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO jobs (id, tenant_id, name, status, owner_membership_id)
            VALUES (:id, :tenant, 'Nightly close', 'draft', :owner)
            """
        ),
        {"id": job_id, "tenant": workspace.tenant_id, "owner": workspace.membership_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO job_versions (id, tenant_id, job_id, snapshot, name, correlation_id)
            VALUES (:id, :tenant, :job, CAST(:snapshot AS jsonb), 'Nightly close', 'test')
            """
        ),
        {
            "id": version_id,
            "tenant": workspace.tenant_id,
            "job": job_id,
            "snapshot": json.dumps(
                {
                    "steps": [
                        {"position": 1, "mode": "ai_agent", "what_exact_work": "Close it"}
                    ],
                    "assignment_rules": [],
                }
            ),
        },
    )
    await session.execute(
        text(
            "UPDATE jobs SET status = 'published', published_version_id = :v WHERE id = :id"
        ),
        {"v": version_id, "id": job_id},
    )
    schedule_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO job_schedules
                (id, tenant_id, job_id, auto_run, timezone, frequency, at_time,
                 overlap_policy, missed_run_policy, dst_policy, ambiguous_policy,
                 requires_approval_per_run, last_run_at, pinned_version_id,
                 created_by_membership_id)
            VALUES
                (:id, :tenant, :job, true, :tz, :freq, :at, :overlap, :missed, :dst,
                 'first', :hold, :last, :pinned, :who)
            """
        ),
        {
            "id": schedule_id,
            "tenant": workspace.tenant_id,
            "job": job_id,
            "tz": timezone,
            "freq": frequency,
            "at": at_time,
            "overlap": overlap_policy,
            "missed": missed_run_policy,
            "dst": dst_policy,
            "hold": requires_approval,
            "last": last_run_at,
            "pinned": version_id if pinned else None,
            "who": workspace.membership_id,
        },
    )
    return job_id, schedule_id


async def _firings(session: AsyncSession, schedule_id: uuid.UUID) -> list[ScheduleFiring]:
    return list(
        (
            await session.execute(
                select(ScheduleFiring)
                .where(ScheduleFiring.schedule_id == schedule_id)
                .order_by(ScheduleFiring.due_at)
            )
        )
        .scalars()
        .all()
    )


#  09:00 IST on the 2nd of March 2026 is 03:30 UTC. One minute past, the occurrence is owed.
IST_0900_UTC = datetime(2026, 3, 2, 3, 30, tzinfo=UTC)


async def test_a_due_occurrence_fires_once_and_only_once(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**The ledger is the scheduler.**

    The first tick claims the occurrence and starts a run. The second tick — which is also what a
    second worker looks like — finds the row already there and does nothing. Without this, every
    duplicated worker doubles every nightly job.
    """
    left, _right = two_workspaces
    factory = build_sessionmaker(owner_engine)

    #  **A session per pass, exactly as the worker does it.** The first version of this test ran
    #  both ticks in one uncommitted transaction, so the duplicate INSERT was never flushed a
    #  second time — and it hid a real bug: a rolled-back savepoint leaves the failed row
    #  *pending*, so the tick's own commit re-issues it and the whole transaction dies. It was
    #  found by running the worker twice against a live database, not by this suite.
    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            job_id, schedule_id = await _scheduled_job(
                session,
                left,
                last_run_at=IST_0900_UTC - timedelta(days=1),
            )
        await session.commit()

    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            first = await service.tick(
                session, tenant_id=left.tenant_id, now=IST_0900_UTC + timedelta(minutes=1)
            )
            assert len(first.started) == 1
        await session.commit()

    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            again = await service.tick(
                session, tenant_id=left.tenant_id, now=IST_0900_UTC + timedelta(minutes=2)
            )
            assert again.started == []
        #  The commit is the assertion: it raises if the refused insert was left pending.
        await session.commit()

    async with factory() as session, tenant_scope(session, left.tenant_id):
        firings = await _firings(session, schedule_id)
        assert len(firings) == 1
        assert firings[0].state == FiringState.STARTED
        runs = (
            (await session.execute(select(Run).where(Run.job_id == job_id)))
            .scalars()
            .all()
        )
        assert len(runs) == 1
        #  Scheduled, and by nobody: the audit answer for "who started this" is the
        #  schedule, not whoever configured it months ago.
        assert runs[0].trigger == "schedule"
        assert runs[0].started_by_membership_id is None


async def test_a_pinned_schedule_keeps_its_version(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Pinning means *this exact method runs until somebody moves it* — right for anything
    regulated. The Job publishing a newer version must not change what the schedule fires."""
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            job_id, schedule_id = await _scheduled_job(
                session,
                left,
                pinned=True,
                last_run_at=IST_0900_UTC - timedelta(days=1),
            )
            pinned_version = (
                await session.execute(
                    text("SELECT pinned_version_id FROM job_schedules WHERE id = :id"),
                    {"id": schedule_id},
                )
            ).scalar_one()

            #  The Job moves on: a second version is published after the schedule was pinned.
            newer = uuid.uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO job_versions (id, tenant_id, job_id, snapshot, name, correlation_id)
                    VALUES (:id, :tenant, :job,
                            CAST('{"steps": [{"position": 1, "mode": "ai_agent"}]}' AS jsonb),
                            'v2', 'test')
                    """
                ),
                {"id": newer, "tenant": left.tenant_id, "job": job_id},
            )
            await session.execute(
                text("UPDATE jobs SET published_version_id = :v WHERE id = :id"),
                {"v": newer, "id": job_id},
            )

            result = await service.tick(
                session, tenant_id=left.tenant_id, now=IST_0900_UTC + timedelta(minutes=1)
            )
            assert len(result.started) == 1
            run = (
                await session.execute(
                    select(Run).where(Run.id == result.started[0].run_id)
                )
            ).scalar_one()
            assert run.job_version_id == pinned_version
            assert run.job_version_id != newer


async def test_the_spring_forward_gap_obeys_the_dst_policy(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**The exit criterion, end to end.**

    America/New_York, 02:30 daily — the classic case, because the US gap is 02:00→03:00 and
    02:30 genuinely does not exist on 8 March 2026. (The first draft of this test used London,
    whose gap is 01:00→02:00, and its 02:30 exists on both sides — the code was right and the
    test was wrong, which is exactly why this is pinned to instants rather than to prose.)

    `shift` fires at the next real instant — 03:30 EDT — exactly once. The 7th fired at
    02:30 EST and the shifted 8th at 03:30 EDT, which are the *same* UTC instant 07:30 a day
    apart; the 9th at 02:30 EDT is 06:30 UTC. Same local intent, different UTC — the whole
    reason the walk happens in local time.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            _job_id, schedule_id = await _scheduled_job(
                session,
                left,
                timezone="America/New_York",
                at_time="02:30",
                dst_policy="shift",
                missed_run_policy="run_all",
                #  Last ran on the 6th at 02:30 EST.
                last_run_at=datetime(2026, 3, 6, 7, 30, tzinfo=UTC),
            )

            #  The tick happens on the 9th, shortly after that morning's slot.
            await service.tick(
                session,
                tenant_id=left.tenant_id,
                now=datetime(2026, 3, 9, 7, 0, tzinfo=UTC),
                start_run=False,
            )

            firings = await _firings(session, schedule_id)
            instants = [firing.due_at.astimezone(UTC) for firing in firings]
            assert instants == [
                #  Saturday the 7th: 02:30 EST.
                datetime(2026, 3, 7, 7, 30, tzinfo=UTC),
                #  Sunday the 8th: no 02:30 exists; shifted to 03:30 EDT — the same UTC instant
                #  as yesterday's, one local hour later.
                datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
                #  Monday the 9th: 02:30 EDT.
                datetime(2026, 3, 9, 6, 30, tzinfo=UTC),
            ]
            #  Exactly once each — the gap day did not double and did not vanish.
            assert len({instant.date() for instant in instants}) == 3


async def test_an_overlapping_occurrence_is_skipped_with_the_reason_recorded(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The overlap policy is checked against the Job's **live runs** — a run started by hand two
    minutes ago counts — and the skip carries a sentence, because "it did not run" is the answer
    nobody can act on."""
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            job_id, schedule_id = await _scheduled_job(
                session,
                left,
                overlap_policy="skip",
                last_run_at=IST_0900_UTC - timedelta(days=1),
            )
            #  A run of this job is still going — started by hand, which must count.
            await session.execute(
                text(
                    """
                    INSERT INTO runs (tenant_id, job_id, job_version_id, workflow_id,
                                      state, trigger, correlation_id)
                    SELECT :tenant, :job, published_version_id, 'wf-test', 'running',
                           'manual', 'test'
                    FROM jobs WHERE id = :job
                    """
                ),
                {"tenant": left.tenant_id, "job": job_id},
            )

            result = await service.tick(
                session, tenant_id=left.tenant_id, now=IST_0900_UTC + timedelta(minutes=1)
            )

            assert result.started == []
            firings = await _firings(session, schedule_id)
            assert len(firings) == 1
            assert firings[0].state == FiringState.SKIPPED
            assert firings[0].detail is not None
            assert "still going" in firings[0].detail


async def test_missed_runs_obey_the_policy(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Down for three days, `run_once`: exactly the latest slot is owed, marked `was_missed`.

    Running the oldest would produce a report about a week nobody is asking about any more, and
    running all three is a different policy somebody can choose.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            _job_id, schedule_id = await _scheduled_job(
                session,
                left,
                missed_run_policy="run_once",
                last_run_at=IST_0900_UTC - timedelta(days=3),
            )

            result = await service.tick(
                session,
                tenant_id=left.tenant_id,
                now=IST_0900_UTC + timedelta(hours=2),
                start_run=False,
            )

            #  One slot, the latest, and it says it was made up for.
            assert result.considered == 1
            firings = await _firings(session, schedule_id)
            assert len(firings) == 1
            assert firings[0].due_at.astimezone(UTC) == IST_0900_UTC
            assert firings[0].was_missed is True


async def test_requires_approval_holds_the_occurrence_for_a_person(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§8's per-run approval. Held visibly — `awaiting_approval`, not skipped — because a run
    that quietly did not happen is indistinguishable from a scheduler that is broken. Releasing
    an occurrence that is not held is refused: it would be a second run of one occurrence."""
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            _job_id, schedule_id = await _scheduled_job(
                session,
                left,
                requires_approval=True,
                last_run_at=IST_0900_UTC - timedelta(days=1),
            )

            result = await service.tick(
                session, tenant_id=left.tenant_id, now=IST_0900_UTC + timedelta(minutes=1)
            )

            assert result.started == []
            assert result.awaiting == 1
            firings = await _firings(session, schedule_id)
            assert firings[0].state == FiringState.AWAITING_APPROVAL

            from tests.integration.test_tasks import _context

            deciding = await _context(session, left)
            started = await service.release(session, deciding, firings[0])
            assert firings[0].state == FiringState.STARTED
            assert started.run_id is not None

            #  Releasing it again reports that it is already running, and names the same run.
            #
            #  It used to raise "That occurrence is not waiting to be released" — true of the
            #  state and false about the request, because the ordinary way to arrive here is a
            #  release that worked and then lost its connection. The route commits mid-request so
            #  its `Idempotency-Key` cannot be replayed from a stored response; the operation
            #  carries its own idempotence instead, and the ledger's unique constraint is still
            #  what guarantees exactly-once.
            with pytest.raises(service.AlreadyReleased) as again:
                await service.release(session, deciding, firings[0])
            assert again.value.run_id == started.run_id
            assert firings[0].state == FiringState.STARTED


async def test_a_schedule_that_has_never_run_owes_no_history(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Switched on today, `run_all`: it owes nothing from before it existed.

    The alternative fires a month of runs at three in the morning the first time a worker sees a
    schedule somebody created a month ago — the surprise nobody wants twice.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            _job_id, schedule_id = await _scheduled_job(
                session,
                left,
                missed_run_policy="run_all",
                last_run_at=None,
            )

            #  Five minutes before today's slot: nothing is due yet, and nothing historical is
            #  invented.
            result = await service.tick(
                session,
                tenant_id=left.tenant_id,
                now=IST_0900_UTC - timedelta(minutes=5),
                start_run=False,
            )
            assert result.considered == 0
            assert await _firings(session, schedule_id) == []
