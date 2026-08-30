"""Reaching Temporal — the client, and the one place its address is read.

Kept apart from `service.py` so the domain has no idea Temporal exists, and apart from
`worker.py` so the API can start a workflow without importing a worker.

**An unreachable Temporal is a supported state.** The same rule the product keeps for the model
gateway, object storage and mail: when the executor cannot be reached, `start_run` raises
`DependencyUnavailable` and the screen says the run could not be started — rather than recording a
run nobody will ever execute. A row that says `pending` for ever is worse than a refusal, because
it looks like work in progress.
"""

from __future__ import annotations

import uuid

from temporalio.client import Client
from temporalio.service import RPCError

from uboss.core.errors import DependencyUnavailable
from uboss.core.logging import correlation_id, get_logger
from uboss.core.settings import Settings
from uboss.modules.runtime.activities import RunRef

log = get_logger(__name__)

#: One queue for the runtime. Splitting queues is how you give different work different worker
#: pools, and there is one kind of work so far — a second name now would be a name to keep true.
TASK_QUEUE = "uboss-runtime"


async def connect(settings: Settings) -> Client:
    """A client, or a refusal that says which service is down.

    Not cached. The SDK's client is cheap to build and holds its own connection pool; a module
    level singleton would outlive the event loop it was created on, which on this codebase's
    Windows loop is the bug that takes an afternoon.
    """
    try:
        return await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
    except (RPCError, OSError, RuntimeError) as cause:
        log.warning("temporal_unreachable", error=type(cause).__name__)
        raise DependencyUnavailable(
            "The workflow service could not be reached, so the run was not started. "
            "Nothing has been changed."
        ) from cause


async def start_run(
    client: Client, *, tenant_id: uuid.UUID, run_id: uuid.UUID, workflow_id: str
) -> None:
    """Start the workflow for a run whose row already exists.

    **In this order, always.** The row is written and committed first; this starts the workflow
    against the id that row carries. A crash in between leaves a `pending` run — visible, and
    resolvable. The other order would leave a workflow that no row points at, which nothing can
    find and nobody can stop.

    Starting twice with the same id is refused by Temporal rather than duplicated, so a retried
    request cannot produce two executions of one run.
    """
    from uboss.modules.runtime.workflows import JobRunWorkflow

    try:
        await client.start_workflow(
            JobRunWorkflow.run,
            RunRef(
                tenant_id=str(tenant_id),
                run_id=str(run_id),
                correlation_id=correlation_id.get(),
            ),
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    except (RPCError, OSError, RuntimeError) as cause:
        log.warning("run_start_failed", run_id=str(run_id), error=type(cause).__name__)
        raise DependencyUnavailable(
            "The workflow service could not be reached, so the run was not started."
        ) from cause

    log.info("run_workflow_started", run_id=str(run_id), workflow_id=workflow_id)


async def signal_step_completed(client: Client, *, workflow_id: str) -> None:
    """Tell a waiting run that its human step is done.

    Sent after the task is recorded, never before: the signal carries nothing, so the workflow
    reads what happened from the database, and a signal that arrived first would find it unchanged.
    """
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("step_completed")


async def cancel_run(client: Client, *, workflow_id: str) -> None:
    """Stop a workflow. The row is already marked cancelled by the caller.

    A workflow that has already finished raises, and that is fine — the run's own state is the
    record, and this is the cleanup.
    """
    handle = client.get_workflow_handle(workflow_id)
    await handle.cancel()
