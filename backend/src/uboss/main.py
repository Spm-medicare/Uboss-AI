"""The FastAPI application.

Built by a factory rather than created at import time, so configuration is read once, explicitly,
and a second app can exist in the same process without sharing an engine.

Start-up opens the connection pool. It deliberately does **not** verify the database: a process
that refuses to start when Postgres is briefly unavailable turns a ten-second blip into a failed
deployment. Readiness reports the truth instead, and the orchestrator withholds traffic until the
database answers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from starlette.middleware.trustedhost import TrustedHostMiddleware

from uboss.api.health import router as health_router
from uboss.api.router import build_v1_router
from uboss.core import telemetry
from uboss.core.errors import install_error_handlers
from uboss.core.logging import configure_logging, get_logger
from uboss.core.middleware import (
    AccessLogMiddleware,
    CorrelationMiddleware,
    SecurityHeadersMiddleware,
)
from uboss.core.runtime import configure_event_loop
from uboss.core.settings import Settings, get_settings
from uboss.db.base import build_engine, build_sessionmaker

log = get_logger(__name__)


def _lifespan(settings: Settings):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = build_sessionmaker(engine)
        redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        app.state.redis = redis
        app.state.settings = settings
        #  Instrumented here rather than in `create_app`, because the engine only exists now.
        telemetry.instrument(app, engine)
        log.info(
            "api_start",
            environment=settings.environment,
            ai_configured=settings.ai_is_configured,
        )
        try:
            yield
        finally:
            # Close the pool on the way out so a reload does not leave connections held open
            # against a server with a finite limit.
            await engine.dispose()
            await redis.aclose()
            log.info("api_stop")

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    #  Before anything creates an event loop. On Windows the default one cannot be used by the
    #  database driver; on Linux this does nothing.
    configure_event_loop()

    settings = settings or get_settings()
    telemetry.configure(settings)
    configure_logging(
        level=settings.log_level,
        json_output=settings.environment != "local",
    )

    app = FastAPI(
        title="UBOSS AI",
        version="0.1.0",
        summary="Governed human and AI work operating system",
        lifespan=_lifespan(settings),
        # The interactive docs are a development convenience. In production they are one more
        # unauthenticated surface describing every route, so they are switched off there.
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
    )

    #  Middleware runs outermost-first, and the order below is deliberate: a request gets its
    #  correlation id before anything can log, and security headers are applied to whatever the
    #  inner layers produced, including error responses.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        #  Every header the browser client actually sends. `If-Match` was missing, and the
        #  consequence was not subtle: it carries `expected_version`, so a browser preflight
        #  refused **every optimistic-concurrency write in the product** — saving an agent, a job,
        #  an objective, renaming a department. Creates worked, because they carry no version, so
        #  the fault looked like "editing is broken" rather than like a CORS list.
        #
        #  Kept as an explicit list rather than a wildcard: a wildcard with `allow_credentials`
        #  is rejected by browsers anyway, and an explicit list is a place this can be reviewed.
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "X-Correlation-Id",
        ],
        expose_headers=["X-Correlation-Id"],
    )
    #  A wildcard origin with credentials is rejected by browsers anyway, but an explicit list
    #  also keeps a misconfigured staging origin from reaching production data.

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list
    )
    #  The Host header never selects a tenant here — the token does — but refusing unknown hosts
    #  still closes off cache-poisoning and absolute-URL forgery.

    install_error_handlers(app)

    app.include_router(health_router)
    app.include_router(build_v1_router(), prefix=settings.api_prefix)

    return app


app = create_app()
