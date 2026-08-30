"""The only file in this repository that knows what Anthropic's API looks like.

Everything above it speaks `Task` and `Completion`. Swapping provider means writing a sibling of
this file and changing one line of policy — not touching a screen, a service or a migration.

**A tool call, not free text.** The task carries a JSON Schema and the model is required to
answer through a tool shaped like it. Parsing prose with a regular expression works until the
model writes a sentence first, and then it fails by producing a plausible wrong shape rather than
an error.

The HTTP client is `httpx` rather than the vendor SDK. One fewer dependency that can change under
the product, and the request is four fields — the SDK's value here would be the retry logic,
which is `httpx`'s anyway.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from uboss.core.logging import get_logger
from uboss.core.settings import Settings
from uboss.modules.ai_gateway.contract import Completion, ModelUnavailableError, Task

log = get_logger(__name__)

API_VERSION = "2023-06-01"

#: The tool the model answers through. Named for what it does, because the name is part of what
#: the model is being told.
TOOL_NAME = "record_answer"


async def complete(settings: Settings, task: Task, model: str) -> Completion:
    """Ask the model, and return a validated answer or raise.

    Raises `ModelUnavailableError` for anything that means "no answer": no key, a timeout, a
    refusal, a rate limit, or a reply that did not use the tool. The caller is expected to carry on
    without a model — never to surface this as a fault in the thing the person was doing.
    """
    key = settings.anthropic_api_key.get_secret_value().strip()
    if not key:
        raise ModelUnavailableError("No model is configured for this environment.")

    body: dict[str, Any] = {
        "model": model,
        "max_tokens": task.max_output_tokens or settings.ai_max_output_tokens,
        "system": task.instructions,
        "messages": [{"role": "user", "content": task.input}],
        "tools": [
            {
                "name": TOOL_NAME,
                "description": "Record the answer in the required shape.",
                "input_schema": task.schema,
            }
        ],
        #  Not "auto". The model must answer through the tool; left to choose, it sometimes
        #  explains instead, and an explanation is not something the caller can use.
        "tool_choice": {"type": "tool", "name": TOOL_NAME},
    }

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ai_base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as cause:
        #  The exception, not its message: a client error can carry the URL, and the URL carries
        #  the key in some configurations.
        log.warning("ai_request_failed", error=type(cause).__name__)
        raise ModelUnavailableError("The model did not answer in time.") from cause

    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code == 429:
        raise ModelUnavailableError("The model is rate limited right now. Try again shortly.")
    if response.status_code >= 400:
        log.warning("ai_request_rejected", status=response.status_code)
        raise ModelUnavailableError("The model refused the request.")

    payload = response.json()
    for block in payload.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
            usage = payload.get("usage", {})
            return Completion(
                content=_as_object(block.get("input")),
                model=payload.get("model", model),
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                latency_ms=latency_ms,
            )

    #  It answered, but not in a shape the caller can use. Treated as unavailable rather than as
    #  an error, because the outcome for the caller is identical: no proposal.
    log.warning("ai_answer_had_no_tool_use", stop_reason=payload.get("stop_reason"))
    raise ModelUnavailableError("The model did not return an answer in the expected form.")


def _as_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise ModelUnavailableError("The model's answer was not readable.") from None
        if isinstance(parsed, dict):
            return parsed
    raise ModelUnavailableError("The model's answer was not readable.")
