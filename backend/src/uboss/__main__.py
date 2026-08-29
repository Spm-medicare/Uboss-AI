"""Start the API.

    uv run python -m uboss --reload     # development
    uv run python -m uboss              # everything else

One entry point rather than a bare `uvicorn` command, because the server has to be told which
event loop to use and a launch command is the wrong place to keep that knowledge — see
`uboss.core.runtime`. It also means the host, port and reload flag have documented defaults
instead of living in whatever shell history started the process last.
"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn

from uboss.core.runtime import configure_event_loop, loop_factory


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the UBOSS API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--reload", action="store_true", help="Restart when a source file changes."
    )
    args = parser.parse_args()

    configure_event_loop()

    if args.reload:
        #  The reloader runs the server in a child process and chooses that process's loop
        #  itself, correctly. Handing it a factory here would have no effect on the child.
        uvicorn.run(
            "uboss.main:app",
            host=args.host,
            port=args.port,
            reload=True,
            log_config=None,
        )
        return

    #  `loop="none"` tells uvicorn not to create a loop, so this process supplies one that the
    #  database driver can actually use. Without it, uvicorn's own factory wins and every query
    #  fails on Windows.
    config = uvicorn.Config(
        "uboss.main:app",
        host=args.host,
        port=args.port,
        loop="none",
        # Structured logging is configured by the application; uvicorn's own format would
        # produce a second, differently-shaped stream in the same output.
        log_config=None,
        proxy_headers=False,
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=loop_factory())


if __name__ == "__main__":
    main()
