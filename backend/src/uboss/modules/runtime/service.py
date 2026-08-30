"""Starting a run, and moving it along — the domain half of the runtime.

**Nothing in this file imports Temporal.** These are the operations a run performs; `workflows.py`
and `activities.py` are how they are *driven* durably. That split is the same one `model_gateway`
and `integrations/` already keep, and it buys the thing that matters here: every rule below can be
tested by calling a function, with no server running and no workflow replay to reason about.

## The one rule the whole module turns on

A run reads a **version**, never a draft. `start` takes a `job_version_id` and copies the steps out
of that version's frozen snapshot into `run_steps`. Somebody editing the Job while a run is in
flight changes nothing about the run — which is what immutable versions are for, and it is far
easier to guarantee by copying at the start than by remembering not to re-read later.

## Why the steps are copied rather than read on demand

A step could be looked up in the snapshot each time it runs. Copying costs one insert per step and
buys three things: a step has its own state and attempt count without a second table to hold them;
`"what is assigned to me"` is a query rather than a scan through JSON; and a run remains readable
as evidence even if the version row is ever archived.

## What "waiting" means

A human step does not block the runtime; it puts the run in `waiting` and stops. Something outside
— a person completing a task in 7.2, an approval decided in 7.3 — calls back in and the run
continues. A runtime that held a thread open for three days waiting on a form would be a runtime
that falls over at the first long weekend.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import NotFound, ValidationFailed
from uboss.core.logging import correlation_id, get_logger
from uboss.modules.audit import service as audit
from uboss.modules.jobs.models import JobVersion
from uboss.modules.runtime.models import (
    Run,
    RunEvent,
    RunState,
    RunStep,
    RunTrigger,
    StepState,
)

log = get_logger(__name__)

#: The work modes a step can carry, from §9. A step that is not `human` is the runtime's to do.
HUMAN = "human"


@dataclass(frozen=True, slots=True)
class StartedRun:
    """What a caller needs to follow a run it just started."""

    run_id: uuid.UUID
    workflow_id: str
    steps: int


def workflow_id_for(tenant_id: uuid.UUID, run_id: uuid.UUID) -> str:
    """Temporal's id for a run.

    Built from ids rather than from a name, and prefixed with the tenant, so that two customers
    running the same Job cannot collide and a workflow id in a log says which tenant it belongs
    to without a lookup.
    """
    return f"run.{tenant_id}.{run_id}"


async def start(
    session: AsyncSession,
    context: SecurityContext,
    *,
    job_version_id: uuid.UUID,
    trigger: RunTrigger,
) -> StartedRun:
    """Create the run and its steps from a published version.

    **The row is written before the workflow is started**, by the caller in `api.py`, and this
    function only does the database half. A crash between the two leaves a `pending` run a
    reconciler can resolve; the other order would leave a running workflow nothing points at,
    which is unrecoverable rather than merely untidy.

    Raises `NotFound` when the version does not exist in this tenant — through RLS as well as the
    filter, so a guessed id from another workspace is not distinguishable from a wrong one.
    """
    version = (
        await session.execute(
            select(JobVersion).where(JobVersion.id == job_version_id)
        )
    ).scalar_one_or_none()
    if version is None:
        raise NotFound("That version does not exist.")

    steps = _steps_of(version.snapshot)
    if not steps:
        #  A version with no steps would produce a run that finishes instantly having done
        #  nothing, which reads as success. Refused rather than run.
        raise ValidationFailed(
            "That version has no steps, so there is nothing to run. Publish a version with at "
            "least one step."
        )

    run = Run(
        tenant_id=context.tenant_id,
        job_version_id=version.id,
        job_id=version.job_id,
        workflow_id="",  # replaced below, once the row has an id
        state=RunState.PENDING,
        trigger=trigger,
        started_by_membership_id=(
            context.membership_id if trigger is RunTrigger.MANUAL else None
        ),
        correlation_id=correlation_id.get(),
    )
    session.add(run)
    #  Flushed to get the id the workflow id is built from. The row is not committed here — the
    #  caller decides the transaction boundary, and it has to be the same one that records the
    #  audit event.
    await session.flush()
    run.workflow_id = workflow_id_for(context.tenant_id, run.id)

    for position, step in enumerate(steps, start=1):
        session.add(
            RunStep(
                tenant_id=context.tenant_id,
                run_id=run.id,
                position=position,
                #  A step with no title is still a step; the position is what identifies it, and
                #  a placeholder is better than a row a screen cannot label.
                title=(step.get("what_exact_work") or f"Step {position}")[:200],
                mode=step.get("mode") or HUMAN,
                state=StepState.PENDING,
            )
        )

    await _record(session, run, kind="run.created", detail={"steps": len(steps)}, context=context)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="runtime.run_started",
        resource_type="run",
        resource_id=run.id,
        actor=context,
        detail={"job_version_id": str(version.id), "trigger": trigger.value},
    )
    #  Flushed before returning, so the function's postcondition is true: the run, its steps and
    #  its first event all exist. The sessionmaker sets `autoflush=False` — deliberately, so a
    #  stray query cannot write a half-built object — which means a caller that started a run and
    #  immediately asked for its steps or its events would be told there were none.
    await session.flush()

    log.info("run_created", run_id=str(run.id), steps=len(steps), trigger=trigger.value)
    return StartedRun(run_id=run.id, workflow_id=run.workflow_id, steps=len(steps))


def _steps_of(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """The version's steps, in order.

    Read defensively. A snapshot is JSON that was correct when it was written, and a run started
    against one written by an older release must fail with a sentence rather than a `KeyError`
    three frames down.
    """
    steps = snapshot.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


async def mark_running(session: AsyncSession, run: Run) -> None:
    """The workflow has started. Called by the first activity, not by the API."""
    run.state = RunState.RUNNING
    run.started_at = datetime.now(UTC)
    await _record(session, run, kind="run.started", detail={})


async def next_step(session: AsyncSession, run_id: uuid.UUID) -> RunStep | None:
    """The first step that has not finished, or `None` when they all have.

    Ordered by position, which is the version's order. There is deliberately no branching yet:
    §8's dependencies between steps are a Job Builder concept the runtime will honour in 7.2, and
    guessing at them here would be a second implementation to reconcile.
    """
    return (
        await session.execute(
            select(RunStep)
            .where(RunStep.run_id == run_id, RunStep.state == StepState.PENDING)
            .order_by(RunStep.position)
            .limit(1)
        )
    ).scalar_one_or_none()


async def begin_step(session: AsyncSession, run: Run, step: RunStep) -> None:
    """Mark a step started, and count the attempt.

    `attempt` is incremented **here**, when the step begins, not after a failure. An activity that
    dies mid-step never reaches the failure path, so counting there would let a poisonous step be
    retried for ever by a succession of workers it kept killing — the same reasoning the outbox
    relay already uses for its own claim.
    """
    step.state = StepState.RUNNING
    step.attempt += 1
    step.started_at = datetime.now(UTC)
    await _record(
        session,
        run,
        kind="step.started",
        detail={"position": step.position, "attempt": step.attempt},
        step=step,
    )


async def finish_step(
    session: AsyncSession,
    run: Run,
    step: RunStep,
    *,
    result: dict[str, Any] | None = None,
) -> None:
    step.state = StepState.SUCCEEDED
    step.finished_at = datetime.now(UTC)
    step.result = result
    await _record(
        session, run, kind="step.succeeded", detail={"position": step.position}, step=step
    )


async def fail_step(session: AsyncSession, run: Run, step: RunStep, *, detail: str) -> None:
    """A step failed for good — the workflow has exhausted its retries.

    The run fails with it. There is no partial success: a Job's steps are a method, and a method
    that stopped halfway has not been performed.
    """
    now = datetime.now(UTC)
    step.state = StepState.FAILED
    step.finished_at = now
    step.failure_detail = detail
    run.state = RunState.FAILED
    run.finished_at = now
    run.failure_detail = detail
    await _record(
        session,
        run,
        kind="step.failed",
        detail={"position": step.position, "reason": detail[:500]},
        step=step,
    )


async def wait_for_person(session: AsyncSession, run: Run, step: RunStep) -> None:
    """A human step. The run stops and something outside it continues the story.

    Not a blocked thread and not a poll: the workflow waits on a signal, and 7.2's task completion
    is what sends it. A runtime that held a worker open across a long weekend would be one that
    falls over on the Tuesday.
    """
    step.state = StepState.WAITING
    run.state = RunState.WAITING
    await _record(
        session, run, kind="step.waiting_for_person", detail={"position": step.position}, step=step
    )


async def finish_run(session: AsyncSession, run: Run) -> None:
    run.state = RunState.SUCCEEDED
    run.finished_at = datetime.now(UTC)
    await _record(session, run, kind="run.succeeded", detail={})


async def cancel(
    session: AsyncSession, context: SecurityContext, run: Run, *, reason: str
) -> None:
    """Stop a run, with the person and the reason on the record.

    Cancellation is an event with an actor rather than a status column, so *who* stopped it
    survives — see migration 0029.
    """
    if run.state in RunState.finished():
        raise ValidationFailed("That run has already finished.")
    run.state = RunState.CANCELLED
    run.finished_at = datetime.now(UTC)
    await _record(
        session, run, kind="run.cancelled", detail={"reason": reason[:500]}, context=context
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="runtime.run_cancelled",
        resource_type="run",
        resource_id=run.id,
        actor=context,
        detail={"reason": reason[:500]},
    )


async def _record(
    session: AsyncSession,
    run: Run,
    *,
    kind: str,
    detail: dict[str, Any],
    step: RunStep | None = None,
    context: SecurityContext | None = None,
) -> None:
    """One line of a run's evidence.

    The correlation id comes from the context variable, so an event written by an activity three
    hops from the request that caused it still carries that request's id — which is what makes a
    run traceable back to the click that started it, possibly hours later and in another process.
    """
    session.add(
        RunEvent(
            tenant_id=run.tenant_id,
            run_id=run.id,
            run_step_id=step.id if step is not None else None,
            kind=kind,
            detail=detail,
            actor_membership_id=context.membership_id if context is not None else None,
            correlation_id=correlation_id.get(),
        )
    )
