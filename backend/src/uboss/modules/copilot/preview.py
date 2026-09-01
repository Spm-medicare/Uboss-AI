"""A proposed change, shown as a difference, saved by nobody.

`PLAN.md` §12: *"Every mutation requires permission, preview and confirmation"*, and §337 spells
the Copilot's version out — *"proposal-versus-saved labeling, preview/diff, confirmation and audit
evidence"*.

## Where the writing does not happen

Nothing in this module writes. There is no branch, no flag and no parameter that makes it write.
That is the design rather than a property of the current code: a preview built by the module that
could also apply it is one `if` away from applying it, and the `if` will be added by somebody in a
hurry who reads `apply=False` as a default rather than as a boundary.

So confirmation is not a token this module issues and later redeems. Confirmation is **the person
opening the object and saving it themselves**, through the same route, the same permission check,
the same `expected_version` and the same audit row as any other edit. The preview's job is to make
that a short journey: it names the object, the fields and the difference, and it stops.

## Why only the fields retrieval already reads

`FIELDS` is deliberately the same handful of text fields `retrieval.py` searches. A Copilot that
could propose a change to a field it cannot see would be proposing from nothing — and the fields it
cannot see are the ones that matter: an approver, a schedule, a permission, a model. Those are
decisions with their own screens, their own step-up and their own reasons, and a side panel is not
where they get made.

The consequence worth stating: **a proposal can only ever be words.** Not a state, not a
relationship, not an access grant.

## Two ways a proposal is refused, both in words

A proposal on an object the person may not edit, and a proposal on an object that is no longer
editable — submitted, approved, published. The second is the interesting one: between submitting
and approving, a design has to hold still or the approver approves something other than what was
sent. A Copilot that offered to edit it anyway would be offering to break that, and the refusal
says which state the object is in rather than only that the answer is no.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.permissions import Action
from uboss.modules.agents.agent_models import Agent
from uboss.modules.agents.agent_service import EDITABLE as AGENT_EDITABLE
from uboss.modules.identity import policies
from uboss.modules.jobs.models import Job
from uboss.modules.objectives.models import Objective
from uboss.modules.supervisors.models import Supervisor

#: What may be proposed, per kind: the attribute, and the label a person reads.
#:
#: The same text fields `retrieval.py` searches, for the reason in this file's header — a proposal
#: about a field the Copilot cannot read is a proposal about nothing.
FIELDS: dict[str, dict[str, str]] = {
    "objective": {
        "title": "Title",
        "description": "Description",
        "expected_result": "Expected result",
    },
    "job": {
        "name": "Name",
        "purpose": "Purpose",
        "high_level_work": "High-level work",
    },
    "agent": {"name": "Name", "purpose": "Purpose"},
    "supervisor": {"name": "Name", "purpose": "Purpose"},
}

#: Where a person goes to make the change themselves. The preview ends here; the route does the
#: work, with the ordinary permission check and the ordinary audit row.
ROUTES: dict[str, str] = {
    "objective": "/objective-builder/{id}",
    "job": "/job-builder/{id}",
    "agent": "/agent-builder/{id}",
    "supervisor": "/supervisor/{id}",
}

#: The table behind each kind. Typed as the union rather than as `type[Base]` so the columns below
#: are checked at each member — the shared base declares neither `tenant_id` nor `archived_at`.
_MODELS: dict[str, type[Objective] | type[Job] | type[Agent] | type[Supervisor]] = {
    "objective": Objective,
    "job": Job,
    "agent": Agent,
    "supervisor": Supervisor,
}

#: A proposed value longer than this is a rewrite rather than a suggestion, and a diff of it is
#: unreadable in a side panel. Truncated rather than refused: the words are still useful.
MAX_VALUE = 2000


@dataclass(frozen=True, slots=True)
class Change:
    """One field, as it is and as it is proposed."""

    field: str
    label: str
    #: What the object says today. Read from the row, never from the model — a diff whose "before"
    #: came from the same place as its "after" is not a diff.
    current: str
    proposed: str


@dataclass(frozen=True, slots=True)
class Preview:
    """A change somebody could make, described well enough to decide on.

    Carries no token, no id to redeem and no expiry, because there is nothing to redeem it against.
    `href` is the whole mechanism: the person opens the object and saves it themselves.
    """

    kind: str
    id: uuid.UUID
    label: str
    href: str
    changes: list[Change] = field(default_factory=list)
    #: Why this cannot be done, when it cannot. A refused preview still names the object, so the
    #: person can see what was meant and go and look.
    refused: str | None = None

    @property
    def actionable(self) -> bool:
        """Whether there is something for a person to go and do."""
        return self.refused is None and bool(self.changes)


def _current(row: object, attribute: str) -> str:
    value = getattr(row, attribute, None)
    return str(value).strip() if value is not None else ""


async def _row(
    session: AsyncSession, context: SecurityContext, kind: str, target_id: uuid.UUID
) -> Any | None:
    """The object, named by tenant as well as by id.

    Both boundaries, as `CLAUDE.md` requires: the `tenant_id` predicate here and row-level security
    underneath. The retrieval module's header records what happened the one time this file's
    sibling relied on RLS alone.
    """
    model = _MODELS.get(kind)
    if model is None:
        return None
    return (
        await session.execute(
            select(model).where(
                model.tenant_id == context.tenant_id,
                model.id == target_id,
                model.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()


def _editable(kind: str, row: Any) -> bool:
    """Whether a draft edit is possible at all right now.

    Asks each module its own question rather than testing a status string here: `is_editable` and
    `agents.EDITABLE` are where the answer lives, and a fifth copy of *"draft or needs_review"* is
    how the four existing ones came to disagree.
    """
    if kind == "agent":
        return bool(row.status in {state.value for state in AGENT_EDITABLE})
    return bool(row.is_editable)


async def build(
    session: AsyncSession,
    context: SecurityContext,
    *,
    kind: str,
    target_id: uuid.UUID,
    proposed: dict[str, str],
) -> Preview | None:
    """The difference between what an object says and what was proposed for it.

    Returns `None` when there is nothing to show at all — an unknown kind, an object that is not
    there, or a proposal naming no field this kind has. A `Preview` with `refused` set is a
    different outcome: the object exists and the person should be told why not.
    """
    allowed_fields = FIELDS.get(kind)
    if allowed_fields is None:
        return None

    row = await _row(session, context, kind, target_id)
    if row is None:
        return None

    label = _current(row, "title") or _current(row, "name") or kind
    href = ROUTES[kind].format(id=target_id)

    #  Permission first, and the object's own state second — a person who may not edit it does not
    #  need to hear about its status.
    grant = await policies.grant_for_resource(
        session,
        tenant_id=context.tenant_id,
        membership_id=context.membership_id,
        resource_type=kind,
        resource_id=target_id,
        role_actions=context.granted_actions,
    )
    if not context.explain(Action.EDIT_DRAFT, grant).allowed:
        return Preview(
            kind=kind,
            id=target_id,
            label=label,
            href=href,
            refused=(
                "I can suggest wording for this, but changing it is not something your access "
                "covers. Ask whoever owns it."
            ),
        )

    if not _editable(kind, row):
        return Preview(
            kind=kind,
            id=target_id,
            label=label,
            href=href,
            refused=(
                f"This is {str(row.status).replace('_', ' ')}, so it is not being edited now. "
                "A design has to hold still between being sent and being decided on."
            ),
        )

    changes: list[Change] = []
    for attribute, field_label in allowed_fields.items():
        if attribute not in proposed:
            continue
        wanted = str(proposed[attribute] or "").strip()[:MAX_VALUE]
        if not wanted:
            #  Emptying a field is not a suggestion; it is a deletion with no reason attached.
            continue
        current = _current(row, attribute)
        if wanted == current:
            continue
        changes.append(
            Change(field=attribute, label=field_label, current=current, proposed=wanted)
        )

    if not changes:
        return None

    return Preview(kind=kind, id=target_id, label=label, href=href, changes=changes)
