"""What a schedule accepts and returns.

`SchedulePreview` is the shape PLAN §8's *recurrence preview* takes. It carries the timezone
alongside the instants, because a list of UTC timestamps with no zone is the least readable way to
show a schedule and the easiest to produce by accident.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.jobs.recurrence import (
    AmbiguousPolicy,
    DstPolicy,
    Frequency,
    MissedRunPolicy,
    OverlapPolicy,
)


class ScheduleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: §8's "Auto-run Yes/No". False saves the schedule without anything firing — the only honest
    #: way to keep a half-built one.
    auto_run: bool = False

    #: IANA, never an offset. `Asia/Kolkata`, not `+05:30`.
    timezone: str = Field(min_length=1, max_length=64)
    frequency: Frequency
    interval: int = Field(default=1, ge=1, le=999)
    #: A local time of day. The intent is "nine where the team is", on both sides of a clock
    #: change — which is why this is a time and not a timestamp.
    at_time: time
    #: Weekly only. Monday is 0. Empty means the weekday it starts on.
    weekdays: list[int] = Field(default_factory=list)
    #: Monthly only. 31 in a 30-day month means the last day, which is what people mean.
    monthday: int | None = Field(default=None, ge=1, le=31)

    dst_policy: DstPolicy = DstPolicy.SHIFT
    ambiguous_policy: AmbiguousPolicy = AmbiguousPolicy.FIRST

    #: §8's calendar — dates this must not run, in the schedule's own timezone.
    skip_dates: list[str] = Field(default_factory=list)
    weekdays_only: bool = False

    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP
    missed_run_policy: MissedRunPolicy = MissedRunPolicy.SKIP
    max_concurrent: int = Field(default=1, ge=1, le=100)

    #: Null means "whatever is published then". Pinned means this exact version keeps running.
    pinned_version_id: uuid.UUID | None = None
    requires_approval_per_run: bool = False

    #: Absent when creating the schedule; required to change one.
    expected_version: int | None = Field(default=None, ge=1)


class ScheduleRead(ScheduleWrite):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    #: Shown, so a schedule that has quietly stopped working is visible rather than silent.
    last_error: str | None = None
    version: int


class SchedulePreview(BaseModel):
    """The next few firings — PLAN §8's recurrence preview."""

    #: Carried alongside the instants. A list of UTC timestamps with no zone is the least
    #: readable way to show a schedule, and the easiest to produce by accident.
    timezone: str
    occurrences: list[datetime]
    #: Things worth knowing before switching auto-run on. Never blockers.
    notes: list[str] = Field(default_factory=list)
