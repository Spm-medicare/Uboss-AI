"""When a schedule actually fires, including on the four days a year that misbehave.

Gate 4's exit check asks that a schedule *"previews correctly across a DST boundary"*. Most of
this suite needs no database at all, because `recurrence` is pure — which is the point of keeping
it that way: the preview a person reads and the times the runtime fires come from one function,
and it can be tested against real zones without a server.

India has no daylight saving, so nobody working on this product would notice these break. That is
precisely why they are here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy import service as hierarchy
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.jobs import recurrence as rec
from uboss.modules.jobs import schedule_service, service
from uboss.modules.jobs.schemas import JobCreate

pytestmark = pytest.mark.anyio

NEW_YORK = "America/New_York"
LONDON = "Europe/London"
KOLKATA = "Asia/Kolkata"


def _local(moments: list[datetime], zone: str) -> list[str]:
    tz = ZoneInfo(zone)
    return [moment.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z") for moment in moments]


# ---------------------------------------------------------------- the days that misbehave


def test_a_missing_local_time_shifts_past_the_gap() -> None:
    """On 8 March 2026 New York goes 02:00 → 03:00, so 02:30 does not exist.

    `SHIFT` runs at the first real instant after the gap. The first version of this got the
    arithmetic backwards and ran at 01:30 — *before* the gap — which is the kind of thing nobody
    notices until a report is an hour early once a year.
    """
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY,
        interval=1,
        at_time=time(2, 30),
        timezone=NEW_YORK,
        dst=rec.DstPolicy.SHIFT,
    )
    moments = rec.occurrences(
        daily, after=datetime(2026, 3, 6, 12, 0, tzinfo=UTC), count=4
    )

    assert _local(moments, NEW_YORK) == [
        "2026-03-07 02:30 EST",
        "2026-03-08 03:30 EDT",
        "2026-03-09 02:30 EDT",
        "2026-03-10 02:30 EDT",
    ]


def test_a_missing_local_time_can_be_skipped_instead() -> None:
    """Right for anything where running late is worse than not running."""
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY,
        interval=1,
        at_time=time(2, 30),
        timezone=NEW_YORK,
        dst=rec.DstPolicy.SKIP,
    )
    moments = rec.occurrences(
        daily, after=datetime(2026, 3, 6, 12, 0, tzinfo=UTC), count=3
    )

    #  The 8th is simply absent.
    assert _local(moments, NEW_YORK) == [
        "2026-03-07 02:30 EST",
        "2026-03-09 02:30 EDT",
        "2026-03-10 02:30 EDT",
    ]


def test_a_repeated_local_time_fires_once_by_default() -> None:
    """On 1 November 2026 New York has 01:30 twice. Once is what people mean by "at 01:30"."""
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY,
        interval=1,
        at_time=time(1, 30),
        timezone=NEW_YORK,
        ambiguous=rec.AmbiguousPolicy.FIRST,
    )
    moments = rec.occurrences(
        daily, after=datetime(2026, 10, 31, 12, 0, tzinfo=UTC), count=2
    )

    the_day = date(2026, 11, 1)
    on_the_day = [m for m in moments if m.astimezone(ZoneInfo(NEW_YORK)).date() == the_day]
    assert len(on_the_day) == 1
    assert _local(on_the_day, NEW_YORK) == ["2026-11-01 01:30 EDT"]


def test_a_repeated_local_time_can_fire_twice() -> None:
    """Right for something counting hours — a meter read — rather than doing a daily task."""
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY,
        interval=1,
        at_time=time(1, 30),
        timezone=NEW_YORK,
        ambiguous=rec.AmbiguousPolicy.BOTH,
    )
    moments = rec.occurrences(
        daily, after=datetime(2026, 10, 31, 12, 0, tzinfo=UTC), count=3
    )

    assert _local(moments, NEW_YORK)[:2] == [
        "2026-11-01 01:30 EDT",
        "2026-11-01 01:30 EST",
    ]
    #  Two distinct instants an hour apart, despite reading the same on a clock.
    assert moments[1] - moments[0] == timedelta(hours=1)


def test_a_daily_time_stays_put_across_a_clock_change() -> None:
    """"Every day at 09:00" means nine in the morning on both sides of a clock change.

    In UTC the instant moves by an hour, and that is correct — it is the local time the person
    meant. Storing a UTC time and converting for display gets this exactly backwards: it keeps
    the instant and moves the meeting.
    """
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY, interval=1, at_time=time(9, 0), timezone=LONDON
    )
    moments = rec.occurrences(
        daily, after=datetime(2026, 3, 27, 0, 0, tzinfo=UTC), count=4
    )

    local = _local(moments, LONDON)
    assert all(entry.endswith("09:00 GMT") or entry.endswith("09:00 BST") for entry in local)
    #  The UTC hour changes because the local one did not.
    assert {moment.hour for moment in moments} == {8, 9}


def test_a_zone_without_daylight_saving_never_moves() -> None:
    """Asia/Kolkata is the deployment zone. 09:00 there is 03:30 UTC, all year."""
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY, interval=1, at_time=time(9, 0), timezone=KOLKATA
    )
    moments = rec.occurrences(
        daily, after=datetime(2026, 3, 6, 0, 0, tzinfo=UTC), count=5
    )

    assert {(moment.hour, moment.minute) for moment in moments} == {(3, 30)}


# ------------------------------------------------------------------- the ordinary cases


def test_weekly_fires_on_the_days_it_was_given() -> None:
    weekly = rec.Recurrence(
        frequency=rec.Frequency.WEEKLY,
        interval=1,
        at_time=time(9, 0),
        timezone=KOLKATA,
        weekdays=(0, 2, 4),
    )
    moments = rec.occurrences(
        weekly, after=datetime(2026, 8, 30, 0, 0, tzinfo=UTC), count=4
    )

    days = {moment.astimezone(ZoneInfo(KOLKATA)).weekday() for moment in moments}
    assert days <= {0, 2, 4}


def test_the_thirty_first_means_the_end_of_a_short_month() -> None:
    """"The 31st" plainly means the end of the month to whoever wrote it.

    Skipping February entirely is the other reading, and it is the one that surprises people —
    a monthly reconciliation that silently misses a month is worse than one that runs on the 28th.
    """
    monthly = rec.Recurrence(
        frequency=rec.Frequency.MONTHLY,
        interval=1,
        at_time=time(18, 0),
        timezone=KOLKATA,
        monthday=31,
    )
    moments = rec.occurrences(
        monthly, after=datetime(2026, 1, 1, 0, 0, tzinfo=UTC), count=4
    )

    days = [moment.astimezone(ZoneInfo(KOLKATA)).strftime("%m-%d") for moment in moments]
    assert days == ["01-31", "02-28", "03-31", "04-30"]


def test_a_holiday_calendar_skips_those_days() -> None:
    """§8 asks for a calendar. A list of dates, because every company's shutdown differs."""
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY,
        interval=1,
        at_time=time(9, 0),
        timezone=KOLKATA,
        skip_dates=(date(2026, 9, 2), date(2026, 9, 3)),
    )
    moments = rec.occurrences(
        daily, after=datetime(2026, 8, 31, 12, 0, tzinfo=UTC), count=3
    )

    days = [moment.astimezone(ZoneInfo(KOLKATA)).strftime("%m-%d") for moment in moments]
    assert days == ["09-01", "09-04", "09-05"]


def test_weekdays_only_skips_the_weekend() -> None:
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY,
        interval=1,
        at_time=time(9, 0),
        timezone=KOLKATA,
        weekdays_only=True,
    )
    moments = rec.occurrences(
        daily, after=datetime(2026, 9, 3, 12, 0, tzinfo=UTC), count=3
    )

    days = [moment.astimezone(ZoneInfo(KOLKATA)).weekday() for moment in moments]
    assert all(day < 5 for day in days)


def test_a_schedule_that_could_never_fire_is_refused() -> None:
    """It would look configured and do nothing, which is the worst outcome available."""
    with pytest.raises(ValidationFailed) as refused:
        rec.validate(
            rec.Recurrence(
                frequency=rec.Frequency.WEEKLY,
                interval=1,
                at_time=time(9, 0),
                timezone=KOLKATA,
                weekdays=(5, 6),
                weekdays_only=True,
            )
        )
    assert "never run at all" in str(refused.value)


def test_an_offset_is_not_a_timezone() -> None:
    """`+05:30` stops being true the moment a government changes its mind — and they do."""
    with pytest.raises(ValidationFailed) as refused:
        rec.validate(
            rec.Recurrence(
                frequency=rec.Frequency.DAILY,
                interval=1,
                at_time=time(9, 0),
                timezone="+05:30",
            )
        )
    assert "IANA" in str(refused.value)


# ---------------------------------------------------------------------- missed runs


def test_nothing_is_owed_before_the_first_run() -> None:
    """A schedule switched on today does not owe a month of runs.

    Which is a surprise nobody wants at three in the morning, and the reason `last_run_at` of
    `None` means nothing rather than everything.
    """
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY, interval=1, at_time=time(9, 0), timezone=KOLKATA
    )
    assert (
        rec.missed(
            daily,
            last_run_at=None,
            now=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
            policy=rec.MissedRunPolicy.RUN_ALL,
        )
        == []
    )


def test_catching_up_once_runs_the_most_recent_occurrence() -> None:
    """Running the oldest would produce a report about a week nobody is asking about."""
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY, interval=1, at_time=time(9, 0), timezone=KOLKATA
    )
    owed = rec.missed(
        daily,
        last_run_at=datetime(2026, 9, 1, 3, 30, tzinfo=UTC),
        now=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        policy=rec.MissedRunPolicy.RUN_ONCE,
    )

    assert len(owed) == 1
    assert owed[0].astimezone(ZoneInfo(KOLKATA)).strftime("%m-%d") == "09-05"


def test_catching_up_fully_runs_every_missed_occurrence_oldest_first() -> None:
    daily = rec.Recurrence(
        frequency=rec.Frequency.DAILY, interval=1, at_time=time(9, 0), timezone=KOLKATA
    )
    owed = rec.missed(
        daily,
        last_run_at=datetime(2026, 9, 1, 3, 30, tzinfo=UTC),
        now=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        policy=rec.MissedRunPolicy.RUN_ALL,
    )

    days = [moment.astimezone(ZoneInfo(KOLKATA)).strftime("%m-%d") for moment in owed]
    assert days == ["09-02", "09-03", "09-04", "09-05"]


# --------------------------------------------------------------- through the service


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = hierarchy._now()
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=workspace.membership_id,
        session_id=uuid.uuid4(),
        email="person@test",
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        org_node_id=membership.org_node_id,
        policy_grants=ceiling,
        step_up_at=now,
        step_up_expires_at=now + timedelta(minutes=10),
    )


async def test_saving_a_schedule_computes_when_it_next_runs(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Recomputed on every save.

    A stale `next_run_at` is a schedule that fires at the old time after somebody changed it,
    which is the failure people find hardest to believe.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Nightly reconciliation"))
        await session.flush()

        schedule = await schedule_service.set_schedule(
            session,
            context,
            job.id,
            {
                "auto_run": True,
                "timezone": KOLKATA,
                "frequency": "daily",
                "at_time": time(23, 0),
            },
            expected_version=None,
        )
        await session.flush()

        assert schedule.next_run_at is not None
        assert schedule.next_run_at > hierarchy._now()
        assert schedule.next_run_at.astimezone(ZoneInfo(KOLKATA)).hour == 23
        await session.rollback()


async def test_the_preview_says_what_a_person_should_know(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Notes, never blockers. Each is a configuration somebody might mean.

    The difference between meaning it and being surprised by it is whether they read it first.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Hourly sync"))
        await session.flush()

        await schedule_service.set_schedule(
            session,
            context,
            job.id,
            {
                "auto_run": False,
                "timezone": KOLKATA,
                "frequency": "daily",
                "at_time": time(9, 0),
                "missed_run_policy": "run_all",
            },
            expected_version=None,
        )
        await session.flush()

        result = await schedule_service.preview(session, context, job.id, count=3)
        joined = " ".join(result.notes)
        assert "Auto-run is off" in joined
        assert "every missed occurrence" in joined
        #  And it says nothing is pinned, which is the setting people forget.
        assert "Pin a version" in joined
        assert len(result.occurrences) == 3
        await session.rollback()


async def test_the_preview_warns_when_the_clocks_change_inside_the_window(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The one time the gap between two runs is not what the interval says."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="London report"))
        await session.flush()

        await schedule_service.set_schedule(
            session,
            context,
            job.id,
            {
                "auto_run": True,
                "timezone": LONDON,
                "frequency": "daily",
                "at_time": time(9, 0),
            },
            expected_version=None,
        )
        await session.flush()

        result = await schedule_service.preview(
            session,
            context,
            job.id,
            count=6,
            from_time=datetime(2026, 3, 27, 0, 0, tzinfo=UTC),
        )
        assert any("clocks change" in note for note in result.notes)
        await session.rollback()


async def test_a_monthly_schedule_needs_a_day_of_the_month(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Refused at the point somebody writes it, not when the report never arrives."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Monthly close"))
        await session.flush()

        with pytest.raises(ValidationFailed):
            await schedule_service.set_schedule(
                session,
                context,
                job.id,
                {
                    "auto_run": True,
                    "timezone": KOLKATA,
                    "frequency": "monthly",
                    "at_time": time(18, 0),
                },
                expected_version=None,
            )
        await session.rollback()


async def test_a_job_has_at_most_one_schedule(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Saving again replaces it rather than adding a second.

    Two schedules on one job would each claim the same `last_run_at`, and their missed-run
    policies would fight over what to catch up.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        job = await service.create(session, context, JobCreate(name="Sync"))
        await session.flush()

        first = await schedule_service.set_schedule(
            session,
            context,
            job.id,
            {"timezone": KOLKATA, "frequency": "daily", "at_time": time(9, 0)},
            expected_version=None,
        )
        await session.flush()

        second = await schedule_service.set_schedule(
            session,
            context,
            job.id,
            {"timezone": KOLKATA, "frequency": "daily", "at_time": time(10, 0)},
            expected_version=first.version,
        )
        await session.flush()

        assert second.id == first.id
        assert second.at_time == time(10, 0)
        await session.rollback()
