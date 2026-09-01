"""Two routes: ask the Copilot something, and search the workspace.

## Why asking is a POST with no idempotency key

Every other `POST /v1` route in this codebase takes an `Idempotency-Key`, because every other one
writes something a retry could duplicate. This one writes an audit row and nothing else, and the
row is the point: *"somebody asked this at this time"* is a fact about each attempt, not a state a
retry should collapse. Two identical questions ten seconds apart are two questions.

It is a POST rather than a GET because a question is a person's own words. A GET puts them in the
URL, and a URL is in the access log, the proxy log, the browser history and the referrer.

## Why searching is a GET

The search box is the opposite: short, repeated, cacheable, and its terms are already going to a
list endpoint's query string everywhere else in the product. `PLAN.md` §85 puts it in the top bar,
and the work breakdown records that it has shown an honest *"unavailable"* state since Gate 1
precisely so it could be built here rather than faked earlier.

Both routes gate on `view`. The Copilot reads; the whole of `policy.py` is about what it does not
do.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from uboss.core.dependencies import CurrentContext, SessionDep, SettingsDep
from uboss.core.permissions import Action
from uboss.modules.copilot import preview, retrieval, service
from uboss.modules.identity import guard

router = APIRouter(prefix="/copilot", tags=["copilot"])


class Ask(BaseModel):
    """A question about this workspace."""

    model_config = ConfigDict(extra="forbid")

    #: Bounded because a prompt is a cost and a paragraph is not a question. The limit is generous
    #: enough for somebody who pastes a sentence from an email.
    question: str = Field(min_length=1, max_length=2000)


class SourceRead(BaseModel):
    """One object the answer stands on, and where to go and check it.

    `UI_SPEC.md` §18: *"Shows sources/object references when using company data."* The text is
    included so the panel can show the reader the same words the model was given.
    """

    kind: str
    id: uuid.UUID
    label: str
    text: str
    href: str


class ChangeRead(BaseModel):
    field: str
    label: str
    current: str
    proposed: str


class PreviewRead(BaseModel):
    """A change the person could make, as a difference. Never applied by this API.

    There is no matching `POST /copilot/apply`, and that absence is the design — see `preview.py`.
    The person opens `href` and saves it through the object's own route.
    """

    kind: str
    id: uuid.UUID
    label: str
    href: str
    changes: list[ChangeRead]
    refused: str | None = None


class AnswerRead(BaseModel):
    """What the Copilot said, and everything needed to judge it.

    `proposal` is always true and is sent anyway: §18 requires the interface to label proposal
    versus saved state, and a field the screen reads is harder to forget than a convention it is
    trusted to remember.
    """

    text: str
    sources: list[SourceRead]
    #: False when the answer is not drawn from retrieved material — the screen says so rather than
    #: presenting a guess in the same shape as a sourced answer.
    grounded: bool
    proposal: bool
    change: PreviewRead | None = None
    #: Set when the retrieved material contained something shaped like an instruction to the model.
    #: Surfaced to the reader: somebody put it there.
    injection_noticed: str | None = None
    #: True when no model answered. A supported state; `text` then names what matched.
    model_unavailable: bool


def _source(found: retrieval.Source) -> SourceRead:
    return SourceRead(
        kind=found.kind,
        id=found.id,
        label=found.label,
        text=found.text,
        href=found.href,
    )


def _preview(shown: preview.Preview) -> PreviewRead:
    return PreviewRead(
        kind=shown.kind,
        id=shown.id,
        label=shown.label,
        href=shown.href,
        changes=[
            ChangeRead(
                field=item.field,
                label=item.label,
                current=item.current,
                proposed=item.proposed,
            )
            for item in shown.changes
        ],
        refused=shown.refused,
    )


@router.post("/ask", summary="Ask about this workspace")
async def ask(
    body: Ask, session: SessionDep, settings: SettingsDep, context: CurrentContext
) -> AnswerRead:
    """Answer from what this person may read, and propose nothing that writes."""
    answer = await service.ask(session, settings, context, body.question)
    return AnswerRead(
        text=answer.text,
        sources=[_source(found) for found in answer.sources],
        grounded=answer.grounded,
        proposal=answer.proposal,
        change=_preview(answer.change) if answer.change is not None else None,
        injection_noticed=answer.injection_noticed,
        model_unavailable=answer.model_unavailable,
    )


@router.get("/search", summary="Search this workspace")
async def search(
    session: SessionDep,
    context: CurrentContext,
    q: Annotated[str, Query(max_length=200, description="What to look for.")] = "",
) -> list[SourceRead]:
    """The top bar's search — the same permission-filtered retrieval, without the model.

    No model call at all: a search box that waited on a completion would be slower than the
    sidebar. What comes back is objects this person may open, which is what a search box is for.
    """
    await guard.authorise(session, context, Action.VIEW)
    return [_source(found) for found in await retrieval.search(session, context, q)]
