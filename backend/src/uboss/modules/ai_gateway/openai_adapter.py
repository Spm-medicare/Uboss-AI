"""The only file in this repository that knows what OpenAI's API looks like.

A sibling of `anthropic_adapter`, written to prove the contract is real: the gateway swaps
provider by changing one line of policy, and nothing above it — no service, no screen, no
migration — knows which one answered. That claim was untested while there was one adapter.

**A tool call, not free text**, for the same reason as its sibling: the task carries a JSON Schema
and the model must answer through a function shaped like it. `strict: true` makes OpenAI enforce
the schema rather than merely suggest it, which is the difference between a validated answer and
a plausible wrong shape.

The differences from Anthropic's shape are all in this file, and they are worth naming because
each one is a place a naive port breaks:

* the system prompt is a message with `role: "system"`, not a top-level field;
* the tool is wrapped in `{"type": "function", "function": {...}}` and the schema key is
  `parameters`, not `input_schema`;
* forcing the call needs the same nested shape again under `tool_choice`;
* the arguments come back as a **JSON string**, never an object — `_as_object` handles both,
  which is why it is shared rather than copied.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from uboss.core.logging import get_logger
from uboss.core.settings import Settings
from uboss.modules.ai_gateway.anthropic_adapter import TOOL_NAME, _as_object
from uboss.modules.ai_gateway.contract import Completion, ModelUnavailableError, Task

log = get_logger(__name__)


async def complete(settings: Settings, task: Task, model: str) -> Completion:
    """Ask the model, and return a validated answer or raise.

    Raises `ModelUnavailableError` for anything that means "no answer": no key, a timeout, a
    refusal, a rate limit, or a reply that did not use the tool. Identical contract to the
    Anthropic adapter, because the caller must not be able to tell them apart.
    """
    key = settings.openai_api_key.get_secret_value().strip()
    if not key:
        raise ModelUnavailableError("No model is configured for this environment.")

    body: dict[str, Any] = {
        "model": model,
        "max_completion_tokens": task.max_output_tokens or settings.ai_max_output_tokens,
        "messages": [
            {"role": "system", "content": task.instructions},
            {"role": "user", "content": task.input},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": TOOL_NAME,
                    "description": "Record the answer in the required shape.",
                    "parameters": task.schema,
                    #  Enforced, not suggested. Without this the schema is a hint and the model
                    #  is free to return a differently-shaped object that parses and is wrong.
                    "strict": True,
                },
            }
        ],
        #  Not "auto". Left to choose, the model sometimes explains instead, and an explanation
        #  is not something the caller can use.
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/v1/chat/completions",
                headers={
                    "authorization": f"Bearer {key}",
                    "content-type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as cause:
        #  The exception type, not its message: a client error can carry the URL, and a URL can
        #  carry the key in some configurations.
        log.warning("ai_request_failed", provider="openai", error=type(cause).__name__)
        raise ModelUnavailableError("The model did not answer in time.") from cause

    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code == 429:
        #  OpenAI returns 429 for two different situations and only one of them is temporary.
        #  "Try again shortly" on an exhausted balance is advice that will never come true, and
        #  it sends an operator looking for a traffic spike instead of a billing page.
        if _is_out_of_credit(response):
            log.warning("ai_quota_exhausted", provider="openai")
            raise ModelUnavailableError(
                "This deployment's model account has no credit left, so no model is reachable "
                "until it is topped up."
            )
        raise ModelUnavailableError("The model is rate limited right now. Try again shortly.")
    if response.status_code >= 400:
        log.warning("ai_request_rejected", provider="openai", status=response.status_code)
        raise ModelUnavailableError("The model refused the request.")

    payload = response.json()
    for choice in payload.get("choices", []):
        for call in choice.get("message", {}).get("tool_calls") or []:
            if call.get("function", {}).get("name") != TOOL_NAME:
                continue
            usage = payload.get("usage", {})
            return Completion(
                #  A JSON *string* here, where Anthropic sends an object. `_as_object` accepts
                #  both, which is why it is imported rather than re-implemented — two copies of
                #  a parser is two places for the error handling to drift.
                content=_as_object(call.get("function", {}).get("arguments")),
                model=payload.get("model", model),
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                latency_ms=latency_ms,
            )

    #  It answered, but not in a shape the caller can use. Treated as unavailable rather than as
    #  an error, because the outcome for the caller is identical: no proposal.
    log.warning(
        "ai_answer_had_no_tool_use",
        provider="openai",
        finish_reason=(payload.get("choices") or [{}])[0].get("finish_reason"),
    )
    raise ModelUnavailableError("The model did not return an answer in the expected form.")


def _is_out_of_credit(response: httpx.Response) -> bool:
    """Whether a 429 means "no balance" rather than "too fast".

    Reads the error *code*, not the message: the message is prose that changes, the code is part
    of the API. Anything unreadable falls through to the temporary reading, which is the safer
    default — advising a retry that will not help is better than telling somebody to pay a bill
    they do not owe.
    """
    try:
        error = response.json().get("error", {})
    except ValueError:
        return False
    return error.get("type") == "insufficient_quota" or error.get("code") in {
        "insufficient_quota",
        "credit_balance_exhausted",
    }
