"""The provider-neutral shape of a model call.

PLAN §18: *"Claude through an internal provider-neutral AI Gateway."* This module is that
contract. Nothing outside `ai_gateway/` imports a provider's SDK, mentions a provider's model
name, or knows what a "system prompt" is — domain code asks for a `Task` and gets a `Completion`.

Two rules hold the boundary:

**A model name never appears in domain logic or in the interface.** It comes from policy, which
reads settings. A screen that hard-codes `claude-…` is a screen that has to be found and edited
the next time the model changes, and it will be missed.

**No model reachable is a supported state, not a failure.** `ModelUnavailable` is raised, the
caller falls back to what it can do deterministically, and the interface says plainly that no
model was consulted. Quietly returning a made-up answer is the one thing this module must never
do.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from uboss.core.errors import UbossError


class TaskKind(enum.StrEnum):
    """What the model is being asked for.

    Policy maps this to a model, so the choice is made once, by name, in one place. A caller says
    what it needs done; it does not get to say which model does it.
    """

    #: Small, structured, low-stakes: match spreadsheet headers to known fields. The answer is
    #: reviewed by a person before anything happens, which is why a fast model is appropriate.
    COLUMN_MAPPING = "column_mapping"
    #: Drafting an objective from a description — Gate 3. Reasoning-heavy and reviewed.
    OBJECTIVE_PROPOSAL = "objective_proposal"


class ModelUnavailableError(UbossError):
    """No model could be reached, or none is configured.

    Deliberately its own error rather than a generic failure: the caller is expected to carry on
    without one, and the interface is expected to say so. A 500 here would turn "we did not ask a
    model" into "the import is broken".
    """

    code = "model_unavailable"
    status_code = 503

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class Task:
    """One request to a model, in the product's own terms."""

    kind: TaskKind
    #: What the model is for, and what it must not do. Sent as the system prompt by the adapter.
    instructions: str
    #: The material to reason about. Never contains anything from another tenant — the caller
    #: builds it from rows it has already read under the tenant's own policy.
    input: str
    #: The JSON Schema the answer must satisfy. Required: a free-text answer would have to be
    #: parsed with a regular expression, and the failure mode is a plausible wrong shape.
    schema: dict[str, Any]
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Completion:
    """What came back, and what it cost.

    `model` is recorded rather than assumed so an audit answers "which model produced this",
    including after policy changes. The proposal stored on an import carries it for the same
    reason.
    """

    content: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    #: Milliseconds. Recorded because a slow model is a product problem before it is a bill.
    latency_ms: int
    warnings: list[str] = field(default_factory=list)
