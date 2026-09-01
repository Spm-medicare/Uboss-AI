"""At-least-once delivery, from the side that matters: what happens on the second delivery.

`PLAN.md` §962 makes this a Gate 7 exit criterion — *"crash/retry/idempotency/outbox recovery tests
pass"* — and the work breakdown says it in product terms: *"a worker killed mid-step resumes
without repeating the step's external effect."*

`activities.py` is written for it. Its header states the contract plainly: *"An activity is a
function Temporal may call more than once. That is not a caveat, it is the contract: a worker killed
after doing the work and before recording the result will be asked to do it again."* Every activity
then checks state before acting.

None of that was tested. The existing run tests exercise the *service* — begin, fail, finish — and
one of them simulates a **retry** by putting a step back to `pending`. A retry and a replay are
different events with different correct answers: a retry counts an attempt, a replay must not.
Nothing asserted the replay case, so the file's whole premise rested on reading it.

## How a killed worker is simulated

By calling the activity twice. That is not an approximation of the failure — it *is* the failure as
the activity experiences it: Temporal redelivers because it never saw the first result, and the
second call arrives at a database that already has the first call's work in it. Killing a real
process would produce the same two calls and prove nothing further.

## These tests commit, and that is the point

An activity opens its own session and commits — that is its contract, and a redelivery is a
*different transaction* arriving at state the first one left behind. A test that ran the pair inside
one open transaction would prove nothing about either.

So the rows are real, and `two_workspaces` removes them: its teardown deletes the workspace with the
append-only triggers briefly disabled, which is why its own comment mentions `run_events` and
`task_comments`. Cleaning up here instead is not possible — `refuse_change()` is a trigger, so
nothing can delete a `run_events` row, not even the owner. The first version of this file tried, and
the second tried to avoid committing at all by joining every session to one rolled-back transaction;
that deadlocked against the workspace teardown, which needs the locks the open transaction was
holding.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.runtime import service
from uboss.modules.runtime.activities import RunActivities, RunRef
from uboss.modules.runtime.models import (
    Run,
    RunEvent,
    RunState,
    RunStep,
    RunTrigger,
    StepState,
)
from uboss.modules.tasks.models import Task

CORRELATION = "replay-test"


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    membership = await session.get(Membership, workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = datetime.now(UTC)
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=membership.id,
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


async def _published_job(
    session: AsyncSession, workspace: Workspace, *, steps: list[dict[str, object]]
) -> tuple[uuid.UUID, uuid.UUID]:
    """A published version to run, written directly — the publish path has its own tests."""
    job_id = uuid.uuid4()
    version_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO jobs (id, tenant_id, name, status, owner_membership_id)
            VALUES (:id, :tenant, 'Replay close', 'draft', :owner)
            """
        ),
        {"id": job_id, "tenant": workspace.tenant_id, "owner": workspace.membership_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO job_versions (id, tenant_id, job_id, snapshot, name, correlation_id)
            VALUES (:id, :tenant, :job, CAST(:snapshot AS jsonb), 'Replay close', :correlation)
            """
        ),
        {
            "id": version_id,
            "tenant": workspace.tenant_id,
            "job": job_id,
            "snapshot": json.dumps({"steps": steps}),
            "correlation": CORRELATION,
        },
    )
    await session.execute(
        text(
            "UPDATE jobs SET status = 'published', published_version_id = :version WHERE id = :id"
        ),
        {"version": version_id, "id": job_id},
    )
    return job_id, version_id


async def _start(
    factory: async_sessionmaker[AsyncSession],
    workspace: Workspace,
    *,
    steps: list[dict[str, object]],
) -> tuple[uuid.UUID, uuid.UUID, RunRef]:
    """A committed run, ready for a worker to pick up."""
    async with factory() as session:
        async with tenant_scope(session, workspace.tenant_id):
            job_id, version_id = await _published_job(session, workspace, steps=steps)
            started = await service.start(
                session,
                tenant_id=workspace.tenant_id,
                job_version_id=version_id,
                trigger=RunTrigger.MANUAL,
                actor=await _context(session, workspace),
            )
        await session.commit()
    return (
        job_id,
        started.run_id,
        RunRef(
            tenant_id=str(workspace.tenant_id),
            run_id=str(started.run_id),
            correlation_id=CORRELATION,
        ),
    )


async def test_marking_a_run_running_twice_is_not_two_events(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The first replay a run meets, and the cheapest one to get wrong.

    A second `run.mark_running` after a redelivery would write a second *started* event. Nothing
    would break — and a year later somebody reading a run's evidence would see a run that started
    twice, and would have to decide whether that meant anything. Evidence has to be readable
    without knowing which worker restarted when.
    """
    left, _right = two_workspaces
    factory = build_sessionmaker(owner_engine)
    _job_id, run_id, ref = await _start(
        factory, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
    )
    activities = RunActivities(factory)

    await activities.mark_running(ref)
    await activities.mark_running(ref)

    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
            assert run.state == RunState.RUNNING
            started = (
                await session.execute(
                    select(func.count())
                    .select_from(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.kind == "run.started")
                )
            ).scalar_one()
            assert started == 1, "a redelivery is not a second start"


async def test_beginning_a_step_twice_counts_one_attempt(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A replay is not a retry, and the attempt column has to know the difference.

    `attempt` is what a person reads to decide whether a step is flaky. If it counted worker
    restarts as well as tries, a step that never failed once could show three attempts after an
    ordinary deployment — and the number would mean nothing.

    The distinction is a state check: `step.begin` returns when the step is not `pending`. The
    existing test moves the step back to `pending` first, which is the retry case; this one leaves
    it running, which is the replay.
    """
    left, _right = two_workspaces
    factory = build_sessionmaker(owner_engine)
    _job_id, _run_id, ref = await _start(
        factory, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
    )
    activities = RunActivities(factory)
    await activities.mark_running(ref)
    step_ref = await activities.next_step(ref)
    assert step_ref is not None

    await activities.begin_step(step_ref)
    await activities.begin_step(step_ref)

    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            step = (
                await session.execute(
                    select(RunStep).where(RunStep.id == uuid.UUID(step_ref.step_id))
                )
            ).scalar_one()
            assert step.state == StepState.RUNNING
            assert step.attempt == 1, "a redelivered begin is the same attempt"


async def test_performing_a_step_twice_records_one_result(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The one the exit criterion is actually about: the effect does not happen twice.

    `step.perform` is where a real effect will live — a model call, an integration, a payment.
    Today it records that no executor is wired, and it says so in the result rather than implying
    work that did not happen. What is being proven here is the shape around that: the second
    delivery finds the step finished, returns `already_finished`, and writes nothing.

    That is the property a real effect will depend on, and it is worth having tested *before* one
    is wired in, because afterwards a failure here costs a duplicate payment rather than a
    duplicate row.
    """
    left, _right = two_workspaces
    factory = build_sessionmaker(owner_engine)
    _job_id, run_id, ref = await _start(
        factory, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
    )
    activities = RunActivities(factory)
    await activities.mark_running(ref)
    step_ref = await activities.next_step(ref)
    assert step_ref is not None
    await activities.begin_step(step_ref)

    first = await activities.perform(step_ref)
    second = await activities.perform(step_ref)

    assert first == {"status": "no_executor"}
    assert second == {"status": "already_finished"}, "the second delivery does nothing"

    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            step = (
                await session.execute(
                    select(RunStep).where(RunStep.id == uuid.UUID(step_ref.step_id))
                )
            ).scalar_one()
            assert step.state == StepState.SUCCEEDED
            assert step.attempt == 1
            #  One completion event, not two. `run_events` is append-only, so a second write here
            #  could never be tidied up afterwards.
            finished = (
                await session.execute(
                    select(func.count())
                    .select_from(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.kind == "step.succeeded")
                )
            ).scalar_one()
            assert finished == 1


async def test_waiting_for_a_person_twice_makes_one_task(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A duplicate here is visible to somebody, which makes it the worst of the four.

    A redelivered `step.wait_for_person` that made a second task would put the same piece of work
    in a To-do list twice. The person does it, ticks one, and the other stays — so the list is
    wrong and the run is waiting on something already done.

    Two facts in one transaction, which is why the activity writes both: a step marked `waiting`
    with no task is a run waiting on nobody.
    """
    left, _right = two_workspaces
    factory = build_sessionmaker(owner_engine)
    _job_id, _run_id, ref = await _start(
        factory, left, steps=[{"what_exact_work": "Check the ledger", "mode": "human"}]
    )
    activities = RunActivities(factory)
    await activities.mark_running(ref)
    step_ref = await activities.next_step(ref)
    assert step_ref is not None
    await activities.begin_step(step_ref)

    await activities.wait_for_person(step_ref)
    await activities.wait_for_person(step_ref)

    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            step = (
                await session.execute(
                    select(RunStep).where(RunStep.id == uuid.UUID(step_ref.step_id))
                )
            ).scalar_one()
            assert step.state == StepState.WAITING
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(Task)
                    .where(Task.run_step_id == uuid.UUID(step_ref.step_id))
                )
            ).scalar_one()
            assert count == 1, "the same work must not appear twice in a To-do list"


async def test_finishing_a_run_twice_leaves_one_ending(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """And a finished run is not re-finished, so `finished_at` is when it ended.

    A second `run.finish` that moved the timestamp would make the run's duration a function of
    when the last worker happened to be redelivered a message.
    """
    left, _right = two_workspaces
    factory = build_sessionmaker(owner_engine)
    _job_id, run_id, ref = await _start(
        factory, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
    )
    activities = RunActivities(factory)
    await activities.mark_running(ref)
    step_ref = await activities.next_step(ref)
    assert step_ref is not None
    await activities.begin_step(step_ref)
    await activities.perform(step_ref)

    await activities.finish(ref)
    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
            ended_at = run.finished_at
    assert ended_at is not None

    await activities.finish(ref)
    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
            assert run.state == RunState.SUCCEEDED
            assert run.finished_at == ended_at, "the ending does not move"
            ended = (
                await session.execute(
                    select(func.count())
                    .select_from(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.kind == "run.succeeded")
                )
            ).scalar_one()
            assert ended == 1


async def test_a_failure_after_the_run_ended_is_ignored(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The nastiest ordering: a late redelivery of a failure for a run that already succeeded.

    It happens when a worker is killed just as it finishes, and the timeout fires before the
    result lands. Without the state check the run would flip from succeeded to failed hours later,
    and the evidence would say the work failed after somebody had already acted on its output.
    """
    left, _right = two_workspaces
    factory = build_sessionmaker(owner_engine)
    _job_id, run_id, ref = await _start(
        factory, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
    )
    activities = RunActivities(factory)
    await activities.mark_running(ref)
    step_ref = await activities.next_step(ref)
    assert step_ref is not None
    await activities.begin_step(step_ref)
    await activities.perform(step_ref)
    await activities.finish(ref)

    await activities.fail(ref, "a timeout that arrived after the work was done")

    async with factory() as session:
        async with tenant_scope(session, left.tenant_id):
            run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
            assert run.state == RunState.SUCCEEDED, "a finished run does not change its mind"
            assert run.failure_detail is None
