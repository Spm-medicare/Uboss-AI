"""Traces and metrics, correlated with the logs that already exist.

PLAN §26: "OpenTelemetry-compatible traces, metrics and structured logs." PLAN Step 1.6 asks for
them to correlate "across Web, API, DB, worker, model and tool calls".

The correlation id has been threaded through every log line since the first commit. This makes it
the same id in a trace, so one browser action can be followed end to end — through the API, into
the database, out to whatever it called — hours later, in a different process.

**Nothing here may carry a secret.** A span attribute is a log line with a longer life: it goes
to a collector, a vendor, and a dashboard other people can read. So the request path is recorded
and the query string is not, the route is recorded and the body is not, and there is an explicit
list of headers that never appear.

**It is off unless an endpoint is configured.** No collector means no exporter, and the
instrumentation costs nothing measurable. A product that requires a telemetry backend in order to
start is a product that cannot be run on a laptop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, TraceIdRatioBased
from opentelemetry.trace import Span

from uboss.core.logging import actor_id, correlation_id, get_logger, tenant_id
from uboss.core.settings import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine

log = get_logger(__name__)

#: Never recorded on a span, whatever the instrumentation would otherwise capture. The library's
#: default is not to capture headers at all; this is the list that must stay true if that ever
#: changes, and the reason it is written down rather than assumed.
NEVER_RECORDED: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "idempotency-key",
        "proxy-authorization",
    }
)

#: Paths that would otherwise dominate every trace view. A readiness probe runs every few seconds
#: and tells nobody anything about a person's request.
NOT_TRACED: tuple[str, ...] = ("/health/live", "/health/ready", "/openapi.json", "/docs")


def configure(settings: Settings) -> None:
    """Set up tracing, if a collector is configured.

    Called once, while the application is being built. Without an endpoint this installs a
    provider that records nothing — so `enrich_span` and the instrumentation below are safe to
    call unconditionally and cost nothing.
    """
    resource = Resource.create(
        {
            "service.name": "uboss-api",
            "service.version": "0.1.0",
            "deployment.environment": settings.environment,
        }
    )

    #  Sampled at 100% outside production. A developer chasing one request needs that request,
    #  and the volume is a handful per minute. Production samples down, because a trace per
    #  request at scale costs more than it is worth and the interesting ones are errors, which
    #  are kept regardless by the collector's tail sampling.
    sampler = (
        TraceIdRatioBased(settings.trace_sample_ratio)
        if settings.environment == "production"
        else ALWAYS_ON
    )

    provider = TracerProvider(resource=resource, sampler=sampler)

    if settings.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
        )
        log.info("telemetry_exporting", endpoint=settings.otlp_endpoint)
    else:
        #  No exporter. Spans are created and dropped, which keeps every call site honest — the
        #  code path that runs on a laptop is the one that runs in production.
        log.info(
            "telemetry_not_exporting",
            detail="No UBOSS_OTLP_ENDPOINT is set, so spans are created and discarded.",
        )

    trace.set_tracer_provider(provider)


def instrument(app: FastAPI, engine: AsyncEngine) -> None:
    """Attach the instrumentation that covers where time is actually spent.

    Three: the API, the database, and outbound calls. Adding more before there is a question
    they answer just makes every trace harder to read.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=",".join(NOT_TRACED),
        #  Runs on every request, on the span the instrumentation just created. This is where
        #  the correlation id, tenant and actor reach the trace.
        server_request_hook=_on_request,
    )
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    HTTPXClientInstrumentor().instrument()


def _on_request(span: Span, _scope: dict[str, Any]) -> None:
    enrich_span(span)


def enrich_span(span: Span | None = None) -> None:
    """Put this request's identity on the current span.

    The same three values that are on every log line, so a trace and a log can be joined by any
    of them. Absent values are not set rather than being set to an empty string — "not signed in"
    and "signed in as nobody" are different facts.
    """
    target = span or trace.get_current_span()
    if not target.is_recording():
        return

    if value := correlation_id.get():
        target.set_attribute("uboss.correlation_id", value)
    if value := tenant_id.get():
        #  The tenant's id, never its name. An id is meaningless to anyone without database
        #  access; a customer's name in a shared dashboard is a disclosure.
        target.set_attribute("uboss.tenant_id", value)
    if value := actor_id.get():
        target.set_attribute("uboss.membership_id", value)


def shutdown() -> None:
    """Flush anything still buffered.

    A batch processor holds spans for a few seconds. Without this, the last few seconds before a
    deployment are missing from the trace of the thing that went wrong during it.
    """
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()
