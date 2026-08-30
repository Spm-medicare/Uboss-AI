"""The process that actually runs runs.

    uv run python -m uboss.runtime_worker

Separate from the API for the same reason the outbox relay is: execution is slow, retried and
occasionally waiting a fortnight on a person. Putting it in a request handler would mean an HTTP
connection held open for a Job; putting it in the API process would mean a deploy interrupting
every run in flight.

**Killing this process is safe, and that is the deliverable.** Gate 7's exit criteria name it:
*"crash/retry/idempotency/outbox recovery tests pass."* Temporal holds the run's state on the
server, so a worker that dies mid-step is replaced and the workflow resumes from its history — and
every activity is written to survive being asked to do its work a second time.

Run several. Temporal distributes tasks across whichever workers are polling the queue; they need
no knowledge of each other.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import socket

from temporalio.worker import Worker

from uboss.core.logging import configure_logging, get_logger
from uboss.core.runtime import configure_event_loop, loop_factory
from uboss.core.settings import get_settings
from uboss.db.base import build_engine, build_sessionmaker
from uboss.db.registry import import_all
from uboss.modules.runtime.activities import RunActivities
from uboss.modules.runtime.temporal import TASK_QUEUE, connect
from uboss.modules.runtime.workflows import JobRunWorkflow

log = get_logger(__name__)


async def run(*, identity: str) -> None:
    """Poll the queue until stopped."""
    #  Every model, not only the runtime's. A mapper resolves its foreign keys against the
    #  metadata it can see, so a worker that imported `runs` alone fails on `runs.tenant_id`
    #  pointing at a `tenants` table nothing had registered. The API gets this for free by
    #  importing its routers; a worker has to ask.
    import_all()

    settings = get_settings()
    engine = build_engine(settings)
    factory = build_sessionmaker(engine)

    client = await connect(settings)
    activities = RunActivities(factory)

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            #  Windows' proactor loop has no signal handlers; there the KeyboardInterrupt path in
            #  `main` is what stops it.
            loop.add_signal_handler(sig, stopping.set)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        identity=identity,
        workflows=[JobRunWorkflow],
        activities=[
            activities.mark_running,
            activities.next_step,
            activities.begin_step,
            activities.wait_for_person,
            activities.perform,
            activities.fail_step,
            activities.finish,
            activities.fail,
        ],
    )

    log.info("runtime_worker_started", identity=identity, queue=TASK_QUEUE)
    try:
        #  `run_until` rather than `run`: the worker finishes what it is holding and stops
        #  polling, so a deploy does not abandon an activity halfway.
        async with worker:
            await stopping.wait()
    finally:
        await engine.dispose()
        log.info("runtime_worker_stopped", identity=identity)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run UBOSS workflow executions.")
    parser.add_argument(
        "--identity",
        default=None,
        help="Name this worker reports to Temporal. Defaults to the hostname and process id.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.environment != "local")
    configure_event_loop()

    #  Hostname *and* pid, so two workers on one machine are distinguishable in Temporal's UI —
    #  which is where somebody looks when a run is stuck.
    identity = args.identity or f"{socket.gethostname()}:{os.getpid()}"

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(identity=identity), loop_factory=loop_factory())


if __name__ == "__main__":
    main()
