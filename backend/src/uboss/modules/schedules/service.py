"""Turning a schedule into runs — the half Gate 4 deliberately left out.

Gate 4 gave a schedule its configuration and a preview; `jobs/recurrence.py` answers *when*,
purely and with no clock of its own. This is what acts on the answer, and the hard part is not the
timer. It is **exactly once**.

## The ledger comes before the run, always

Every scheduler is eventually run twice at the same moment — a second worker started by mistake, a
deploy that overlaps, a container restarted before anybody noticed the first was alive. So each
occurrence is written to `schedule_firings` **and committed** before a run is started. The second
worker's insert is refused by `uq_schedule_firings_occurrence` rather than by a lock somebody has
to remember to take, and a nightly reconciliation cannot run twice.

A crash between the row and the run leaves a `due` firing: visible, and picked up on the next
tick. The other order would start a run nothing recorded, which is the failure that cannot be
found afterwards.

## No clock of its own

`tick()` takes `now`. Every rule below is therefore a function of its arguments, and a test can
walk a schedule across a daylight-saving boundary without waiting until March. A scheduler that
read the wall clock internally could only be tested by changing the machine's time.

## What each policy actually does here

* **missed_run_policy** decides how much of the gap since `last_run_at` is owed. `recurrence.missed`
  computes it; this module marks those firings `was_missed`, so a report that ran at 09:14 for an
  03:00 slot says why rather than looking like a schedule firing at the wrong time.
* **overlap_policy** is checked against the Job's *live* runs at the moment of firing, not against
  the previous firing's row — a run started by hand counts as a run.
* **max_concurrent** applies to `allow`. `skip` and `queue` are about the previous run rather than
  about a count.
* **requires_approval_per_run** stops before the run and records `awaiting_approval`. A person
  releases it. Nothing is started quietly.

## What this does not do

**It does not sleep, retry or hold a lease.** `tick()` is one pass; `scheduler_worker.py` is what
calls it on an interval. Keeping the loop out of here is what makes every rule above testable by
calling a function.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import ValidationFailed
from uboss.core.logging import get_logger
from uboss.modules.audit import service as audit
from uboss.modules.jobs import recurrence as rec
from uboss.modules.jobs.models import Job, JobSchedule
from uboss.modules.notifications import fanout
from uboss.modules.notifications import service as notify
from uboss.modules.runtime import service as runtime
from uboss.modules.runtime.models import Run, RunState, RunTrigger
from uboss.modules.schedules.models import FiringState, ScheduleFiring

log = get_logger(__name__)

#: How far back a catch-up will look. A `last_run_at` a year old — restored from a backup — must
#: not produce a year of firings the moment a worker starts.
MAX_CATCH_UP_HOURS = 48

#: A slot due within this window is *current* — simply due, never subject to the missed-run
#: policy. Longer than the worker's poll by a comfortable margin, so an ordinary tick's slots are
#: never mistaken for downtime's.
RECENT_MINUTES = 10


@dataclass(slots=True)
class Planned:
    """One occurrence the scheduler decided to act on."""

    due_at: datetime
    was_missed: bool


@dataclass(frozen=True, slots=True)
class StartedFiring:
    """A run this tick created, and what the worker needs to start its workflow after commit."""

    tenant_id: uuid.UUID
    run_id: uuid.UUID
    workflow_id: str


@dataclass(slots=True)
class TickResult:
    """What one pass did. Returned rather than logged only, so a test can assert on it."""

    considered: int = 0
    started: list[StartedFiring] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    awaiting: int = 0
    failed: list[str] = field(default_factory=list)


async def due_schedules(session: AsyncSession) -> list[JobSchedule]:
    """Every schedule that is switched on. Read under the caller's bound tenant.

    `auto_run` false is §8's honest half-built state: the schedule is described and nothing fires.
    It is filtered here rather than checked later so a switched-off schedule never even appears in
    the scheduler's log.
    """
    return list(
        (
            await session.execute(
                select(JobSchedule).where(JobSchedule.auto_run.is_(True))
            )
        )
        .scalars()
        .all()
    )


def plan(schedule: JobSchedule, *, now: datetime) -> list[Planned]:
    """Which occurrences this schedule owes, at `now`.

    Pure: no database, no clock. Two windows, and the difference between them is the whole
    missed-run feature:

    * **Current** — due within the last `RECENT_MINUTES`. A slot that fell due while the
      scheduler was running normally is simply due, and always fires; a policy that could
      swallow it would make `skip` mean "never run at all".
    * **Missed** — older than that. These fell due while nothing was running, and
      `missed_run_policy` is the author's answer: forget them, run the latest once, or run
      every one. They are marked `was_missed`, so a report that ran at 09:14 for an 03:00
      slot says why.

    A schedule that has **never run** starts from its own `next_run_at` — the moment its
    configuration said "the first one is here" — and owes nothing from before it existed. The
    alternative fires a month of runs at three in the morning the first time a worker sees a
    schedule somebody created a month ago.
    """
    recurrence = rec.from_row(schedule)
    policy = rec.MissedRunPolicy(schedule.missed_run_policy)

    horizon = now - timedelta(hours=MAX_CATCH_UP_HOURS)
    recent_floor = now - timedelta(minutes=RECENT_MINUTES)

    if schedule.last_run_at is not None:
        #  Where it left off, bounded: a `last_run_at` a year old — restored from a backup, say —
        #  must not produce a year of firings.
        base = max(schedule.last_run_at, horizon)
    elif schedule.next_run_at is not None:
        #  Never run: the first occurrence its configuration promised, and nothing earlier.
        base = max(schedule.next_run_at - timedelta(microseconds=1), horizon)
    else:
        #  Never run and never planned — a schedule switched on before this tick computes its
        #  `next_run_at` at the end. It owes nothing yet; the next tick sees the plan.
        base = now

    #  What fell due while nothing was watching, filtered by the author's policy. Bounded at the
    #  recent window so a normally-due slot is never subject to it.
    owed: list[datetime] = []
    if schedule.last_run_at is not None and base < recent_floor:
        owed = rec.missed(
            recurrence, last_run_at=base, now=recent_floor, policy=policy
        )

    #  What is simply due now.
    current = rec.occurrences(
        recurrence, after=max(base, recent_floor), count=rec.MAX_OCCURRENCES, until=now
    )

    planned: dict[datetime, bool] = {moment: True for moment in owed}
    for moment in current:
        planned[moment] = False

    return [
        Planned(due_at=moment, was_missed=planned[moment])
        for moment in sorted(planned)
    ]


async def tick(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    now: datetime | None = None,
    start_run: bool = True,
) -> TickResult:
    """One pass over one workspace: plan every switched-on schedule, record, act.

    **No `SecurityContext`, deliberately.** The scheduler is not a person, and inventing a context
    for it would put a made-up name on the audit row of every nightly run. `audit.record` accepts
    an event with no actor for exactly this case, and the tenant comes in explicitly because the
    worker sweeps workspaces one at a time under `tenant_scope`.

    `start_run` is false in tests that only want the ledger — the run itself needs a workflow
    service, and the rules this module owns do not.
    """
    moment = now or datetime.now(UTC)
    result = TickResult()

    for schedule in await due_schedules(session):
        try:
            occurrences = plan(schedule, now=moment)
        except ValidationFailed as bad:
            #  A schedule whose configuration cannot be read is recorded on the schedule itself
            #  rather than crashing the tick — one broken schedule must not stop every other one.
            schedule.last_error = str(bad)
            result.failed.append(str(schedule.id))
            log.warning("schedule_unreadable", schedule_id=str(schedule.id))
            continue

        for occurrence in occurrences:
            result.considered += 1
            firing = await _claim(session, schedule, occurrence, tenant_id=tenant_id)
            if firing is None:
                #  Already recorded by an earlier tick, or by another worker a moment ago.
                continue
            await _act(
                session,
                schedule,
                firing,
                now=moment,
                result=result,
                start_run=start_run,
            )

        schedule.next_run_at = _next(schedule, after=moment)

    return result


async def _claim(
    session: AsyncSession,
    schedule: JobSchedule,
    occurrence: Planned,
    *,
    tenant_id: uuid.UUID,
) -> ScheduleFiring | None:
    """Write the ledger row, or find out somebody else already owns this occurrence.

    **`ON CONFLICT DO NOTHING`, not a caught exception.** Three attempts were made at this and the
    first two were wrong in the same way: `session.add()` followed by a flush inside a savepoint
    raises on the duplicate, and the rolled-back savepoint leaves the failed object in the session
    — sometimes pending, sometimes detached, depending on whether the INSERT was issued inside the
    savepoint or by an earlier autoflush. Either way the tick's own commit re-issues it and the
    whole transaction dies with a `PendingRollbackError`, three functions from the cause.

    A statement that simply does not insert has none of that. Nothing is raised, nothing is left
    in the unit of work, and `RETURNING` tells the caller which happened: a row means this worker
    owns the occurrence, no row means another one recorded it first. The constraint is still what
    guarantees exactly-once; this is just asking it politely.
    """
    claimed = (
        await session.execute(
            text(
                """
                INSERT INTO schedule_firings
                    (tenant_id, schedule_id, job_id, due_at, state, was_missed)
                VALUES (:tenant, :schedule, :job, :due_at, 'due', :was_missed)
                ON CONFLICT (schedule_id, due_at) DO NOTHING
                RETURNING id
                """
            ),
            {
                "tenant": tenant_id,
                "schedule": schedule.id,
                "job": schedule.job_id,
                "due_at": occurrence.due_at,
                "was_missed": occurrence.was_missed,
            },
        )
    ).scalar_one_or_none()

    if claimed is None:
        log.info(
            "schedule_occurrence_already_claimed",
            schedule_id=str(schedule.id),
            due_at=occurrence.due_at.isoformat(),
        )
        return None

    #  Read back as an ORM object so the rest of the tick can set its state the ordinary way.
    return (
        await session.execute(
            select(ScheduleFiring).where(ScheduleFiring.id == claimed)
        )
    ).scalar_one()


async def _act(
    session: AsyncSession,
    schedule: JobSchedule,
    firing: ScheduleFiring,
    *,
    now: datetime,
    result: TickResult,
    start_run: bool,
) -> None:
    """Decide what happens to one claimed occurrence, and record it."""
    firing.fired_at = now

    version_id = await _version_for(session, schedule)
    if version_id is None:
        _skip(
            firing,
            result,
            "This job has no published version, so there was nothing to run. Publish it first.",
        )
        return
    firing.job_version_id = version_id

    blocked = await _overlap_block(session, schedule)
    if blocked is not None:
        _skip(firing, result, blocked)
        return

    if schedule.requires_approval_per_run:
        #  Stopped **before** the run. Recorded as its own state rather than skipped: a person
        #  has to release it, and a run that quietly did not happen is indistinguishable from a
        #  scheduler that is broken.
        firing.state = FiringState.AWAITING_APPROVAL
        firing.detail = "This schedule needs a person to release each run."
        result.awaiting += 1
        #  Held work that nobody is told about is held forever. This is the only signal that an
        #  occurrence is waiting — there is no run yet, so it appears in no To-do list.
        await _tell_owner(
            session,
            schedule,
            event="schedule.awaiting_release",
            title="A scheduled run is waiting to be released",
            body=firing.detail,
            action_required=True,
        )
        return

    if not start_run:
        #  The ledger is written and the decision is made; the run is somebody else's to start.
        return

    await _start(session, schedule, firing, result, actor=None)


async def _start(
    session: AsyncSession,
    schedule: JobSchedule,
    firing: ScheduleFiring,
    result: TickResult,
    *,
    actor: SecurityContext | None,
) -> None:
    """Create the run for a firing that is allowed to proceed.

    The workflow is **not** started here. `runtime.start` writes the row; the caller — the worker
    or the release route — commits and then asks Temporal, in that order, for the same reason
    `POST /runs` does: a crash between them leaves a `pending` run somebody can find, and the
    other order leaves a workflow nothing points at.
    """
    try:
        started = await runtime.start(
            session,
            tenant_id=firing.tenant_id,
            job_version_id=firing.job_version_id,  # type: ignore[arg-type]
            trigger=RunTrigger.SCHEDULE,
            #  Named only when a person released a held occurrence. A scheduled run that fired on
            #  its own has no actor, and the audit row says so rather than naming whoever
            #  configured the schedule months ago.
            actor=actor,
        )
    except ValidationFailed as bad:
        firing.state = FiringState.FAILED
        firing.detail = str(bad)
        result.failed.append(str(firing.id))
        return

    firing.state = FiringState.STARTED
    firing.run_id = started.run_id
    schedule.last_run_at = firing.due_at
    schedule.last_error = None
    result.started.append(
        StartedFiring(
            tenant_id=firing.tenant_id,
            run_id=started.run_id,
            workflow_id=started.workflow_id,
        )
    )

    await audit.record(
        session,
        tenant_id=firing.tenant_id,
        action="schedules.fired",
        resource_type="schedule",
        resource_id=schedule.id,
        actor=actor,
        detail={
            "run_id": str(started.run_id),
            "due_at": firing.due_at.isoformat(),
            "was_missed": firing.was_missed,
        },
    )
    log.info(
        "schedule_fired",
        schedule_id=str(schedule.id),
        run_id=str(started.run_id),
        due_at=firing.due_at.isoformat(),
        was_missed=firing.was_missed,
    )


class AlreadyReleased(Exception):
    """This occurrence is running already, and the caller asked for it to be running.

    Not a `ValidationFailed`: nothing about the request is wrong. It carries the run so the route
    can answer with the occurrence as it stands, without starting a second workflow for it.
    """

    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__("That occurrence is already running.")
        self.run_id = run_id


async def release(
    session: AsyncSession,
    context: SecurityContext,
    firing: ScheduleFiring,
) -> StartedFiring:
    """Let a held occurrence run — §8's `requires_approval_per_run`, decided by a person.

    Only from `awaiting_approval`. Releasing something already started would produce a second run
    of one occurrence, which is exactly what the ledger exists to prevent.
    """
    #  Already running counts as released.
    #
    #  This route commits in the middle of the request so the run row is durable before the
    #  workflow starts, which is the ordering every run start here keeps — and it means the
    #  `Idempotency-Key` it demands cannot be replayed from a stored response. So the operation
    #  carries its own idempotence. Without it a release that succeeded and then lost its
    #  connection came back, on retry, as *"not waiting to be released"*: a refusal, about work
    #  that had been done. The ledger's unique constraint is still what guarantees exactly-once;
    #  this only stops the second attempt lying about the first.
    if firing.state == FiringState.STARTED and firing.run_id is not None:
        raise AlreadyReleased(firing.run_id)
    if firing.state != FiringState.AWAITING_APPROVAL:
        raise ValidationFailed("That occurrence is not waiting to be released.")

    schedule = await session.get(JobSchedule, firing.schedule_id)
    if schedule is None:
        raise ValidationFailed("That schedule no longer exists.")

    result = TickResult()
    firing.detail = None
    await _start(session, schedule, firing, result, actor=context)
    if firing.state != FiringState.STARTED or not result.started:
        raise ValidationFailed(
            firing.detail or "That occurrence could not be started."
        )
    #  The caller needs the workflow id to start the workflow after its commit — the same
    #  row-first ordering every run start keeps.
    return result.started[0]


async def _version_for(
    session: AsyncSession, schedule: JobSchedule
) -> uuid.UUID | None:
    """Which version this occurrence runs.

    A pinned version wins and keeps winning until somebody moves it — right for anything
    regulated. Otherwise it is whatever the Job has published *now*, read at firing time rather
    than at configuration time, because that is what "run the current method" means.
    """
    if schedule.pinned_version_id is not None:
        return schedule.pinned_version_id
    job = await session.get(Job, schedule.job_id)
    return job.published_version_id if job is not None else None


async def _overlap_block(
    session: AsyncSession, schedule: JobSchedule
) -> str | None:
    """The overlap rule, as a sentence or `None`.

    Counted against the Job's **live runs**, not against the previous firing: a run somebody
    started by hand two minutes ago is a run, and a scheduler that ignored it would produce
    exactly the collision the policy exists to prevent.
    """
    active = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Run)
                .where(
                    Run.job_id == schedule.job_id,
                    Run.state.in_(RunState.active()),
                )
            )
        ).scalar_one()
    )
    if active == 0:
        return None

    policy = rec.OverlapPolicy(schedule.overlap_policy)
    if policy == rec.OverlapPolicy.SKIP:
        return (
            f"A run of this job was still going ({active} active), and this schedule is set to "
            "skip rather than overlap."
        )
    if policy == rec.OverlapPolicy.QUEUE:
        #  §22's recommended default is "queue one run". Queuing here means *this* occurrence is
        #  not started while one is going; the ledger keeps the record, and the next tick after
        #  the run finishes starts the next occurrence rather than replaying this one. Replaying
        #  an old slot would produce a report about a window nobody is asking about any more.
        return (
            f"A run of this job was still going ({active} active), so this occurrence waited "
            "rather than overlapping it."
        )
    if active >= max(schedule.max_concurrent, 1):
        return (
            f"This job already had {active} runs going and its limit is "
            f"{schedule.max_concurrent}."
        )
    return None


def _skip(firing: ScheduleFiring, result: TickResult, why: str) -> None:
    """Record a skip with its reason. There is no skip without one — see the check constraint."""
    firing.state = FiringState.SKIPPED
    firing.detail = why
    result.skipped.append(why)


async def _tell_owner(
    session: AsyncSession,
    schedule: JobSchedule,
    *,
    event: str,
    title: str,
    body: str | None,
    action_required: bool = False,
) -> None:
    """Tell whoever owns the Job. A schedule has no actor, so it needs somebody accountable.

    Silently does nothing when the Job has no owner — that is a Job somebody should fix, and a
    notification addressed to nobody is not the way to say so.
    """
    owner = await fanout.job_owner(session, schedule.job_id)
    if owner is None:
        return
    job = await session.get(Job, schedule.job_id)
    await notify.schedule_event(
        session,
        tenant_id=schedule.tenant_id,
        membership_id=owner,
        job_id=schedule.job_id,
        job_name=job.name if job is not None else "A job",
        event=event,
        title=title,
        body=body,
        action_required=action_required,
    )


def _next(schedule: JobSchedule, *, after: datetime) -> datetime | None:
    """The next occurrence after this tick, for the schedule page to show.

    Recomputed every tick rather than stored once: a stale `next_run_at` is a page that says a
    schedule will fire at a time it will not.
    """
    try:
        upcoming = rec.occurrences(rec.from_row(schedule), after=after, count=1)
    except ValidationFailed:
        return None
    return upcoming[0] if upcoming else None
