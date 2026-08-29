"""Liveness and readiness.

The two answer different questions, and conflating them is how a deployment routes traffic at a
process that cannot serve it:

* **Live** — this process is running and its event loop is responsive. If this fails, restart it.
* **Ready** — every dependency this process needs is answering *right now*. If this fails, stop
  sending it traffic; do not restart it, because the fault is elsewhere.

Readiness runs a real query. A hard-coded `{"status": "ok"}` is worse than no check at all: it
reports health it never measured, and the orchestrator believes it.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text

from uboss.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["health"])

#: A dependency that has not answered in this long is treated as down. Long enough to survive a
#: slow query, short enough that a probe does not hang behind a dead connection.
PROBE_TIMEOUT_SECONDS = 3.0


class DependencyStatus(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class Readiness(BaseModel):
    status: Literal["ready", "degraded"]
    dependencies: list[DependencyStatus]


@router.get("/health/live", summary="Is this process alive?")
async def live() -> dict[str, str]:
    """Answers only for itself. It touches nothing, so a database outage cannot cause a restart
    loop of a perfectly healthy API."""
    return {"status": "alive"}


async def _check_database(request: Request) -> DependencyStatus:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            factory = request.app.state.sessionmaker
            async with factory() as session:
                await session.execute(text("SELECT 1"))
        return DependencyStatus(name="database", ok=True)
    except TimeoutError:
        return DependencyStatus(
            name="database", ok=False, detail="did not answer within the probe timeout"
        )
    except Exception as exc:
        return DependencyStatus(name="database", ok=False, detail=type(exc).__name__)


async def _check_redis(request: Request) -> DependencyStatus:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            client: Redis = request.app.state.redis
            await client.ping()
        return DependencyStatus(name="redis", ok=True)
    except TimeoutError:
        return DependencyStatus(
            name="redis", ok=False, detail="did not answer within the probe timeout"
        )
    except RedisError as exc:
        return DependencyStatus(name="redis", ok=False, detail=type(exc).__name__)


@router.get(
    "/health/ready",
    summary="Can this process serve traffic?",
    response_model=Readiness,
)
async def ready(request: Request, response: Response) -> Readiness:
    """Reports what was actually measured, and returns 503 when anything is down.

    The status code matters as much as the body: an orchestrator reads the code, and a 200 with
    `"degraded"` inside would keep traffic flowing to a process that cannot serve it.
    """
    checks = list(
        await asyncio.gather(
            _check_database(request),
            _check_redis(request),
        )
    )
    healthy = all(check.ok for check in checks)
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        log.warning(
            "not_ready",
            failing=[check.name for check in checks if not check.ok],
        )
    return Readiness(status="ready" if healthy else "degraded", dependencies=checks)
