"""Request-level concerns that apply to every route.

Correlation, security headers and a request log. Deliberately small: middleware runs on every
request including health checks, so anything expensive here is expensive everywhere.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from uboss.core.logging import correlation_id, get_logger, new_correlation_id

log = get_logger(__name__)

#: The header a caller may use to continue an existing trace. Accepted, but never trusted as an
#: identifier for anything — it is a log key, not a credential.
CORRELATION_HEADER = "X-Correlation-Id"


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Give every request an id, and put it on the response.

    A caller-supplied id is honoured so a browser action and the API call it triggered share one
    id. It is length-capped and stripped of anything unusual, because it lands in log files that
    other tools parse.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get(CORRELATION_HEADER, "")
        cleaned = "".join(c for c in supplied if c.isalnum() or c in "-_")[:64]
        token = correlation_id.set(cleaned or new_correlation_id())
        try:
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id.get()
            return response
        finally:
            correlation_id.reset(token)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One line per request: what was asked, what came back, how long it took.

    The path is logged, the query string is not — query strings carry search terms, and a search
    term can be a person's name.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=elapsed_ms,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Headers that cost nothing and close whole classes of attack.

    This is an API, not a document server: it declares that nothing here should be framed,
    sniffed, or treated as a page.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Cache-Control", "no-store, no-cache, must-revalidate"
        )
        # An API response is never a document; nothing it returns should be able to load
        # anything, and nothing should be able to embed it.
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        return response
