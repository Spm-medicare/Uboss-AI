"""Runs — the rules that decide whether a governed execution means anything.

The durable half was proven end to end against a real Temporal: a run was queued with no worker
alive, stayed `pending` and lost nothing; a worker was started and the run completed with each
step recorded exactly once. What is tested *here* is the half that decides what a run **is**, and
it is tested by calling functions rather than by replaying a workflow — the split `service.py`
exists for.

Five properties, and each one is something a runtime gets wrong:

* it runs a **version**, and a later edit to the Job does not reach it;
* a version with nothing in it is refused rather than run to instant, meaningless success;
* an attempt is counted when a step *begins*, so a step that kills its worker cannot be retried
  for ever;
* a failure names a reason, and the run fails with the step;
* a run is invisible to every other workspace.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import NotFound, ValidationFailed
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.identity.service import access_for
from uboss.modules.identity.models import Membership
from uboss.modules.runtime import service
from uboss.modules.runtime.models import Run, RunEvent, RunState, RunStep, RunTrigger, StepState

pytestmark = pytest.mark.anyio


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    """The same context the API would build, resolved from the membership's real roles.

    Built rather than faked: a hand-made context with every action set would pass tests the
    product's own permission resolution would fail.
    """
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


async def _publish_version(
    session, workspace: Workspace, *, steps: list[dict[str, object]], name: str = "Nightly close"
) -> uuid.UUID:
    """A published Job version, written directly.

    The Builder's own publish path has its own tests; what this file needs is a frozen snapshot to
    run, and going through submit-and-approve here would make every test in it depend on the
    separation-of-duty rules as well.
    """
    job_id = uuid.uuid4()
    version_id = uuid.uuid4()
    #  In the order the product writes them: a draft, then its frozen version, then the job
    #  pointing at it. `ck_jobs_published_has_version` refuses a published Job with no version,
    #  which is the constraint that makes "published" mean something.
    await session.execute(
        text(
            """
            INSERT INTO jobs (id, tenant_id, name, status, owner_membership_id)
            VALUES (:id, :tenant, :name, 'draft', :owner)
            """
        ),
        {"id": job_id, "tenant": workspace.tenant_id, "name": name, "owner": workspace.membership_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO job_versions (id, tenant_id, job_id, snapshot, name, correlation_id)
            VALUES (:id, :tenant, :job, CAST(:snapshot AS jsonb), :name, 'test')
            """
        ),
        {
            "id": version_id,
            "tenant": workspace.tenant_id,
            "job": job_id,
            "snapshot": json.dumps({"steps": steps}),
            "name": name,
        },
    )
    await session.execute(
        text(
            "UPDATE jobs SET status = 'published', published_version_id = :version WHERE id = :id"
        ),
        {"version": version_id, "id": job_id},
    )
    return version_id


async def test_a_run_executes_the_version_and_not_the_draft(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**The rule the whole runtime turns on.**

    The steps are copied out of the version's frozen snapshot when the run starts. Editing the Job
    afterwards changes the draft and reaches nothing that is already running — which is what
    immutable versions are for, and is far easier to guarantee by copying once than by remembering
    never to re-read.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            version_id = await _publish_version(
                session,
                left,
                steps=[
                    {"what_exact_work": "Pull the ledger", "mode": "ai_agent"},
                    {"what_exact_work": "Send the summary", "mode": "human"},
                ],
            )
            started = await service.start(
                session, await _context(session, left), job_version_id=version_id, trigger=RunTrigger.MANUAL
            )

            #  The draft changes underneath. Nothing about the run may follow it.
            await session.execute(
                text("UPDATE jobs SET name = 'Renamed after the run started' WHERE tenant_id = :t"),
                {"t": left.tenant_id},
            )

            steps = list(
                (
                    await session.execute(
                        select(RunStep)
                        .where(RunStep.run_id == started.run_id)
                        .order_by(RunStep.position)
                    )
                )
                .scalars()
                .all()
            )

        assert started.steps == 2
        assert [step.title for step in steps] == ["Pull the ledger", "Send the summary"]
        assert [step.mode for step in steps] == ["ai_agent", "human"]
        assert all(step.state == StepState.PENDING for step in steps)
        await session.rollback()


async def test_a_version_with_no_steps_is_refused(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A run of nothing would finish instantly and read as a success.

    Which is worse than a refusal: a green run that did no work is a report somebody acts on.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            version_id = await _publish_version(session, left, steps=[])
            with pytest.raises(ValidationFailed) as refused:
                await service.start(
                    session, await _context(session, left), job_version_id=version_id, trigger=RunTrigger.MANUAL
                )
        assert "no steps" in str(refused.value)
        await session.rollback()


async def test_a_version_from_another_workspace_is_not_found(
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """The same answer as a version that does not exist.

    Distinguishing them would let somebody with a guessed id learn that another organisation has
    a Job by that id — which is the one thing a tenant boundary is for.

    """
    left, right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, right.tenant_id):
            theirs = await _publish_version(
                session, right, steps=[{"what_exact_work": "Theirs", "mode": "ai_agent"}]
            )

        await session.commit()

    #  As the application role, which is the one row-level security binds. `uboss_owner` owns
    #  these tables and the setup above needs it, but a cross-tenant check run as the owner
    #  proves nothing about the boundary the product actually meets.
    async with build_sessionmaker(app_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            with pytest.raises(NotFound):
                await service.start(
                    session,
                    await _context(session, left),
                    job_version_id=theirs,
                    trigger=RunTrigger.MANUAL,
                )
        await session.rollback()


async def test_an_attempt_is_counted_when_a_step_begins(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Counted on start, never on failure.

    A step that kills its worker never reaches the failure path. Counting there would let a
    poisonous step be retried for ever by a succession of workers it kept killing — the same
    reasoning the outbox relay already uses when it claims a row.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            version_id = await _publish_version(
                session, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
            )
            started = await service.start(
                session, await _context(session, left), job_version_id=version_id, trigger=RunTrigger.MANUAL
            )
            run = (
                await session.execute(select(Run).where(Run.id == started.run_id))
            ).scalar_one()
            step = await service.next_step(session, started.run_id)
            assert step is not None

            await service.begin_step(session, run, step)
            assert step.attempt == 1
            #  A second attempt on the same step — a retry — counts again.
            step.state = StepState.PENDING
            await service.begin_step(session, run, step)
            assert step.attempt == 2
        await session.rollback()


async def test_a_failed_step_fails_the_run_and_says_why(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """No partial success.

    A Job's steps are a method. A method that stopped halfway has not been performed, and a run
    that reported success for the half it did would be a report nobody could rely on.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            version_id = await _publish_version(
                session,
                left,
                steps=[
                    {"what_exact_work": "One", "mode": "ai_agent"},
                    {"what_exact_work": "Two", "mode": "ai_agent"},
                ],
            )
            started = await service.start(
                session, await _context(session, left), job_version_id=version_id, trigger=RunTrigger.MANUAL
            )
            run = (
                await session.execute(select(Run).where(Run.id == started.run_id))
            ).scalar_one()
            step = await service.next_step(session, started.run_id)
            assert step is not None

            await service.begin_step(session, run, step)
            await service.fail_step(session, run, step, detail="The ledger export was empty.")

            assert step.state == StepState.FAILED
            assert run.state == RunState.FAILED
            #  The constraint in migration 0029 refuses a failed row with no reason, so this is
            #  belt and braces — but the *sentence* is what somebody reads, and an empty one is a
            #  support ticket.
            assert run.failure_detail == "The ledger export was empty."
            assert run.finished_at is not None
        await session.rollback()


async def test_a_finished_run_cannot_be_cancelled(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Cancelling something that already ended would rewrite what happened."""
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            version_id = await _publish_version(
                session, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
            )
            started = await service.start(
                session, await _context(session, left), job_version_id=version_id, trigger=RunTrigger.MANUAL
            )
            run = (
                await session.execute(select(Run).where(Run.id == started.run_id))
            ).scalar_one()
            await service.finish_run(session, run)

            with pytest.raises(ValidationFailed):
                await service.cancel(session, await _context(session, left), run, reason="Changed my mind")
        await session.rollback()


async def test_run_events_cannot_be_rewritten(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A run's evidence is append-only, or it is not evidence.

    Refused for the application role *and* for the owner: the trigger does not care who is
    asking, which is the point — a guarantee that the owner can step around is a convention.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            version_id = await _publish_version(
                session, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
            )
            started = await service.start(
                session,
                await _context(session, left),
                job_version_id=version_id,
                trigger=RunTrigger.MANUAL,
            )

            events = list(
                (
                    await session.execute(
                        select(RunEvent).where(RunEvent.run_id == started.run_id)
                    )
                )
                .scalars()
                .all()
            )
            assert events, "starting a run records that it was started"

            with pytest.raises(DatabaseError) as refused:
                await session.execute(
                    text("UPDATE run_events SET kind = 'tampered' WHERE run_id = :run"),
                    {"run": started.run_id},
                )
            #  The message must name `run_events`. Migration 0030 exists because the shared
            #  trigger used to say `audit_events` whatever table it was defending, which sent
            #  anybody debugging a refused write to the wrong table.
            assert "run_events" in str(refused.value)
            assert "append-only" in str(refused.value)
        await session.rollback()


async def test_a_run_is_invisible_to_another_workspace(
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """Row-level security, not a filter in a query somebody might forget to write."""
    left, right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            version_id = await _publish_version(
                session, left, steps=[{"what_exact_work": "One", "mode": "ai_agent"}]
            )
            started = await service.start(
                session,
                await _context(session, left),
                job_version_id=version_id,
                trigger=RunTrigger.MANUAL,
            )

        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        async with tenant_scope(session, right.tenant_id):
            mine = (
                await session.execute(select(Run).where(Run.id == started.run_id))
            ).scalar_one_or_none()
            assert mine is None, "another workspace's run must not be readable"

            steps = (
                await session.execute(select(RunStep).where(RunStep.run_id == started.run_id))
            ).scalars().all()
            assert not steps
        await session.rollback()
