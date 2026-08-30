"""When a schedule actually fires, in a real timezone, across the days that do not behave.

PLAN §8: *"If WHEN repeats, ask Auto-run Yes/No. If enabled, require timezone, recurrence preview,
DST, overlap, missed-run policy, calendar, concurrency, pinned versions and approval behavior."*

This module is the *when*. It is pure — no database, no clock of its own — because the same
function has to produce the preview a person reads and the times the runtime fires, and two
implementations of "next Tuesday at 09:00" is one of them being wrong twice a year.

**Local time is the intent; UTC is the storage.** "Every weekday at 09:00" means nine in the
morning where the team is, on both sides of a clock change. Storing a UTC time and converting for
display gets this exactly backwards: it keeps the instant and moves the meeting.

**Two days a year have no 02:30, and two have it twice.** Neither is hypothetical — a daily 02:30
job in Europe or North America meets both every year. The policies below are the only honest
answers, and each is a choice somebody makes rather than a default this code picks:

* `SKIP` — the run does not happen on the day the hour does not exist.
* `SHIFT` — it happens at the next real instant, which is 03:30 that day.
* On the repeated hour, `FIRST` fires once (the usual intent) and `BOTH` fires twice (right for
  something that genuinely counts hours, like a meter read).

India, where this product is first deployed, has no daylight saving at all — which is exactly why
this needs testing rather than trusting: nobody here would notice it break.
"""

from __future__ import annotations

import calendar
import enum
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from uboss.core.errors import ValidationFailed


class Frequency(enum.StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class DstPolicy(enum.StrEnum):
    """What to do on the two days a local time is missing or repeated."""

    #: The run does not happen on the day the hour does not exist. Right for anything where
    #: running late is worse than not running.
    SKIP = "skip"
    #: It happens at the next real instant. Right for almost everything else.
    SHIFT = "shift"


class AmbiguousPolicy(enum.StrEnum):
    """Which of the two 02:30s to use when the clock goes back."""

    #: Once, at the first occurrence. What people mean by "at 02:30".
    FIRST = "first"
    #: Both. Right for something counting hours rather than doing a daily task.
    BOTH = "both"


class MissedRunPolicy(enum.StrEnum):
    """What to do about runs that should have happened while nothing was running.

    A worker that was down for a weekend comes back to a decision, and it is not the code's to
    make: a nightly report probably wants only the latest, and a nightly reconciliation probably
    wants every one of them.
    """

    #: Forget them. The next run is the next scheduled one.
    SKIP = "skip"
    #: Run once, now, to catch up.
    RUN_ONCE = "run_once"
    #: Run every missed occurrence, oldest first.
    RUN_ALL = "run_all"


class OverlapPolicy(enum.StrEnum):
    """What to do when a run is still going and the next one is due."""

    #: Do not start it. Right when a second copy would fight the first over the same records.
    SKIP = "skip"
    #: Start it when the running one finishes.
    QUEUE = "queue"
    #: Start it anyway, up to the concurrency limit.
    ALLOW = "allow"


#: Monday is 0, matching `datetime.weekday()`.
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: A preview longer than this is not a preview. It is also the ceiling on a catch-up sweep.
MAX_OCCURRENCES = 100


@dataclass(frozen=True, slots=True)
class Recurrence:
    """A repeating time, in somebody's own timezone."""

    frequency: Frequency
    #: Every `interval` hours/days/weeks/months. 1 is the usual case.
    interval: int
    #: The local time of day. Ignored for `HOURLY`, which fires on the hour from `at_time`.
    at_time: time
    #: IANA, always. "IST" is three different zones and "+05:30" stops being true the moment a
    #: government changes its mind — which they do, with weeks of notice.
    timezone: str
    #: For `WEEKLY`: which days. Empty means the weekday of the start date.
    weekdays: tuple[int, ...] = ()
    #: For `MONTHLY`: which day of the month. 31 in a 30-day month falls back to the last day,
    #: because "the 31st" plainly means "the end of the month" to the person who wrote it.
    monthday: int | None = None
    dst: DstPolicy = DstPolicy.SHIFT
    ambiguous: AmbiguousPolicy = AmbiguousPolicy.FIRST
    #: Days the job must not run — a holiday calendar, in the schedule's own timezone. §8 asks
    #: for a calendar; this is it, and it is a list rather than a country code because every
    #: company's shutdown days differ from every other's.
    skip_dates: tuple[date, ...] = ()
    #: When true, a run landing on a Saturday or Sunday is skipped.
    weekdays_only: bool = False

    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as cause:
            raise ValidationFailed(
                f"“{self.timezone}” is not a timezone this system knows. Use an IANA name such "
                "as Asia/Kolkata."
            ) from cause


def validate(recurrence: Recurrence) -> None:
    """Refuse a recurrence that could never fire, at the point somebody writes it.

    Each of these produces a schedule that looks configured and does nothing, which is the worst
    outcome available: nobody notices until the report they expected never arrives.
    """
    recurrence.zone()

    if recurrence.interval < 1 or recurrence.interval > 999:
        raise ValidationFailed("The interval has to be between 1 and 999.")

    if (
        recurrence.frequency == Frequency.WEEKLY
        and recurrence.weekdays
        and any(day < 0 or day > 6 for day in recurrence.weekdays)
    ):
        raise ValidationFailed("A weekday has to be Monday through Sunday.")

    if recurrence.frequency == Frequency.MONTHLY:
        if recurrence.monthday is None:
            raise ValidationFailed("A monthly schedule needs a day of the month.")
        if recurrence.monthday < 1 or recurrence.monthday > 31:
            raise ValidationFailed("The day of the month has to be between 1 and 31.")

    if recurrence.weekdays_only and recurrence.frequency == Frequency.WEEKLY:
        chosen = set(recurrence.weekdays or range(7))
        if not chosen & {0, 1, 2, 3, 4}:
            raise ValidationFailed(
                "This schedule only runs at weekends but is set to skip them, so it would never "
                "run at all."
            )


def occurrences(
    recurrence: Recurrence,
    *,
    after: datetime,
    count: int = 10,
    until: datetime | None = None,
) -> list[datetime]:
    """The next `count` firing instants, in UTC, strictly after `after`.

    The walk happens in local dates and local times, and only becomes an instant at the end. Doing
    it the other way — adding 24 hours to a UTC timestamp — is what makes a "daily 09:00" job
    drift to 08:00 for half the year.
    """
    validate(recurrence)
    if count < 1:
        return []
    count = min(count, MAX_OCCURRENCES)

    zone = recurrence.zone()
    local_after = after.astimezone(zone)
    found: list[datetime] = []

    if recurrence.frequency == Frequency.HOURLY:
        return _hourly(recurrence, zone, local_after, count, until)

    #  Start a little before, so an occurrence earlier today is not missed, and walk forward.
    cursor = local_after.date() - timedelta(days=1)
    #  A generous ceiling on the search: a monthly schedule with a 31st and a skip calendar can
    #  legitimately pass hundreds of days between runs.
    for _ in range(4000):
        if len(found) >= count:
            break
        if _matches(recurrence, cursor, local_after.date()):
            for moment in _instants(recurrence, zone, cursor):
                if moment <= after:
                    continue
                if until is not None and moment > until:
                    return found
                found.append(moment)
                if len(found) >= count:
                    break
        cursor += timedelta(days=1)

    return found


def _hourly(
    recurrence: Recurrence,
    zone: ZoneInfo,
    local_after: datetime,
    count: int,
    until: datetime | None,
) -> list[datetime]:
    """Every `interval` hours, from the minute in `at_time`.

    Walked in UTC on purpose, and this is the one place that is right: an hourly schedule means
    "every hour of elapsed time". A clock change makes the local hour jump, and that is correct —
    the gap between two runs stays an hour.
    """
    found: list[datetime] = []
    cursor = local_after.replace(
        minute=recurrence.at_time.minute, second=0, microsecond=0
    ).astimezone(UTC)

    while len(found) < count:
        cursor += timedelta(hours=recurrence.interval)
        if until is not None and cursor > until:
            break
        local = cursor.astimezone(zone)
        if _blocked(recurrence, local.date()):
            continue
        found.append(cursor)
    return found


def _matches(recurrence: Recurrence, day: date, from_day: date) -> bool:
    """Whether the recurrence lands on this local date."""
    if _blocked(recurrence, day):
        return False

    match recurrence.frequency:
        case Frequency.DAILY:
            return (day - from_day).days % recurrence.interval == 0 or recurrence.interval == 1
        case Frequency.WEEKLY:
            wanted = recurrence.weekdays or (from_day.weekday(),)
            if day.weekday() not in wanted:
                return False
            weeks = ((day - from_day).days + from_day.weekday()) // 7
            return weeks % recurrence.interval == 0 or recurrence.interval == 1
        case Frequency.MONTHLY:
            assert recurrence.monthday is not None
            last = calendar.monthrange(day.year, day.month)[1]
            #  "The 31st" in a 30-day month means the end of the month. Skipping those months
            #  entirely is the other reading, and it is the one that surprises people.
            target = min(recurrence.monthday, last)
            if day.day != target:
                return False
            months = (day.year - from_day.year) * 12 + (day.month - from_day.month)
            return months % recurrence.interval == 0 or recurrence.interval == 1
        case Frequency.HOURLY:  # pragma: no cover - handled above
            return True


def _blocked(recurrence: Recurrence, day: date) -> bool:
    if recurrence.weekdays_only and day.weekday() >= 5:
        return True
    return day in recurrence.skip_dates


def _instants(
    recurrence: Recurrence, zone: ZoneInfo, day: date
) -> list[datetime]:
    """The UTC instant or instants for this local date, handling the two awkward days.

    `fold` is how Python distinguishes the two 02:30s on the day a clock goes back: `fold=0` is
    the first, `fold=1` is the second. A local time that does not exist is detected by converting
    to UTC and back — a real local time survives the round trip, and a missing one does not.
    """
    naive = datetime.combine(day, recurrence.at_time)
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)

    #  Nonexistent: the two folds give the same UTC instant *and* converting back lands on a
    #  different local time. That is the spring-forward gap.
    if first.utcoffset() != second.utcoffset() and first.astimezone(UTC).astimezone(
        zone
    ).replace(tzinfo=None) != naive:
        if recurrence.dst == DstPolicy.SKIP:
            return []
        #  Shift forward to the first real instant after the gap. The gap's size is the
        #  difference between the offsets on either side of it — an hour nearly everywhere, and
        #  thirty minutes in the few zones that do it by halves. Adding it to a local time
        #  inside the gap lands exactly on the far edge.
        before = first.utcoffset()
        after_offset = second.utcoffset()
        assert before is not None and after_offset is not None
        return [(naive + (after_offset - before)).replace(tzinfo=zone).astimezone(UTC)]

    #  Ambiguous: two distinct instants for one local time. That is the autumn overlap.
    if first.astimezone(UTC) != second.astimezone(UTC):
        if recurrence.ambiguous == AmbiguousPolicy.BOTH:
            return [first.astimezone(UTC), second.astimezone(UTC)]
        return [first.astimezone(UTC)]

    return [first.astimezone(UTC)]


def missed(
    recurrence: Recurrence,
    *,
    last_run_at: datetime | None,
    now: datetime,
    policy: MissedRunPolicy,
) -> list[datetime]:
    """Which runs to make up for, given when the schedule last fired.

    Called when something comes back after being down. `last_run_at` of `None` means it has never
    run, and nothing is owed — a schedule created last month does not owe a month of runs the
    moment it is switched on, which is a surprise nobody wants at three in the morning.
    """
    if last_run_at is None or policy == MissedRunPolicy.SKIP:
        return []

    due = occurrences(
        recurrence, after=last_run_at, count=MAX_OCCURRENCES, until=now
    )
    if not due:
        return []
    if policy == MissedRunPolicy.RUN_ONCE:
        #  The most recent one. Running the oldest would produce a report about a week nobody is
        #  asking about any more.
        return [due[-1]]
    return due
