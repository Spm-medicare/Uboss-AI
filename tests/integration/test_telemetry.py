"""Telemetry — 1.6.2.

Exit check: **one browser action can be followed end to end by its correlation id, and no span
carries a secret.**

The second half is the one that needs a test. A span attribute is a log line with a longer life —
it reaches a collector, a vendor, and a dashboard other people can read. Nothing stops somebody
adding `request.body` to a span except a check that fails when they do.

These use an in-memory exporter, so they assert on the spans that were actually produced rather
than on the code that produces them.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from uboss.core import telemetry
from uboss.core.logging import actor_id, correlation_id, tenant_id
from uboss.core.settings import Settings


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """A provider that keeps its spans, so they can be read back.

    The global provider is replaced for the test and the original restored afterwards —
    OpenTelemetry's provider is process-wide, and leaving a test one installed would make every
    later test's telemetry go somewhere unexpected.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    original = trace.get_tracer_provider()
    trace._TRACER_PROVIDER = provider
    try:
        yield exporter
    finally:
        trace._TRACER_PROVIDER = original


def test_a_span_carries_the_correlation_id(spans: InMemorySpanExporter) -> None:
    """The same id as every log line, so a trace and a log join on it."""
    token = correlation_id.set("abc123correlation")
    try:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("a-request") as span:
            telemetry.enrich_span(span)
    finally:
        correlation_id.reset(token)

    finished = spans.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].attributes is not None
    assert finished[0].attributes["uboss.correlation_id"] == "abc123correlation"


def test_a_span_carries_the_tenant_and_actor(spans: InMemorySpanExporter) -> None:
    tokens = (
        correlation_id.set("c"),
        tenant_id.set("11111111-1111-1111-1111-111111111111"),
        actor_id.set("22222222-2222-2222-2222-222222222222"),
    )
    try:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("a-request") as span:
            telemetry.enrich_span(span)
    finally:
        correlation_id.reset(tokens[0])
        tenant_id.reset(tokens[1])
        actor_id.reset(tokens[2])

    attributes = spans.get_finished_spans()[0].attributes
    assert attributes is not None
    assert attributes["uboss.tenant_id"] == "11111111-1111-1111-1111-111111111111"
    assert attributes["uboss.membership_id"] == "22222222-2222-2222-2222-222222222222"


def test_an_absent_value_is_not_set_at_all(spans: InMemorySpanExporter) -> None:
    """"Not signed in" and "signed in as nobody" are different facts.

    Setting an empty string would make an anonymous request look like one with a blank actor.
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("anonymous") as span:
        telemetry.enrich_span(span)

    attributes = spans.get_finished_spans()[0].attributes
    assert attributes is not None
    assert "uboss.membership_id" not in attributes
    assert "uboss.tenant_id" not in attributes


def test_no_span_attribute_is_ever_a_secret(spans: InMemorySpanExporter) -> None:
    """The half of the exit check that needs guarding, not just asserting.

    A span reaches a collector, a vendor and a shared dashboard. Nothing prevents somebody adding
    a request body or an authorization header to one except this failing when they do.
    """
    token = correlation_id.set("c")
    try:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("a-request") as span:
            telemetry.enrich_span(span)
    finally:
        correlation_id.reset(token)

    attributes = spans.get_finished_spans()[0].attributes or {}
    forbidden = {
        "password",
        "token",
        "secret",
        "cookie",
        "authorization",
        "api_key",
        "email",
        "hash",
    }
    for name, value in attributes.items():
        lowered = name.lower()
        assert not any(word in lowered for word in forbidden), (
            f"span attribute {name!r} looks like a secret"
        )
        assert "@" not in str(value), (
            f"span attribute {name!r} contains what looks like an email address"
        )


def test_the_never_recorded_list_covers_the_headers_that_matter() -> None:
    """A written list, so it stays true if the instrumentation's defaults ever change."""
    for header in ("authorization", "cookie", "set-cookie", "idempotency-key"):
        assert header in telemetry.NEVER_RECORDED


def test_health_probes_are_not_traced() -> None:
    """A readiness probe runs every few seconds and tells nobody anything about a request.

    Left in, it dominates every trace view and the interesting spans become unfindable.
    """
    assert "/health/ready" in telemetry.NOT_TRACED
    assert "/health/live" in telemetry.NOT_TRACED


def test_telemetry_starts_without_a_collector() -> None:
    """No endpoint is a supported state, not a failure.

    A product that needs a telemetry backend in order to start is a product nobody can run on a
    laptop — and the code path that runs locally stops being the one that runs in production.
    """
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://x:x@localhost:5432/x",  # type: ignore[arg-type]
        auth_signing_key="test",  # type: ignore[arg-type]
        otlp_endpoint="",
    )
    telemetry.configure(settings)
    #  Spans are still created — they are simply dropped. That keeps every call site honest.
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("still-works"):
        telemetry.enrich_span()
