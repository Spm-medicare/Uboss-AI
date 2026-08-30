"""Setting a job's schedule, and previewing what it would actually do.

The preview is the point. PLAN §8 asks for a *recurrence preview* by name, and the reason is that
nobody can read `interval=2, weekdays=[1,3], dst=shift` and know when it fires. A list of the next
ten instants, in the reader's own words, is the only honest way to show a schedule — and it is
produced by the same function the runtime will use, so what somebody approves is what happens.

**Nothing here fires anything.** The runtime that does is Gate 7. This decides *when*, records it,
and shows it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.jobs import recurrence as rec
from uboss.modules.jobs.models import Job, JobSchedule, JobVersion


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Preview:
    """The next few firings, and anything worth saying about them."""

    timezone: str
    occurrences: list[datetime]
    #: Things a person should know before switching auto-run on. Never blockers — each is a
    #: legitimate configuration, and each is also a way to be surprised at 3 a.m.
    notes: list[str]


def to_recurrence(schedule: JobSchedule) -> rec.Recurrence:
    """The stored row as the pure recurrence type.

    One conversion, used by the preview and by whatever fires it, so a schedule cannot mean two
    different things depending on who asked.
    """
    return rec.from_row(schedule)


async def read(
    session: AsyncSession, context: SecurityContext, job_id: uuid.UUID
) -> JobSchedule | None:
    await guard.authorise(session, context, Action.VIEW)
    return (
        await session.execute(select(JobSchedule).where(JobSchedule.job_id == job_id))
    ).scalar_one_or_none()


async def preview(
    session: AsyncSession,
    context: SecurityContext,
    job_id: uuid.UUID,
    *,
    count: int = 10,
    from_time: datetime | None = None,
) -> Preview:
    """What this schedule would do next.

    `from_time` exists so a screen can preview a date somebody is curious about — usually a clock
    change. Without it, a person configuring a schedule in July has no way to see what happens in
    October until October.
    """
    await guard.authorise(session, context, Action.VIEW)

    schedule = await read(session, context, job_id)
    if schedule is None:
        raise NotFound("This job has no schedule.")

    recurrence = to_recurrence(schedule)
    moments = rec.occurrences(recurrence, after=from_time or _now(), count=count)
    return Preview(
        timezone=schedule.timezone,
        occurrences=moments,
        notes=_notes(schedule, recurrence, moments),
    )


def _notes(
    schedule: JobSchedule, recurrence: rec.Recurrence, moments: list[datetime]
) -> list[str]:
    """What a person should know before turning auto-run on.

    Never blockers. Each of these is a configuration somebody might mean; each is also a way to be
    surprised at three in the morning, and the difference is whether they read it first.
    """
    notes: list[str] = []

    if not schedule.auto_run:
        notes.append(
            "Auto-run is off, so none of these will actually happen until you switch it on."
        )
    if not moments:
        notes.append(
            "This schedule has no next run. Check the calendar and the day of the month — a "
            "schedule that never fires looks configured and does nothing."
        )

    zone = recurrence.zone()
    offsets = {moment.astimezone(zone).utcoffset() for moment in moments}
    if len(offsets) > 1:
        #  A clock change inside the window. Worth saying explicitly, because it is the one time
        #  the gap between two runs is not what the interval says.
        notes.append(
            "The clocks change during this period. The local time stays the same; the gap "
            "between two of these runs does not."
        )

    if schedule.pinned_version_id is None:
        notes.append(
            "This runs whatever version is published at the time. Pin a version if the method "
            "must not change underneath it."
        )
    if schedule.max_concurrent > 1 and schedule.overlap_policy == rec.OverlapPolicy.ALLOW:
        notes.append(
            f"Up to {schedule.max_concurrent} runs can be in progress at once. Make sure they do "
            "not write to the same records."
        )
    if schedule.missed_run_policy == rec.MissedRunPolicy.RUN_ALL:
        notes.append(
            "After an outage this will run every missed occurrence, oldest first. That can be a "
            "lot of runs at once."
        )

    return notes


async def set_schedule(
    session: AsyncSession,
    context: SecurityContext,
    job_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    expected_version: int | None,
) -> JobSchedule:
    """Create or replace a job's schedule.

    The recurrence is validated before anything is written — a schedule that could never fire is
    refused at the point somebody writes it, not discovered when the report never arrives.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    job = (
        await session.execute(select(Job).where(Job.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise NotFound("No such job.")

    schedule = await read(session, context, job_id)
    if schedule is None and expected_version is not None:
        raise Conflict("This job has no schedule yet.")
    if (
        schedule is not None
        and expected_version is not None
        and schedule.version != expected_version
    ):
        raise Conflict("Somebody else changed this schedule. Reload it and try again.")

    pinned = payload.get("pinned_version_id")
    if pinned is not None:
        version = (
            await session.execute(select(JobVersion).where(JobVersion.id == pinned))
        ).scalar_one_or_none()
        if version is None or version.job_id != job_id:
            raise ValidationFailed("That version does not belong to this job.")

    fields = {
        "auto_run": bool(payload.get("auto_run", False)),
        "timezone": str(payload["timezone"]).strip(),
        "frequency": payload["frequency"],
        "interval": int(payload.get("interval", 1)),
        "at_time": payload["at_time"],
        "weekdays": list(payload.get("weekdays") or []),
        "monthday": payload.get("monthday"),
        "dst_policy": payload.get("dst_policy", "shift"),
        "ambiguous_policy": payload.get("ambiguous_policy", "first"),
        "skip_dates": [str(value) for value in (payload.get("skip_dates") or [])],
        "weekdays_only": bool(payload.get("weekdays_only", False)),
        "overlap_policy": payload.get("overlap_policy", "skip"),
        "missed_run_policy": payload.get("missed_run_policy", "skip"),
        "max_concurrent": int(payload.get("max_concurrent", 1)),
        "pinned_version_id": pinned,
        "requires_approval_per_run": bool(payload.get("requires_approval_per_run", False)),
    }

    if isinstance(fields["at_time"], str):
        fields["at_time"] = time.fromisoformat(fields["at_time"])

    if schedule is None:
        schedule = JobSchedule(
            tenant_id=context.tenant_id,
            job_id=job_id,
            created_by_membership_id=context.membership_id,
            **fields,
        )
        session.add(schedule)
    else:
        for key, value in fields.items():
            setattr(schedule, key, value)
        schedule.version += 1

    #  Validated after the fields are set and before the flush, so the message names what is
    #  wrong rather than being a constraint violation the person has to decode.
    rec.validate(to_recurrence(schedule))

    #  Recomputed on every save. A stale `next_run_at` is a schedule that fires at the old time
    #  after somebody changed it, which is the failure people find hardest to believe.
    schedule.next_run_at = _next(schedule)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="job.schedule.set",
        resource_type="job",
        resource_id=job_id,
        actor=context,
        detail={
            "auto_run": schedule.auto_run,
            "frequency": schedule.frequency,
            "timezone": schedule.timezone,
            "pinned": schedule.pinned_version_id is not None,
        },
    )
    return schedule


def _next(schedule: JobSchedule) -> datetime | None:
    moments = rec.occurrences(to_recurrence(schedule), after=_now(), count=1)
    return moments[0] if moments else None


async def remove(
    session: AsyncSession, context: SecurityContext, job_id: uuid.UUID
) -> None:
    """Delete the schedule. The job stays; it simply no longer runs by itself."""
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    schedule = await read(session, context, job_id)
    if schedule is None:
        return

    await session.delete(schedule)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="job.schedule.removed",
        resource_type="job",
        resource_id=job_id,
        actor=context,
    )
