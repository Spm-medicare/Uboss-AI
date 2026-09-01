"""Who hears about something — resolved from the tables that already say so.

**No second subscriber table.** `TaskFollower` already records who is watching a task; `delegate`
writes into it, and the *Following* tab reads from it. A notification module that invented its own
subscription list would be a second list to keep in step, and the one people managed on screen
would be the one that was wrong.

## The three audiences, and why they are separate functions

* **The holder** — whoever the work is assigned to now. One person, and the only one for whom a
  task is `action_required`.
* **The watchers** — the followers plus whoever set the run going. Told what happened; never told
  to do anything.
* **Nobody** — a legitimate answer. An unassigned task has no holder, and a run started by a
  schedule has no starter. Both return empty rather than falling back to "tell an administrator",
  which is how a notification system becomes a thing administrators mute.

Duplicates are removed here rather than at each call site, because a person who both holds a task
and follows it is one person and should be told once.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.modules.runtime.models import Run
from uboss.modules.tasks.models import Task, TaskFollower


async def watchers_of_task(
    session: AsyncSession, task: Task, *, exclude: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Everybody who should hear about something happening on this task.

    The followers, the current holder, and whoever started the run — deduplicated, and with
    `exclude` dropped so the person who did the thing is not told they did it.
    """
    followers = list(
        (
            await session.execute(
                select(TaskFollower.membership_id).where(
                    TaskFollower.task_id == task.id
                )
            )
        )
        .scalars()
        .all()
    )

    starter = await run_starter(session, task.run_id)

    seen: list[uuid.UUID] = []
    for candidate in [task.assignee_membership_id, starter, *followers]:
        if candidate is None or candidate == exclude or candidate in seen:
            continue
        seen.append(candidate)
    return seen


async def run_starter(
    session: AsyncSession, run_id: uuid.UUID
) -> uuid.UUID | None:
    """Whoever set the run going, or `None` for a scheduled one.

    `None` is the honest answer for a run nobody started, and it is what stops a nightly job's
    every event being addressed to whichever person last edited the schedule.
    """
    return (
        await session.execute(select(Run.started_by_membership_id).where(Run.id == run_id))
    ).scalar_one_or_none()


async def job_owner(session: AsyncSession, job_id: uuid.UUID) -> uuid.UUID | None:
    """The Job's owner — the recipient for anything about a schedule or a failing run.

    A schedule has no actor, so its notifications need somebody accountable rather than somebody
    who acted. §9 makes the owner exactly that.
    """
    from uboss.modules.jobs.models import Job

    return (
        await session.execute(select(Job.owner_membership_id).where(Job.id == job_id))
    ).scalar_one_or_none()
