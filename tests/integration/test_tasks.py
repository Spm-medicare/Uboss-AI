"""Tasks — the rules that decide whether a To-do list is governed work or a list of strings.

Tested by calling the service, which is the split `service.py` exists for: the durable half is
Temporal's, and none of it is needed to prove what a task *is*.

Seven properties, each one something a work list gets wrong:

* a task is created from the version the run pinned, with §8's WHO rules resolved once;
* a WHO rule that matches nobody produces an **unassigned** task, not a guessed one;
* creating twice for one step returns the first task rather than a second;
* completing a task finishes its step, so the run and the list cannot disagree;
* a rejection without a reason is refused, by the service and by the database;
* declining hands the work back rather than failing the run;
* delegating closes the original as `delegated`, not as `done`.
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
from uboss.core.errors import Conflict, ValidationFailed
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for
from uboss.modules.runtime import service as runtime
from uboss.modules.runtime.models import Run, RunStep, RunTrigger, StepState
from uboss.modules.tasks import assignment
from uboss.modules.tasks import service as tasks
from uboss.modules.tasks.models import Task, TaskKind, TaskOutcome, TaskState

pytestmark = pytest.mark.anyio


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    """The context the API would build, from the membership's real roles — never a faked one."""
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


async def _publish(
    session: AsyncSession,
    workspace: Workspace,
    *,
    steps: list[dict[str, object]],
    rules: list[dict[str, object]] | None = None,
) -> uuid.UUID:
    """A published version with a frozen snapshot, written directly.

    The Builder's publish path has its own tests; going through submit-and-approve here would make
    every test in this file depend on the separation-of-duty rules as well.
    """
    job_id = uuid.uuid4()
    version_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO jobs (id, tenant_id, name, status, owner_membership_id)
            VALUES (:id, :tenant, 'Month end', 'draft', :owner)
            """
        ),
        {"id": job_id, "tenant": workspace.tenant_id, "owner": workspace.membership_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO job_versions (id, tenant_id, job_id, snapshot, name, correlation_id)
            VALUES (:id, :tenant, :job, CAST(:snapshot AS jsonb), 'Month end', 'test')
            """
        ),
        {
            "id": version_id,
            "tenant": workspace.tenant_id,
            "job": job_id,
            "snapshot": json.dumps(
                {"steps": steps, "assignment_rules": rules or []}
            ),
        },
    )
    await session.execute(
        text(
            "UPDATE jobs SET status = 'published', published_version_id = :v WHERE id = :id"
        ),
        {"v": version_id, "id": job_id},
    )
    return version_id


async def _run_to_first_step(
    session: AsyncSession,
    workspace: Workspace,
    *,
    steps: list[dict[str, object]],
    rules: list[dict[str, object]] | None = None,
) -> tuple[Run, RunStep, SecurityContext]:
    """Start a run and take it to its first step, the way the workflow does."""
    context = await _context(session, workspace)
    version_id = await _publish(session, workspace, steps=steps, rules=rules)
    started = await runtime.start(
        session,
        tenant_id=workspace.tenant_id,
        job_version_id=version_id,
        trigger=RunTrigger.MANUAL,
        actor=context,
    )
    run = (
        await session.execute(select(Run).where(Run.id == started.run_id))
    ).scalar_one()
    step = await runtime.next_step(session, run.id)
    assert step is not None
    await runtime.begin_step(session, run, step)
    await runtime.wait_for_person(session, run, step)
    return run, step, context


async def test_a_task_is_made_from_the_version_and_the_rule_resolves_once(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The task's instructions come from the **frozen** step, and WHO is answered at creation.

    Both halves matter. The instructions are the ones the version recorded, so editing the Job
    afterwards cannot change what a person was asked to do; and the assignee is written down,
    so somebody who transfers next week does not silently lose work already given to them.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, _context = await _run_to_first_step(
                session,
                left,
                steps=[
                    {
                        "position": 1,
                        "what_exact_work": "Reconcile the ledger",
                        "how_exact_method": "Match against the bank file",
                        "output": "A signed reconciliation",
                        "mode": "human",
                    }
                ],
                rules=[
                    {
                        "position": 1,
                        "who_type": "user",
                        "target_id": str(left.membership_id),
                    }
                ],
            )

            task = await tasks.create_for_step(session, run, step)

            assert task.assignee_membership_id == left.membership_id
            assert task.assigned_via == "user"
            assert task.kind == TaskKind.WORK
            assert task.state == TaskState.PENDING
            assert task.instructions is not None
            #  The words the author wrote, labelled — not a sentence this code invented.
            assert "Reconcile the ledger" in task.instructions
            assert "Match against the bank file" in task.instructions


async def test_a_rule_that_matches_nobody_leaves_the_task_unassigned(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**The honest empty answer.**

    A role with no holder, a vacant seat, an archived department: the task is created with nobody
    on it and says why. Inventing an assignee to avoid a blank would put somebody's name against
    work nobody chose them for.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, _context = await _run_to_first_step(
                session,
                left,
                steps=[{"position": 1, "what_exact_work": "Check it", "mode": "human"}],
                #  A role id that belongs to nothing, and a group nothing evaluates.
                rules=[
                    {"position": 1, "who_type": "role", "target_id": str(uuid.uuid4())},
                    {"position": 2, "who_type": "dynamic_group", "target_id": None},
                ],
            )

            task = await tasks.create_for_step(session, run, step)

            assert task.assignee_membership_id is None
            assert task.assigned_via == assignment.UNRESOLVED


async def test_creating_a_task_twice_for_one_step_returns_the_first(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """At-least-once delivery is the contract, so the activity must be safe to repeat.

    Proven twice over: the function returns the same row, and the partial unique index refuses a
    second open task even when the check is bypassed.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, _context = await _run_to_first_step(
                session,
                left,
                steps=[{"position": 1, "what_exact_work": "Check it", "mode": "human"}],
            )

            first = await tasks.create_for_step(session, run, step)
            again = await tasks.create_for_step(session, run, step)
            assert again.id == first.id

            count = (
                (await session.execute(select(Task).where(Task.run_step_id == step.id)))
                .scalars()
                .all()
            )
            assert len(count) == 1

            #  And the database refuses a second one on its own. In a savepoint, because a
            #  failed insert poisons the transaction it runs in and the rest of the test still
            #  needs one.
            with pytest.raises(DatabaseError):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            """
                            INSERT INTO tasks
                                (tenant_id, run_id, run_step_id, kind, title, state)
                            VALUES (:t, :r, :s, 'work', 'A second open task', 'pending')
                            """
                        ),
                        {"t": left.tenant_id, "r": run.id, "s": step.id},
                    )


async def test_completing_a_task_finishes_its_step(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**One transaction, both facts.**

    A done task on a step still `waiting` is a run nobody can explain. The step also carries what
    was decided and by whom, so the run's evidence answers "what happened at step 1" without a
    join to a table the reader may not know exists.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session,
                left,
                steps=[{"position": 1, "what_exact_work": "Sign it", "mode": "human"}],
                rules=[
                    {"position": 1, "who_type": "user", "target_id": str(left.membership_id)}
                ],
            )
            task = await tasks.create_for_step(session, run, step)

            await tasks.complete(
                session, context, task, outcome=TaskOutcome.COMPLETED, note="Signed."
            )

            assert task.state == TaskState.DONE
            assert task.completed_by_membership_id == left.membership_id
            refreshed = await session.get(RunStep, step.id)
            assert refreshed is not None
            assert refreshed.state == StepState.SUCCEEDED
            assert refreshed.result is not None
            assert refreshed.result["outcome"] == TaskOutcome.COMPLETED
            assert refreshed.result["task_id"] == str(task.id)

            #  A second completion is a conflict, not a repeat: somebody is recording a different
            #  decision on work already decided.
            with pytest.raises(Conflict):
                await tasks.complete(
                    session, context, task, outcome=TaskOutcome.COMPLETED, note=None
                )


async def test_a_rejection_must_say_why(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Refused by the service with a sentence, and by the database with a constraint.

    Two boundaries because they answer different questions: the service is what a person sees,
    and the constraint is what holds when somebody writes to the table directly.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session,
                left,
                steps=[
                    {
                        "position": 1,
                        "approval": "Finance director signs off",
                        "mode": "human",
                    }
                ],
                rules=[
                    {"position": 1, "who_type": "user", "target_id": str(left.membership_id)}
                ],
            )
            task = await tasks.create_for_step(session, run, step)
            #  A step with an approval is an approval task, decided from the step's own fields.
            assert task.kind == TaskKind.APPROVAL

            with pytest.raises(ValidationFailed):
                await tasks.complete(
                    session, context, task, outcome=TaskOutcome.REJECTED, note="   "
                )
            #  And an outcome that does not belong to this kind of task.
            with pytest.raises(ValidationFailed):
                await tasks.complete(
                    session, context, task, outcome=TaskOutcome.PROVIDED, note=None
                )
            #  The constraint, in a savepoint: what holds when somebody writes to the table
            #  directly rather than through the service.
            with pytest.raises(DatabaseError):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            """
                            UPDATE tasks SET state = 'done', outcome = 'rejected',
                                outcome_note = NULL, completed_at = now(),
                                completed_by_membership_id = :m
                            WHERE id = :id
                            """
                        ),
                        {"id": task.id, "m": left.membership_id},
                    )


async def test_declining_hands_the_work_back_rather_than_failing_the_run(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """"Not me" is information about the assignment, not about the work.

    The step stays `waiting` and a fresh, unheld task takes the closed one's place. A runtime that
    failed the run because one person declined would teach people never to decline.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session,
                left,
                steps=[{"position": 1, "what_exact_work": "File it", "mode": "human"}],
                rules=[
                    {"position": 1, "who_type": "user", "target_id": str(left.membership_id)}
                ],
            )
            task = await tasks.create_for_step(session, run, step)

            await tasks.decline(session, context, task, reason="This is not my department.")

            assert task.state == TaskState.DECLINED
            refreshed_step = await session.get(RunStep, step.id)
            assert refreshed_step is not None
            assert refreshed_step.state == StepState.WAITING

            replacement = await tasks.open_for_step(session, step.id)
            assert replacement is not None
            assert replacement.id != task.id
            assert replacement.assignee_membership_id is None


async def test_delegating_closes_the_original_as_delegated(
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Passed on, not performed.

    `DELEGATED` rather than `DONE` because a report that counted delegations as completions would
    overstate what got done — and the new task names who sent it, so "why me?" has an answer with
    a person in it.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session,
                left,
                steps=[{"position": 1, "what_exact_work": "Review it", "mode": "human"}],
                rules=[
                    {"position": 1, "who_type": "user", "target_id": str(left.membership_id)}
                ],
            )
            task = await tasks.create_for_step(session, run, step)

            handed = await tasks.delegate(
                session, context, task, to_membership_id=colleague, note="You know this one."
            )

            assert task.state == TaskState.DELEGATED
            assert task.state not in (TaskState.DONE,)
            assert handed.assignee_membership_id == colleague
            assert handed.assigned_by_membership_id == left.membership_id
            assert handed.assigned_via == "delegation"
            assert handed.state == TaskState.PENDING
            #  Still one open task for the step: the closed one no longer counts.
            assert (await tasks.open_for_step(session, step.id)) is not None
