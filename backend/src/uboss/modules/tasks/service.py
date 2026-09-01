"""What a person does with a task — the domain half of §11's To-do list.

**Nothing here imports Temporal.** The same split `runtime/service.py` keeps: these are the
operations, and `api.py` is what drives them and sends the signal afterwards. A rule that only
existed inside a route would be a rule provable only by making an HTTP request.

## A task is created by the runtime, never by a person

There is no "new task" verb. A task exists because a published version has a human step and a run
reached it — which is what makes the To-do list a view of governed work rather than a second,
ungoverned place to record things. `create_for_step` is called from the activity that marks a step
`waiting`, in the same transaction, so a waiting step always has a task and a task always has a
step.

## Closing a task closes the step

`complete` finishes the run step as well, in one transaction. The two could drift if they were
written apart — a done task on a step still `waiting`, which is a run nobody can explain — and the
database is where the screens read both from.

The Temporal signal is sent *after* that transaction commits, by the caller. The signal carries
nothing, so a signal that arrived first would wake the workflow to find the step unchanged.

## Declining is not failing

A person may say "this is not mine" or "this cannot be done". `DECLINED` closes the task and
leaves the step `waiting`, with a fresh task nobody holds: the work still needs doing and the run
is still the place it belongs. What is *not* done is silently failing the run because one person
said no.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.logging import get_logger
from uboss.modules.approvals import service as approvals
from uboss.modules.audit import service as audit
from uboss.modules.jobs.models import JobVersion
from uboss.modules.notifications import fanout
from uboss.modules.notifications import service as notify
from uboss.modules.notifications.models import Category
from uboss.modules.runtime import service as runtime
from uboss.modules.runtime.models import Run, RunStep, StepState
from uboss.modules.tasks import assignment
from uboss.modules.tasks.models import (
    Task,
    TaskComment,
    TaskEvidence,
    TaskFollower,
    TaskKind,
    TaskOutcome,
    TaskState,
)

log = get_logger(__name__)

#: Which outcomes belong to which kind of task. An approval is approved or rejected; work is
#: completed; an input is provided. Enforced here as well as by the check constraint, so the
#: message a person sees is a sentence rather than a constraint name.
OUTCOMES_FOR: dict[str, frozenset[str]] = {
    TaskKind.WORK: frozenset({TaskOutcome.COMPLETED, TaskOutcome.PROVIDED}),
    TaskKind.INPUT: frozenset({TaskOutcome.PROVIDED, TaskOutcome.COMPLETED}),
    TaskKind.APPROVAL: frozenset(
        {TaskOutcome.APPROVED, TaskOutcome.REJECTED, TaskOutcome.CHANGES_REQUESTED}
    ),
}


# ── the runtime creates them ─────────────────────────────────────────────────────────────


async def create_for_step(session: AsyncSession, run: Run, step: RunStep) -> Task:
    """The task for a human step. Idempotent: an existing open one is returned unchanged.

    Called from the activity that marks the step `waiting`, so at-least-once delivery cannot
    produce two tasks for one step — and `uq_tasks_one_open_per_step` refuses it at the database
    even if this check were ever skipped.
    """
    existing = await open_for_step(session, step.id)
    if existing is not None:
        return existing

    snapshot = await _snapshot(session, run)
    frozen = _step_of(snapshot, step.position)
    rules = _rules_of(snapshot)

    who = await assignment.resolve(session, rules, position=step.position)
    kind = _kind_of(frozen)

    task = Task(
        tenant_id=run.tenant_id,
        run_id=run.id,
        run_step_id=step.id,
        kind=kind,
        title=step.title,
        instructions=_instructions(frozen),
        assignee_membership_id=who.membership_id,
        assigned_via=who.via,
        state=TaskState.PENDING,
    )
    session.add(task)
    #  Flushed so the caller's postcondition is true — the sessionmaker sets `autoflush=False`,
    #  and an activity that created a task and then read it back would otherwise find nothing.
    await session.flush()

    #  An approval step gets its approval row here, in the same transaction. The two are one
    #  fact — "somebody must decide this" — and a task that existed without its approval would be
    #  a decision with no record of who asked or who was entitled to make it.
    await approvals.raise_for_task(
        session,
        run,
        task,
        frozen_step=frozen,
        escalation_note=_escalation_of(snapshot),
    )

    #  Told once, when the work becomes theirs. Nothing is raised for an unassigned task: there
    #  is nobody to tell, and addressing it to an administrator is how a bell becomes a thing
    #  administrators mute.
    if task.assignee_membership_id is not None:
        await notify.task_assigned(
            session,
            tenant_id=run.tenant_id,
            membership_id=task.assignee_membership_id,
            task_id=task.id,
            run_id=run.id,
            title=task.title,
            kind=kind,
            actor_membership_id=run.started_by_membership_id,
        )

    log.info(
        "task_created",
        task_id=str(task.id),
        run_id=str(run.id),
        kind=kind,
        assigned=who.membership_id is not None,
        via=who.via,
    )
    return task


async def open_for_step(session: AsyncSession, run_step_id: uuid.UUID) -> Task | None:
    return (
        await session.execute(
            select(Task).where(
                Task.run_step_id == run_step_id, Task.state.in_(TaskState.open())
            )
        )
    ).scalar_one_or_none()


# ── what a person does ───────────────────────────────────────────────────────────────────


async def start(session: AsyncSession, context: SecurityContext, task: Task) -> Task:
    """Pick it up. Only moves `pending` → `in_progress`; anything else is left alone.

    Deliberately forgiving rather than an error: two clicks on *Start* is not a conflict, and a
    person opening a task they already started should not be told off.
    """
    if task.state == TaskState.PENDING:
        task.state = TaskState.IN_PROGRESS
        task.updated_at = datetime.now(UTC)
        await session.flush()
    return task


async def complete(
    session: AsyncSession,
    context: SecurityContext,
    task: Task,
    *,
    outcome: str,
    note: str | None,
) -> Task:
    """Finish a task and its step, in one transaction.

    Refuses when the task is already closed — that *is* a conflict, because the second caller is
    recording a different decision on work somebody else has already decided.
    """
    _must_be_open(task)
    _check_outcome(task, outcome, note)

    step = await _step(session, task)
    run = await _run(session, task)

    #  An approval task's decision is recorded on the approval as well, in this transaction and
    #  before the task is touched. `decide` refuses a self-approval — so a caller that reached
    #  here without the route's guard still cannot record one, and nothing is half-written.
    approval = await approvals.for_task(session, task.id)
    if approval is not None:
        await approvals.decide(
            session, context, approval, state=_state_for(outcome), reason=note
        )

    now = datetime.now(UTC)
    task.state = TaskState.DONE
    task.outcome = outcome
    task.outcome_note = note
    task.completed_at = now
    task.completed_by_membership_id = context.membership_id
    task.updated_at = now

    #  The step carries what was decided, so a run's evidence answers "what happened at step 3"
    #  without a join to a table a reader may not know exists.
    await runtime.finish_step(
        session,
        run,
        step,
        result={
            "outcome": outcome,
            "note": note,
            "by_membership_id": str(context.membership_id),
            "task_id": str(task.id),
        },
    )
    #  What the person produced, recorded as the run's output rather than only inside the step's
    #  result blob. The name comes from the published version — Form 3 gives every step an
    #  `Output`, so this was named in the design before it existed — and the note and each attached
    #  file become rows somebody can list, count and open.
    #
    #  `record_output` returns nothing for an empty note, so a task completed with no note and no
    #  attachment records no output. A row for it would be a run claiming to have produced
    #  something it cannot show.
    name, destination = await runtime.designed_output(session, run, step)
    await runtime.record_output(
        session, run, step, name=name, destination=destination, value_text=note
    )
    attached = (
        (
            await session.execute(
                select(TaskEvidence)
                .where(TaskEvidence.task_id == task.id)
                .order_by(TaskEvidence.created_at)
            )
        )
        .scalars()
        .all()
    )
    for proof in attached:
        await runtime.record_output(
            session,
            run,
            step,
            name=name,
            destination=destination,
            file_id=proof.file_id,
        )

    #  Everybody watching, except whoever just did it. An approval's own decision notice is
    #  raised by `approvals.decide`, which knows who asked; this is the task-level report.
    if approval is None:
        for watcher in await fanout.watchers_of_task(
            session, task, exclude=context.membership_id
        ):
            await notify.raise_for(
                session,
                tenant_id=task.tenant_id,
                membership_id=watcher,
                category=Category.TASK_ASSIGNMENT,
                event="task.completed",
                title=f"{task.title} was completed",
                body=note,
                deep_link=f"/todo?task={task.id}",
                dedupe_key=f"task-completed:{task.id}",
                group_key=f"run:{task.run_id}",
                subject_type="task",
                subject_id=task.id,
                actor_membership_id=context.membership_id,
            )

    await audit.record(
        session,
        tenant_id=task.tenant_id,
        action="tasks.completed",
        resource_type="task",
        resource_id=task.id,
        actor=context,
        detail={"outcome": outcome, "run_id": str(task.run_id)},
    )
    await session.flush()
    log.info("task_completed", task_id=str(task.id), outcome=outcome)
    return task


async def decline(
    session: AsyncSession, context: SecurityContext, task: Task, *, reason: str
) -> Task:
    """Hand it back. The task closes; the step stays waiting and gets a fresh, unheld task.

    The run is not failed and the step is not skipped. Somebody saying "not me" is information
    about the assignment, not about the work — and a runtime that failed a run because one person
    declined would teach people never to decline.
    """
    _must_be_open(task)
    if not reason.strip():
        raise ValidationFailed("Say why you are handing this back.")

    now = datetime.now(UTC)
    task.state = TaskState.DECLINED
    task.outcome_note = reason
    task.completed_at = now
    task.completed_by_membership_id = context.membership_id
    task.updated_at = now
    await session.flush()

    #  A replacement, unassigned. Written after the flush so the partial unique index sees the
    #  first one closed — the index is what guarantees one open task per step, and it is checked
    #  per statement.
    replacement = Task(
        tenant_id=task.tenant_id,
        run_id=task.run_id,
        run_step_id=task.run_step_id,
        kind=task.kind,
        title=task.title,
        instructions=task.instructions,
        assignee_membership_id=None,
        assigned_via=assignment.UNRESOLVED,
        state=TaskState.PENDING,
        due_at=task.due_at,
    )
    session.add(replacement)
    await session.flush()

    #  The approval that was addressed to this person is withdrawn — not rejected: nobody said
    #  no. The replacement raises its own, so who was asked first survives on the closed row.
    await approvals.withdraw_for_task(
        session, task, why="Handed back before it was decided."
    )
    run = await _run(session, task)
    snapshot = await _snapshot(session, run)
    await approvals.raise_for_task(
        session,
        run,
        replacement,
        frozen_step=_step_of(snapshot, await _position_of(session, task)),
        escalation_note=_escalation_of(snapshot),
    )

    #  The replacement is unassigned and nothing else escalates it — the step simply stays
    #  waiting. So this notification is the only thing that closes the loop: somebody who may
    #  hand work out has to learn the task needs an owner.
    for watcher in await fanout.watchers_of_task(
        session, task, exclude=context.membership_id
    ):
        await notify.raise_for(
            session,
            tenant_id=task.tenant_id,
            membership_id=watcher,
            category=Category.TASK_ASSIGNMENT,
            event="task.declined",
            title=f"{task.title} was handed back",
            body=reason,
            deep_link=f"/todo?tab=mine&task={replacement.id}",
            dedupe_key=f"task-declined:{task.id}",
            subject_type="task",
            subject_id=replacement.id,
            actor_membership_id=context.membership_id,
            #: Somebody has to give it an owner. That is an action.
            action_required=True,
        )

    await audit.record(
        session,
        tenant_id=task.tenant_id,
        action="tasks.declined",
        resource_type="task",
        resource_id=task.id,
        actor=context,
        detail={"reason": reason[:500], "run_id": str(task.run_id)},
    )
    await session.flush()
    log.info("task_declined", task_id=str(task.id), replacement_id=str(replacement.id))
    return task


async def delegate(
    session: AsyncSession,
    context: SecurityContext,
    task: Task,
    *,
    to_membership_id: uuid.UUID,
    note: str | None,
) -> Task:
    """Pass it to somebody else, on the record.

    The original closes as `DELEGATED` rather than `DONE`: it was passed on, not performed, and a
    report that counted delegations as completions would overstate what got done. The new task
    names who sent it, so "why me?" has an answer with a person in it.

    The person who delegated follows the new task automatically. They are still accountable for it
    and would otherwise lose sight of work they are answerable for.
    """
    _must_be_open(task)
    if to_membership_id == task.assignee_membership_id:
        raise ValidationFailed("That is already who this task belongs to.")
    if not await assignment.is_active(
        session, to_membership_id, tenant_id=task.tenant_id
    ):
        raise ValidationFailed("That person is not active in this workspace.")

    now = datetime.now(UTC)
    task.state = TaskState.DELEGATED
    task.outcome_note = note
    task.completed_at = now
    task.completed_by_membership_id = context.membership_id
    task.updated_at = now
    await session.flush()

    handed = Task(
        tenant_id=task.tenant_id,
        run_id=task.run_id,
        run_step_id=task.run_step_id,
        kind=task.kind,
        title=task.title,
        instructions=task.instructions,
        assignee_membership_id=to_membership_id,
        assigned_by_membership_id=context.membership_id,
        assigned_via="delegation",
        state=TaskState.PENDING,
        due_at=task.due_at,
    )
    session.add(handed)
    await session.flush()

    await approvals.withdraw_for_task(
        session, task, why="Delegated before it was decided."
    )
    delegated_run = await _run(session, task)
    delegated_snapshot = await _snapshot(session, delegated_run)
    await approvals.raise_for_task(
        session,
        delegated_run,
        handed,
        frozen_step=_step_of(delegated_snapshot, await _position_of(session, task)),
        escalation_note=_escalation_of(delegated_snapshot),
    )

    session.add(
        TaskFollower(
            tenant_id=task.tenant_id,
            task_id=handed.id,
            membership_id=context.membership_id,
        )
    )
    await notify.task_assigned(
        session,
        tenant_id=task.tenant_id,
        membership_id=to_membership_id,
        task_id=handed.id,
        run_id=task.run_id,
        title=task.title,
        kind=task.kind,
        actor_membership_id=context.membership_id,
    )

    await audit.record(
        session,
        tenant_id=task.tenant_id,
        action="tasks.delegated",
        resource_type="task",
        resource_id=task.id,
        actor=context,
        detail={"to_membership_id": str(to_membership_id), "new_task_id": str(handed.id)},
    )
    await session.flush()
    log.info("task_delegated", task_id=str(task.id), new_task_id=str(handed.id))
    return handed


async def reassign(
    session: AsyncSession,
    context: SecurityContext,
    task: Task,
    *,
    to_membership_id: uuid.UUID,
) -> Task:
    """Give an open task to somebody, without closing it.

    How an unassigned task — a WHO rule that matched nobody — gets an owner. Distinct from
    delegation: nothing was passed on, so nothing is closed, and the task keeps its history.
    """
    _must_be_open(task)
    if not await assignment.is_active(
        session, to_membership_id, tenant_id=task.tenant_id
    ):
        raise ValidationFailed("That person is not active in this workspace.")

    #  **Captured before the column is overwritten.** Two lines down the previous holder is
    #  unrecoverable, and they are precisely the person who needs telling that the work is no
    #  longer theirs.
    previous = task.assignee_membership_id

    task.assignee_membership_id = to_membership_id
    task.assigned_by_membership_id = context.membership_id
    task.assigned_via = "manual"
    task.updated_at = datetime.now(UTC)

    await notify.task_assigned(
        session,
        tenant_id=task.tenant_id,
        membership_id=to_membership_id,
        task_id=task.id,
        run_id=task.run_id,
        title=task.title,
        kind=task.kind,
        actor_membership_id=context.membership_id,
    )
    if previous is not None and previous != to_membership_id:
        await notify.raise_for(
            session,
            tenant_id=task.tenant_id,
            membership_id=previous,
            category=Category.TASK_ASSIGNMENT,
            event="task.reassigned_away",
            title=f"{task.title} is no longer yours",
            deep_link=f"/todo?task={task.id}",
            dedupe_key=f"task-away:{task.id}",
            subject_type="task",
            subject_id=task.id,
            actor_membership_id=context.membership_id,
        )
    await audit.record(
        session,
        tenant_id=task.tenant_id,
        action="tasks.reassigned",
        resource_type="task",
        resource_id=task.id,
        actor=context,
        detail={"to_membership_id": str(to_membership_id)},
    )
    await session.flush()
    return task


# ── conversation and proof ───────────────────────────────────────────────────────────────


async def comment(
    session: AsyncSession, context: SecurityContext, task: Task, *, body: str
) -> TaskComment:
    """Say something on a task. Append-only — see the trigger in 0032.

    Allowed on a closed task on purpose: the question that matters most is often asked after a
    decision, and a comment box that shuts when the task does sends that conversation to email.
    """
    if not body.strip():
        raise ValidationFailed("Write something first.")
    row = TaskComment(
        tenant_id=task.tenant_id,
        task_id=task.id,
        membership_id=context.membership_id,
        body=body.strip(),
    )
    session.add(row)
    await session.flush()

    #  Comments are allowed on a closed task, which is exactly when this matters: the task is in
    #  nobody's open list any more, so the notification is the entire delivery mechanism.
    for watcher in await fanout.watchers_of_task(
        session, task, exclude=context.membership_id
    ):
        await notify.commented(
            session,
            tenant_id=task.tenant_id,
            membership_id=watcher,
            task_id=task.id,
            author_membership_id=context.membership_id,
            author_name=context.display_name,
            excerpt=row.body,
        )
    return row


async def attach(
    session: AsyncSession,
    context: SecurityContext,
    task: Task,
    *,
    file_id: uuid.UUID,
    note: str | None,
) -> TaskEvidence:
    """Attach a file already uploaded to this workspace as evidence.

    A join to `files`, never a second copy — the file's own scanning, retention and access rules
    keep applying, which they would not to a copy this table made.
    """
    _must_be_open(task)
    already = (
        await session.execute(
            select(TaskEvidence).where(
                TaskEvidence.task_id == task.id, TaskEvidence.file_id == file_id
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        #  Attaching the same file twice is a double click, not a conflict.
        return already

    row = TaskEvidence(
        tenant_id=task.tenant_id,
        task_id=task.id,
        file_id=file_id,
        attached_by_membership_id=context.membership_id,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def follow(session: AsyncSession, context: SecurityContext, task: Task) -> None:
    already = (
        await session.execute(
            select(TaskFollower).where(
                TaskFollower.task_id == task.id,
                TaskFollower.membership_id == context.membership_id,
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        return
    session.add(
        TaskFollower(
            tenant_id=task.tenant_id,
            task_id=task.id,
            membership_id=context.membership_id,
        )
    )
    await session.flush()


async def unfollow(session: AsyncSession, context: SecurityContext, task: Task) -> None:
    row = (
        await session.execute(
            select(TaskFollower).where(
                TaskFollower.task_id == task.id,
                TaskFollower.membership_id == context.membership_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.flush()


# ── counting ─────────────────────────────────────────────────────────────────────────────


async def open_count(session: AsyncSession, membership_id: uuid.UUID) -> int:
    """What the sidebar shows: open tasks assigned to me.

    Assigned to *me*, not to everybody — a badge counting work that is not mine is a badge people
    learn to ignore. Unassigned tasks are somebody's to hand out, and they appear in the *All*
    tab rather than in this count.
    """
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.assignee_membership_id == membership_id,
                    Task.state.in_(TaskState.open()),
                )
            )
        ).scalar_one()
    )


# ── internals ────────────────────────────────────────────────────────────────────────────


def _must_be_open(task: Task) -> None:
    if task.state in TaskState.closed():
        raise Conflict(
            "That task has already been closed. Open it to see what was decided and by whom."
        )


def _check_outcome(task: Task, outcome: str, note: str | None) -> None:
    allowed = OUTCOMES_FOR.get(task.kind, frozenset())
    if outcome not in allowed:
        raise ValidationFailed(
            f"'{outcome}' is not something a {task.kind} task can end with."
        )
    if outcome in TaskOutcome.needs_reason() and not (note or "").strip():
        raise ValidationFailed("Say why. A rejection without a reason cannot be acted on.")


async def _step(session: AsyncSession, task: Task) -> RunStep:
    step = (
        await session.execute(select(RunStep).where(RunStep.id == task.run_step_id))
    ).scalar_one_or_none()
    if step is None:
        raise NotFound("The step this task belongs to no longer exists.")
    if step.state in StepState.finished():
        raise Conflict("That step has already finished, so this task cannot change it.")
    return step


async def _run(session: AsyncSession, task: Task) -> Run:
    run = (
        await session.execute(select(Run).where(Run.id == task.run_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFound("The run this task belongs to no longer exists.")
    return run


async def _snapshot(session: AsyncSession, run: Run) -> dict[str, Any]:
    """The version the run is executing. Read defensively — see `runtime.service._steps_of`."""
    version = (
        await session.execute(
            select(JobVersion).where(JobVersion.id == run.job_version_id)
        )
    ).scalar_one_or_none()
    if version is None or not isinstance(version.snapshot, dict):
        return {}
    return version.snapshot


def _step_of(snapshot: dict[str, Any], position: int) -> dict[str, Any]:
    steps = snapshot.get("steps")
    if not isinstance(steps, list):
        return {}
    for step in steps:
        if isinstance(step, dict) and step.get("position") == position:
            return step
    return {}


def _rules_of(snapshot: dict[str, Any]) -> list[dict[str, object]]:
    rules = snapshot.get("assignment_rules")
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def _escalation_of(snapshot: dict[str, Any]) -> str | None:
    """The Job's `escalation_to`, as its author typed it.

    Free text on the Job, so free text here. Resolving it to a person would be inventing a route
    out of a label somebody wrote for a human reader.
    """
    job = snapshot.get("job")
    if not isinstance(job, dict):
        return None
    value = str(job.get("escalation_to") or "").strip()
    return value[:200] or None


async def _position_of(session: AsyncSession, task: Task) -> int:
    """Which step of the run this task belongs to."""
    return int(
        (
            await session.execute(
                select(RunStep.position).where(RunStep.id == task.run_step_id)
            )
        ).scalar_one()
    )


#: Which approval state an outcome means. The reverse of `approvals.OUTCOME_FOR`, kept beside the
#: outcome checking so the two records of one decision cannot drift.
_STATE_FOR: dict[str, str] = {
    TaskOutcome.APPROVED: "approved",
    TaskOutcome.REJECTED: "rejected",
    TaskOutcome.CHANGES_REQUESTED: "changes_requested",
}


def _state_for(outcome: str) -> str:
    state = _STATE_FOR.get(outcome)
    if state is None:
        raise ValidationFailed(f"'{outcome}' is not an approval decision.")
    return state


def _kind_of(frozen: dict[str, Any]) -> str:
    """Which of §11's three kinds this step is.

    From the step's own fields, not from a fourth column somebody would have to keep in step:
    a step with an `approval` is an approval; a step whose work is to supply something is an
    input; everything else is work.
    """
    if str(frozen.get("approval") or "").strip():
        return TaskKind.APPROVAL
    if str(frozen.get("input_exact") or "").strip() and not str(
        frozen.get("what_exact_work") or ""
    ).strip():
        return TaskKind.INPUT
    return TaskKind.WORK


def _instructions(frozen: dict[str, Any]) -> str | None:
    """What the person is being asked to do, in the words the Job Builder recorded.

    Assembled from §9's own columns rather than paraphrased. Nothing is invented: a field the
    author left empty is left out, and a step with nothing filled in gets no instructions at all
    rather than a sentence this code made up.
    """
    parts: list[tuple[str, str]] = []
    for label, key in (
        ("What to do", "what_exact_work"),
        ("How", "how_exact_method"),
        ("Input", "input_exact"),
        ("Where to find it", "input_found_where"),
        ("Where", "where_performed"),
        ("Rule or check", "rule_formula_check"),
        ("Expected output", "output"),
        ("Where it goes", "output_destination"),
        ("Approval", "approval"),
        ("If missing or wrong", "if_missing_or_wrong"),
    ):
        value = str(frozen.get(key) or "").strip()
        if value:
            parts.append((label, value))
    if not parts:
        return None
    return "\n".join(f"{label}: {value}" for label, value in parts)
