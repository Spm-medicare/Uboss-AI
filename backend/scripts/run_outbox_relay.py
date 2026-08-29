"""The outbox relay worker.

    uv run python -m scripts.run_outbox_relay
    uv run python -m scripts.run_outbox_relay --once     # one pass, for a cron or a check

Connects as `uboss_relay` — the only credential in the system that reads across every tenant, and
one whose reach is `SELECT` and `UPDATE` on `outbox_events` and nothing else.

**No publisher is registered yet, and that is visible rather than hidden.** Until an event type
has one, its events are dead-lettered with `no publisher is registered`, and this worker says so
on start-up. A relay that logged "delivered" for events nothing sent would be worse than no relay
at all.

Temporal takes this over in Gate 7. Until then it is a process, run under whatever supervises
processes here.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import socket
from datetime import timedelta

from sqlalchemy.ext.asyncio import create_async_engine

from uboss.core.logging import configure_logging, get_logger
from uboss.core.runtime import run as run_async
from uboss.core.settings import get_settings
from uboss.db.base import build_sessionmaker
from uboss.modules.audit import relay

log = get_logger(__name__)

#: How long to wait when there was nothing to do. Short enough that a notification is not
#: noticeably late, long enough that an idle relay is not a busy loop against the database.
IDLE_PAUSE = timedelta(seconds=5)


def _relay_url() -> str:
    url = os.environ.get("UBOSS_RELAY_DATABASE_URL")
    if not url:
        raise SystemExit(
            "Set UBOSS_RELAY_DATABASE_URL. The relay connects as uboss_relay, which can read "
            "and update outbox_events and nothing else. Running it as the application role "
            "would not work — that role sees only one tenant — and running it as the owner "
            "would give a queue worker the ability to alter the schema."
        )
    return url


def build_registry() -> relay.Registry:
    """Which event types can actually be delivered.

    Empty on purpose. Email delivery (needed by invite and password reset, step 1.2.6) waits on a
    provider and credentials the client has not supplied. Registering a placeholder that logged
    and returned would mark every event delivered and send nothing — the exact failure the outbox
    exists to make impossible.
    """
    registry = relay.Registry()
    return registry


async def main_async(once: bool) -> None:
    settings = get_settings()
    configure_logging(
        level=settings.log_level, json_output=settings.environment != "local"
    )

    registry = build_registry()
    worker = f"{socket.gethostname()}:{os.getpid()}"

    if not registry.registered:
        log.warning(
            "outbox_relay_has_no_publishers",
            detail=(
                "Every event will be dead-lettered as undeliverable. This is the honest state "
                "until a provider is configured — see step 1.2.6."
            ),
        )
    else:
        log.info("outbox_relay_started", worker=worker, publishes=registry.registered)

    engine = create_async_engine(_relay_url(), pool_size=2, max_overflow=2)
    factory = build_sessionmaker(engine)

    stopping = asyncio.Event()

    def request_stop(*_: object) -> None:
        #  Finish the current pass, then stop. Killing a relay mid-publish is safe — the lease
        #  expires and another worker retries — but finishing cleanly avoids the duplicate.
        log.info("outbox_relay_stopping", worker=worker)
        stopping.set()

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), request_stop)

    try:
        while not stopping.is_set():
            handled = await relay.run_once(factory, registry, worker=worker)
            if once:
                print(f"Handled {handled} event(s).")
                return
            if handled == 0:
                #  Waits on the stop signal rather than sleeping, so a shutdown is immediate instead
                #  of taking up to the idle pause. The timeout is the pause; reaching it just
                #  means nothing asked us to stop.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stopping.wait(), timeout=IDLE_PAUSE.total_seconds()
                    )
    finally:
        await engine.dispose()
        log.info("outbox_relay_stopped", worker=worker)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver what the outbox recorded.")
    parser.add_argument(
        "--once", action="store_true", help="One pass, then exit. For a cron or a check."
    )
    args = parser.parse_args()
    run_async(main_async(args.once))


if __name__ == "__main__":
    main()
