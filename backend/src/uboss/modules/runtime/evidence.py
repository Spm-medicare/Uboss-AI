"""What a run read, did, produced and who decided — assembled in one place.

Gate 7.6. Everything here already existed in some table; what did not exist was a way to ask for
all of it at once, in an order a person can read, with the gaps stated rather than left blank.

## Why it is one document and not six endpoints

Evidence is only evidence if it is complete. Six requests a reader has to make in the right order
and join by hand is a set of facts; one document with the run at the top, its steps beneath, and
what each step produced under it, is an account. The difference matters most for the reader this is
actually for — somebody asking, a year later, why a thing happened.

## What it contains, and against what

`PLAN.md` §17 names the runtime's tables: *"runs, run steps, tasks, approvals, schedules, outputs,
evidence, model calls and tool calls."* This gathers every one of them that has rows:

* **the run** — which published version, on whose instruction, when, and how it ended;
* **its steps** — state, attempts and the result each recorded;
* **what happened** — `run_events`, append-only, in order;
* **who decided** — the tasks, their outcome, note, who completed them, and the approvals with
  their reasons;
* **what it produced** — `run_outputs`, with the names the published version gave them;
* **what it asked a model** — `model_calls`, with tokens and latency, never prompt text.

## What it says is missing, rather than omitting

**Tool calls.** §17 names them and `integrations/` is empty — nothing external is wired until Gate
8. The bundle carries `tool_calls: []` alongside `tool_calls_available: false`, because an empty
list on its own reads as *"this run used no tools"* when the truth is *"this system cannot yet
record that"*. Those are different facts and the second one is the honest one today.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import NotFound
from uboss.core.permissions import Action
from uboss.modules.approvals.models import Approval
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.jobs.models import Job, JobVersion
from uboss.modules.runtime.models import ModelCall, Run, RunEvent, RunOutput, RunStep
from uboss.modules.tasks.models import Task, TaskComment, TaskEvidence


def _when(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def bundle(
    session: AsyncSession, context: SecurityContext, run_id: uuid.UUID
) -> dict[str, Any]:
    """Everything recorded about one run.

    `view`, not `audit`: this is the run's own record, and anybody who may see the run may see
    what it did. The audit trail — who read this evidence, and when — is a separate question that
    `audit.record` answers at the route.
    """
    await guard.authorise(session, context, Action.VIEW)

    run = (
        await session.execute(select(Run).where(Run.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        #  Not found and not permitted are the same answer. Row-level security has already made
        #  another organisation's runs invisible, so this is the truth as well as the safe reply.
        raise NotFound("No such run.")

    job = await session.get(Job, run.job_id)
    version = await session.get(JobVersion, run.job_version_id)

    steps = list(
        (
            await session.execute(
                select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position)
            )
        )
        .scalars()
        .all()
    )
    events = list(
        (
            await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run.id)
                .order_by(RunEvent.occurred_at, RunEvent.id)
            )
        )
        .scalars()
        .all()
    )
    outputs = list(
        (
            await session.execute(
                select(RunOutput)
                .where(RunOutput.run_id == run.id)
                .order_by(RunOutput.position)
            )
        )
        .scalars()
        .all()
    )
    calls = list(
        (
            await session.execute(
                select(ModelCall)
                .where(ModelCall.run_id == run.id)
                .order_by(ModelCall.occurred_at)
            )
        )
        .scalars()
        .all()
    )
    tasks = list(
        (
            await session.execute(
                select(Task).where(Task.run_id == run.id).order_by(Task.created_at)
            )
        )
        .scalars()
        .all()
    )

    task_ids = [task.id for task in tasks]
    comments = (
        list(
            (
                await session.execute(
                    select(TaskComment)
                    .where(TaskComment.task_id.in_(task_ids))
                    .order_by(TaskComment.created_at)
                )
            )
            .scalars()
            .all()
        )
        if task_ids
        else []
    )
    proofs = (
        list(
            (
                await session.execute(
                    select(TaskEvidence).where(TaskEvidence.task_id.in_(task_ids))
                )
            )
            .scalars()
            .all()
        )
        if task_ids
        else []
    )
    approvals = (
        list(
            (
                await session.execute(
                    select(Approval)
                    .where(Approval.task_id.in_(task_ids))
                    .order_by(Approval.created_at)
                )
            )
            .scalars()
            .all()
        )
        if task_ids
        else []
    )

    #  Every person named anywhere in the bundle, resolved once. A reader needs names; an id is
    #  evidence nobody can check without another system.
    wanted = {run.started_by_membership_id}
    wanted |= {task.assignee_membership_id for task in tasks}
    wanted |= {task.completed_by_membership_id for task in tasks}
    wanted |= {comment.membership_id for comment in comments}
    wanted |= {approval.decided_by_membership_id for approval in approvals}
    wanted |= {approval.requested_by_membership_id for approval in approvals}
    wanted |= {call.actor_membership_id for call in calls}
    known = [value for value in wanted if value is not None]
    names: dict[uuid.UUID, str] = {}
    if known:
        for member in (
            (await session.execute(select(Membership).where(Membership.id.in_(known))))
            .scalars()
            .all()
        ):
            names[member.id] = member.display_name

    def person(value: uuid.UUID | None) -> str | None:
        return names.get(value) if value is not None else None

    by_task: dict[uuid.UUID, list[Any]] = {}
    for comment in comments:
        by_task.setdefault(comment.task_id, []).append(comment)
    proofs_by_task: dict[uuid.UUID, list[Any]] = {}
    for proof in proofs:
        proofs_by_task.setdefault(proof.task_id, []).append(proof)

    return {
        "run": {
            "id": str(run.id),
            "state": run.state,
            "trigger": run.trigger,
            "job_id": str(run.job_id),
            "job_name": job.name if job is not None else None,
            "job_version_id": str(run.job_version_id),
            "job_version_no": version.version_no if version is not None else None,
            "started_by": person(run.started_by_membership_id),
            "started_at": _when(run.started_at),
            "finished_at": _when(run.finished_at),
            "failure_detail": run.failure_detail,
            "correlation_id": run.correlation_id,
        },
        "steps": [
            {
                "id": str(step.id),
                "position": step.position,
                "title": step.title,
                "mode": step.mode,
                "state": step.state,
                #: Attempts, so a retry is visible rather than smoothed over.
                "attempt": step.attempt,
                "started_at": _when(step.started_at),
                "finished_at": _when(step.finished_at),
                "result": step.result,
                "failure_detail": step.failure_detail,
            }
            for step in steps
        ],
        "events": [
            {
                "kind": event.kind,
                "detail": event.detail,
                "occurred_at": _when(event.occurred_at),
                "run_step_id": str(event.run_step_id) if event.run_step_id else None,
                "correlation_id": event.correlation_id,
            }
            for event in events
        ],
        "tasks": [
            {
                "id": str(task.id),
                "title": task.title,
                "state": task.state,
                "assignee": person(task.assignee_membership_id),
                "outcome": task.outcome,
                "outcome_note": task.outcome_note,
                "completed_by": person(task.completed_by_membership_id),
                "completed_at": _when(task.completed_at),
                "comments": [
                    {
                        "author": person(comment.membership_id),
                        "body": comment.body,
                        "written_at": _when(comment.created_at),
                    }
                    for comment in by_task.get(task.id, [])
                ],
                "evidence_file_ids": [
                    str(proof.file_id) for proof in proofs_by_task.get(task.id, [])
                ],
            }
            for task in tasks
        ],
        "approvals": [
            {
                "id": str(approval.id),
                "task_id": str(approval.task_id),
                "state": approval.state,
                "requested_by": person(approval.requested_by_membership_id),
                "decided_by": person(approval.decided_by_membership_id),
                #  The reason, always. §7's separation of duty is only meaningful if the decision
                #  says why, and a decision with no reason is a signature nobody can question.
                "reason": approval.reason,
                "decided_at": _when(approval.decided_at),
            }
            for approval in approvals
        ],
        "outputs": [
            {
                "position": output.position,
                "name": output.name,
                "destination": output.destination,
                "format": output.output_format,
                "value_text": output.value_text,
                "file_id": str(output.file_id) if output.file_id else None,
                "run_step_id": str(output.run_step_id) if output.run_step_id else None,
                "produced_at": _when(output.produced_at),
            }
            for output in outputs
        ],
        "model_calls": [
            {
                "task_kind": call.task_kind,
                "provider": call.provider,
                "model": call.model,
                "outcome": call.outcome,
                "detail": call.detail,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "latency_ms": call.latency_ms,
                "by": person(call.actor_membership_id),
                "occurred_at": _when(call.occurred_at),
                "run_step_id": str(call.run_step_id) if call.run_step_id else None,
            }
            for call in calls
        ],
        #  Named as unavailable rather than left empty. An empty list reads as "this run used no
        #  tools"; the truth is that nothing external is wired until Gate 8, and those are
        #  different facts. See `integrations/`, which is an empty package on purpose.
        "tool_calls": [],
        "tool_calls_available": False,
    }
