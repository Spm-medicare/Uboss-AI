"""The runtime's activities — the only place the domain and Temporal meet.

An activity is a function Temporal may call more than once. That is not a caveat, it is the
contract: a worker killed after doing the work and before recording the result will be asked to do
it again. Everything here is written to survive that.

## The three rules every activity in this file keeps

**Its own session, its own transaction.** An activity commits before returning. Holding a
transaction across an activity boundary is not possible — the boundary is a process boundary — and
a half-written run is worse than a repeated one.

**Idempotent by state, not by hope.** Each activity checks what it is about to do has not been
done. `begin_step` on a step already running returns rather than counting a second attempt;
`finish_step` on a finished step returns. Temporal's at-least-once delivery is then harmless.

**Nothing here decides anything.** The decisions live in `service.py` and are testable without a
server; these are the thin durable wrappers. A rule that only existed inside an activity would be
a rule provable only by running a workflow.

## Why the tenant is bound explicitly

An activity runs in a worker, not in a request, so nothing has bound `app.tenant_id` and every
row-level policy would refuse. `tenant_scope` binds it for the activity's transaction — the same
function the outbox relay and the recovery path use, for the same reason.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity

from uboss.core.logging import correlation_id, get_logger
from uboss.db.base import tenant_scope
from uboss.modules.runtime import service
from uboss.modules.runtime.models import Run, RunState, RunStep, StepState

log = get_logger(__name__)


@dataclass
class RunRef:
    """Everything an activity needs to find its run without a second lookup.

    Passed by value through the workflow rather than fetched from a closure: a workflow's inputs
    are recorded in its history and replayed, and anything not in them does not survive a worker
    restart.
    """

    tenant_id: str
    run_id: str
    #: Carried so an event written by an activity still names the request that started the run.
    correlation_id: str


@dataclass
class StepRef:
    """One step of a run, and what happened to it."""

    tenant_id: str
    run_id: str
    step_id: str
    position: int
    mode: str
    correlation_id: str


class RunActivities:
    """The activities, bound to a session factory.

    A class rather than module functions so the worker can hand them a factory. Temporal
    registers bound methods perfectly well, and the alternative — a module-level global — is a
    global that tests have to reach into.
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    # ── the run ──────────────────────────────────────────────────────────────────────────

    @activity.defn(name="run.mark_running")
    async def mark_running(self, ref: RunRef) -> None:
        async with self._scope(ref) as (session, run):
            #  Already running is the replay case, and it is not an error.
            if run.state in RunState.finished() or run.state == RunState.RUNNING:
                return
            await service.mark_running(session, run)

    @activity.defn(name="run.next_step")
    async def next_step(self, ref: RunRef) -> StepRef | None:
        """The next step to do, or `None` when the run is done.

        Read in its own transaction and returned by value, so the workflow's next decision is made
        from a fact rather than from a row it is holding open.
        """
        async with self._scope(ref) as (session, _run):
            step = await service.next_step(session, uuid.UUID(ref.run_id))
            if step is None:
                return None
            return StepRef(
                tenant_id=ref.tenant_id,
                run_id=ref.run_id,
                step_id=str(step.id),
                position=step.position,
                mode=step.mode,
                correlation_id=ref.correlation_id,
            )

    @activity.defn(name="run.finish")
    async def finish(self, ref: RunRef) -> None:
        async with self._scope(ref) as (session, run):
            if run.state in RunState.finished():
                return
            await service.finish_run(session, run)

    @activity.defn(name="run.fail")
    async def fail(self, ref: RunRef, detail: str) -> None:
        """Fail the run without a step to blame — a workflow-level failure.

        Rare, and worth having: a run whose version disappeared, or one the workflow could not
        make progress on. A run left `running` for ever is worse than one that says why it stopped.
        """
        async with self._scope(ref) as (session, run):
            if run.state in RunState.finished():
                return
            step = await service.next_step(session, uuid.UUID(ref.run_id))
            if step is not None:
                await service.fail_step(session, run, step, detail=detail)
            else:
                run.failure_detail = detail
                run.state = RunState.FAILED
                run.finished_at = datetime.now(UTC)

    # ── one step ─────────────────────────────────────────────────────────────────────────

    @activity.defn(name="step.begin")
    async def begin_step(self, ref: StepRef) -> None:
        async with self._scope(ref) as (session, run):
            step = await self._step(session, ref)
            #  Already running: this is a replay, and counting a second attempt would make the
            #  attempt column a count of worker restarts rather than of tries.
            if step.state != StepState.PENDING:
                return
            await service.begin_step(session, run, step)

    @activity.defn(name="step.wait_for_person")
    async def wait_for_person(self, ref: StepRef) -> None:
        async with self._scope(ref) as (session, run):
            step = await self._step(session, ref)
            if step.state in StepState.finished():
                return
            await service.wait_for_person(session, run, step)

    @activity.defn(name="step.perform")
    async def perform(self, ref: StepRef) -> dict[str, str]:
        """Do a non-human step.

        **Nothing is performed yet, and that is deliberate.** A step's actual work — a model call,
        an integration, a tool — is 7.2's and later. What exists here is the durable shape: the
        step is begun, an attempt is counted, and a result is recorded. Wiring a real effect in
        before the shape was proven against a killed worker would mean debugging both at once.

        The result says plainly that nothing was performed, so a run's evidence never implies work
        that did not happen.
        """
        async with self._scope(ref) as (session, run):
            step = await self._step(session, ref)
            if step.state in StepState.finished():
                return {"status": "already_finished"}
            await service.finish_step(
                session,
                run,
                step,
                result={
                    "status": "no_executor",
                    "detail": (
                        "This step's work is not wired to an executor yet. The run recorded that "
                        "it reached this step and moved on."
                    ),
                },
            )
            return {"status": "no_executor"}

    @activity.defn(name="step.fail")
    async def fail_step(self, ref: StepRef, detail: str) -> None:
        async with self._scope(ref) as (session, run):
            step = await self._step(session, ref)
            if step.state in StepState.finished():
                return
            await service.fail_step(session, run, step, detail=detail)

    # ── plumbing ─────────────────────────────────────────────────────────────────────────

    def _scope(self, ref: RunRef | StepRef):  # type: ignore[no-untyped-def]
        """A session with the tenant bound and the correlation id restored.

        Both matter. Without the tenant every policy refuses; without the correlation id an event
        written here cannot be tied back to the request that started the run.
        """
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def scope():  # type: ignore[no-untyped-def]
            token = correlation_id.set(ref.correlation_id)
            try:
                async with self._factory() as session:
                    async with tenant_scope(session, uuid.UUID(ref.tenant_id)):
                        run = (
                            await session.execute(
                                select(Run).where(Run.id == uuid.UUID(ref.run_id))
                            )
                        ).scalar_one()
                        yield session, run
                    await session.commit()
            finally:
                correlation_id.reset(token)

        return scope()

    @staticmethod
    async def _step(session: AsyncSession, ref: StepRef) -> RunStep:
        return (
            await session.execute(select(RunStep).where(RunStep.id == uuid.UUID(ref.step_id)))
        ).scalar_one()
