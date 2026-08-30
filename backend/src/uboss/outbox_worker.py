"""The process that actually delivers what the outbox recorded.

    uv run python -m uboss.outbox_worker

Separate from the API process on purpose. Delivery is slow, retried and occasionally blocked on
somebody else's mail server; putting it in a request handler would mean a person waiting on the
sign-in screen for a provider that is having a bad afternoon. It also means delivery keeps
running while the API is being deployed, and the API keeps serving while this is.

**Idle is a poll, not a queue.** One `LISTEN`-based design was considered and rejected: the
outbox is already polled for due retries, so a notification channel would only shorten the first
attempt's latency and would add a second way for an event to be missed. Two seconds is
imperceptible on a password reset.

**One worker or ten, it does not matter.** `claim` takes its rows with `FOR UPDATE SKIP LOCKED`,
so workers never wait on each other and never take the same row.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import socket

from uboss.core.logging import configure_logging, get_logger
from uboss.core.runtime import configure_event_loop, loop_factory
from uboss.core.settings import get_settings
from uboss.db.base import build_engine, build_sessionmaker
from uboss.modules.audit import relay
from uboss.modules.notifications import publishers

log = get_logger(__name__)

#: How long to wait after finding nothing. Short enough that a reset link arrives while the
#: person is still looking at the screen that told them to expect it.
IDLE_SECONDS = 2.0

#: How long to wait after an error at the *database*, as opposed to at a provider. Longer,
#: because retrying a broken connection ten times a second helps nobody and fills the log.
ERROR_SECONDS = 10.0


async def run(*, worker: str, once: bool = False) -> int:
    """Deliver until stopped. Returns how many events were claimed in total."""
    settings = get_settings()
    engine = build_engine(settings)
    factory = build_sessionmaker(engine)
    registry = publishers.build(settings)

    if not settings.mail_is_configured:
        #  Started anyway. The relay will attempt each event, `mail.send` will raise, and the
        #  row will carry the reason — which is a far better diagnostic than a worker that
        #  refuses to start and leaves the queue looking healthy.
        log.warning("outbox_worker_mail_unconfigured", registered=registry.registered)

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            #  Windows has no signal handler support on the proactor loop; there the
            #  KeyboardInterrupt path below is what stops it.
            loop.add_signal_handler(sig, stopping.set)

    log.info("outbox_worker_started", worker=worker, registered=registry.registered)
    total = 0
    try:
        while not stopping.is_set():
            try:
                claimed = await relay.run_once(factory, registry, worker=worker)
            except Exception as exc:
                #  A failure *here* is the database or the claim query, not a provider — a
                #  provider failure is caught inside `run_once` and recorded against the row.
                log.error("outbox_worker_pass_failed", error=f"{type(exc).__name__}: {exc}")
                claimed = 0
                delay: float = ERROR_SECONDS
            else:
                total += claimed
                #  A full batch means there is probably more waiting, so go straight round again.
                delay = 0.0 if claimed >= relay.BATCH else IDLE_SECONDS

            if once:
                break
            if delay:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stopping.wait(), timeout=delay)
    finally:
        await engine.dispose()
        log.info("outbox_worker_stopped", worker=worker, claimed=total)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver UBOSS outbox events.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Do a single pass and exit. Used by tests and by a manual flush.",
    )
    parser.add_argument(
        "--worker",
        default=None,
        help="Name recorded on the lease. Defaults to the hostname and process id.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(
        level=settings.log_level, json_output=settings.environment != "local"
    )
    configure_event_loop()

    #  Hostname *and* pid: two workers on one machine must not share a lease name, or the
    #  `leased_by` column stops telling an operator which process is holding a row.
    worker = args.worker or f"{socket.gethostname()}:{os.getpid()}"

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(worker=worker, once=args.once), loop_factory=loop_factory())


if __name__ == "__main__":
    main()
