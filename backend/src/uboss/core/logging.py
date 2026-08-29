"""Structured logging.

Every line is a JSON object with the same shape, so a production log is queryable rather than
grep-able. Three rules hold everywhere:

* **A log line carries the correlation id.** One request, one id, threaded through the API, the
  workflow and the outbox, so a person can follow a single piece of work end to end.
* **A log line never carries a secret.** No token, no password hash, no API key, no request body
  from a form that might hold personal data.
* **A log line is not an audit record.** Logs are for operators and may be dropped or sampled.
  Anything that must survive for governance is written to the audit table inside the same
  transaction as the change it describes.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import structlog

#: Set once per request by the correlation middleware and read by every log line after it.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

#: Set once the caller is identified. Absent on anonymous requests, which is itself information.
actor_id: ContextVar[str] = ContextVar("actor_id", default="")
tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")


def new_correlation_id() -> str:
    return uuid4().hex


def _add_context(
    _logger: object, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Attach the request's identity to every line without the caller passing it."""
    for key, var in (
        ("correlation_id", correlation_id),
        ("actor_id", actor_id),
        ("tenant_id", tenant_id),
    ):
        value = var.get()
        if value:
            event[key] = value
    return event


def configure_logging(level: str = "info", json_output: bool = True) -> None:
    """Install the logging configuration. Called once, at start-up.

    On a laptop the console renderer is easier to read; everywhere else the output is JSON so a
    collector can parse it. The difference is presentation only -- the fields are identical.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
