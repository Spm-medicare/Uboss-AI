"""Which event loop the process runs on.

One platform quirk, in one place, so that it cannot be worked around in a launch command and
then quietly break when the launch command changes.

Windows offers two event loops. psycopg's async driver cannot use the Proactor one and raises on
its first connection — surfacing as a 500 on whichever endpoint happens to touch the database
first, with a message about event loops that says nothing about the request. Uvicorn picks
Proactor on Windows unless it is running its reloader in a subprocess, which is why the fault
appears only when reload is switched off: exactly the configuration closest to production.

Setting the event-loop *policy* does not fix this, because uvicorn passes an explicit loop
factory to `asyncio.run` and the factory wins. So the factory is what this module supplies.

On Linux — every deployed environment — all of this is the standard selector loop and none of it
does anything.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Coroutine
from typing import Any


def loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """The loop this process should run on, or None to accept the default.

    Passed to `asyncio.run(..., loop_factory=...)` and to uvicorn's server, so the choice is
    made once and applies to the API, the migrations and any script.
    """
    if sys.platform == "win32":
        #  The selector loop caps out around 512 sockets. Far above anything a development
        #  machine reaches, and irrelevant to the Linux deployment.
        return asyncio.SelectorEventLoop
    return None


def configure_event_loop() -> None:
    """Set the policy as well, for code paths that create a loop without a factory.

    Belt and braces: `asyncio.run(...)` without `loop_factory` reads the policy, and some
    libraries still do that. Harmless where the factory is already correct.
    """
    if sys.platform != "win32":
        return
    if isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy):
        return
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """`asyncio.run` with the right loop for this platform, **returning what the coroutine
    returned**.

    Every entry point in the backend goes through this rather than calling `asyncio.run`
    directly, so none of them can be the one that forgets the loop factory.

    The return value is the point of the signature. An earlier version was annotated `-> None`
    and discarded the result, which is silent: a caller doing `value = run(fetch())` got `None`
    and no error, and the preflight script duly reported an empty database that was in fact at
    head. Typed generically so the type checker catches the next one.
    """
    configure_event_loop()
    return asyncio.run(coro, loop_factory=loop_factory())
