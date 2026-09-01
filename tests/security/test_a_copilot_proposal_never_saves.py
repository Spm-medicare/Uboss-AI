"""Mutation preview — the last of Gate 7's six named Copilot exit tests.

`PLAN.md` §12: *"Every mutation requires permission, preview and confirmation."* §337 adds
*"preview/diff, confirmation and audit evidence"*.

The interesting thing to test is not that a diff is computed correctly. It is that **there is no
way to apply it** — no route, no flag, no parameter — and that the two refusals a preview can carry
are the right ones. So the assertions here are mostly negative, and one of them reads the published
API surface rather than any Python: an `apply` route added later would fail that test on the day it
appears, which is the only moment anybody could still be talked out of it.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.permissions import Action
from uboss.core.settings import Settings
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.audit.models import AuditEvent
from uboss.modules.copilot import preview, service
from uboss.modules.objectives.models import Objective, ObjectiveStatus

PHRASE = "quotation turnaround"


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    from tests.integration.test_objective_analysis import _context as build

    return await build(session, workspace)


async def _objective(session: AsyncSession, workspace: Workspace, title: str) -> Objective:
    row = Objective(
        tenant_id=workspace.tenant_id,
        title=title,
        department="Sales",
        expected_result="Quotations out within one working day.",
        description="Sales sends quotations by hand today.",
        owner_membership_id=workspace.membership_id,
        created_by_membership_id=workspace.membership_id,
    )
    session.add(row)
    await session.flush()
    return row


def _proposal(objective_id: uuid.UUID, **fields: str) -> dict[str, Any]:
    return {
        "answer": "Here is a clearer wording.",
        "used_source_ids": [str(objective_id)],
        "answered_from_sources": True,
        "proposed_change": {
            "target_kind": "objective",
            "target_id": str(objective_id),
            "fields": [{"name": name, "value": value} for name, value in fields.items()],
        },
    }


# ── the diff ──────────────────────────────────────────────────────────────────────────────


async def test_a_proposal_is_a_difference_against_what_the_object_says_now(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], model: Any
) -> None:
    """`current` comes from the row, never from the model.

    A diff whose "before" was supplied by the same thing that supplied the "after" is not a diff —
    it is two sentences from a model, one of them labelled *current*, and a reader who trusts it
    approves a change against a state that may never have existed.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective = await _objective(session, left, f"Reduce {PHRASE}")
            context = await _context(session, left)
            model.answer["content"] = _proposal(
                objective.id, expected_result="Quotations out within four working hours."
            )

            answer = await service.ask(session, Settings(), context, PHRASE)

            assert answer.change is not None
            change = answer.change
            assert change.actionable is True
            assert change.label == f"Reduce {PHRASE}"
            assert change.href == f"/objective-builder/{objective.id}"
            assert len(change.changes) == 1
            assert change.changes[0].field == "expected_result"
            assert change.changes[0].label == "Expected result"
            assert change.changes[0].current == "Quotations out within one working day."
            assert change.changes[0].proposed == "Quotations out within four working hours."
            await session.rollback()


async def test_a_field_the_copilot_may_not_propose_is_dropped(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], model: Any
) -> None:
    """The allow-list, from the other side.

    `preview.FIELDS` is the same handful of text fields retrieval searches. Everything else — a
    status, an approver, a visibility, an owner — has its own screen, its own permission and often
    its own step-up. A proposal naming one of those is not refused with a message; it is simply not
    a field this mechanism has, which is why it cannot become one by accident.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective = await _objective(session, left, f"Reduce {PHRASE}")
            context = await _context(session, left)
            model.answer["content"] = _proposal(
                objective.id,
                title="A clearer title",
                #  Not in FIELDS: a state transition, an owner and a visibility.
                status="published",
                owner_membership_id=str(uuid.uuid4()),
                visibility="company",
            )

            answer = await service.ask(session, Settings(), context, PHRASE)

            assert answer.change is not None
            assert [item.field for item in answer.change.changes] == ["title"]
            #  And the object itself is untouched by any of it.
            row = await session.get(Objective, objective.id)
            assert row is not None
            assert row.status == ObjectiveStatus.DRAFT
            await session.rollback()


async def test_a_proposal_that_changes_nothing_is_not_shown(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], model: Any
) -> None:
    """A diff with no difference is a panel asking somebody to approve a no-op."""
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective = await _objective(session, left, f"Reduce {PHRASE}")
            context = await _context(session, left)
            model.answer["content"] = _proposal(objective.id, title=f"Reduce {PHRASE}")

            answer = await service.ask(session, Settings(), context, PHRASE)

            assert answer.change is None
            await session.rollback()


async def test_an_emptied_field_is_not_a_suggestion(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], model: Any
) -> None:
    """Blanking a field is a deletion with no reason attached, and the model does not get to ask.

    A person can empty a field themselves on the screen, where it is visibly their own doing.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective = await _objective(session, left, f"Reduce {PHRASE}")
            context = await _context(session, left)
            model.answer["content"] = _proposal(objective.id, description="   ")

            answer = await service.ask(session, Settings(), context, PHRASE)

            assert answer.change is None
            await session.rollback()


# ── the two refusals ──────────────────────────────────────────────────────────────────────


async def test_a_design_that_has_been_sent_for_approval_holds_still(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], model: Any
) -> None:
    """The refusal that protects an approval's meaning.

    Between submitting and approving, a design must not move: otherwise the approver approves
    something other than what was sent, and the immutable version published from it is not the
    thing that was reviewed. The refusal names the state rather than only saying no, because
    *"it is waiting for approval"* tells the person what to do next and *"not allowed"* does not.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective = await _objective(session, left, f"Reduce {PHRASE}")
            #  Submitted properly: the table refuses a `ready_to_publish` row that names nobody,
            #  and a test that got round that constraint would be testing a state the product
            #  cannot reach.
            objective.status = ObjectiveStatus.READY_TO_PUBLISH
            objective.submitted_by_membership_id = left.membership_id
            objective.submitted_at = datetime.now(UTC)
            await session.flush()
            context = await _context(session, left)
            model.answer["content"] = _proposal(objective.id, title="Something else")

            answer = await service.ask(session, Settings(), context, PHRASE)

            assert answer.change is not None
            assert answer.change.actionable is False
            assert answer.change.changes == []
            assert answer.change.refused is not None
            assert "ready to publish" in answer.change.refused
            await session.rollback()


async def test_somebody_who_may_read_but_not_edit_is_told_so(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], model: Any
) -> None:
    """Permission is checked before the object's state, and refused in the person's own terms.

    The Copilot reads with `view`; proposing an edit is checked against `edit_draft` — the same
    action the save route checks. A person who may read an objective but not change it gets the
    wording and is told the change is not theirs to make, rather than getting a diff with a button
    that would fail.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective = await _objective(session, left, f"Reduce {PHRASE}")
            full = await _context(session, left)
            #  The same person, without the one action. Frozen dataclass, so a copy — nothing can
            #  widen a caller's reach mid-request, which is why `replace` and not assignment.
            reader = dataclasses.replace(
                full,
                granted_actions=frozenset(full.granted_actions - {Action.EDIT_DRAFT}),
            )

            shown = await preview.build(
                session,
                reader,
                kind="objective",
                target_id=objective.id,
                proposed={"title": "A clearer title"},
            )

            assert shown is not None
            assert shown.actionable is False
            assert shown.changes == []
            assert shown.refused is not None
            assert "your access" in shown.refused
            #  Never blames the reader's permissions in a way that is false, and never suggests an
            #  administrator: the point is who owns the object.
            assert "not allowed" not in shown.refused.lower()
            await session.rollback()


# ── nothing applies it ────────────────────────────────────────────────────────────────────


async def test_a_target_that_was_never_retrieved_is_not_a_target(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], model: Any
) -> None:
    """Retrieval is where the permission filter runs, so a target must come from it.

    Otherwise the id is just a uuid the model wrote down, and a sentence in company text could
    choose which object a proposal lands on — including one this person has never been allowed to
    see. Nothing would be written either way; what would leak is the object's current wording,
    shown in the diff.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective = await _objective(session, left, f"Reduce {PHRASE}")
            context = await _context(session, left)
            stranger = uuid.uuid4()
            model.answer["content"] = {
                "answer": "Here.",
                "used_source_ids": [str(objective.id)],
                "answered_from_sources": True,
                "proposed_change": {
                    "target_kind": "objective",
                    "target_id": str(stranger),
                    "fields": [{"name": "title", "value": "Renamed"}],
                },
            }

            answer = await service.ask(session, Settings(), context, PHRASE)

            assert answer.change is None
            await session.rollback()


async def test_the_record_says_a_proposal_was_made_and_not_what_it_said(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], model: Any
) -> None:
    """§12 asks for audit evidence of a proposal. The evidence is that one was made, on what.

    The proposed words are deliberately not stored. They are not a decision until somebody saves
    them, and then they are in the object's own audit row — where an auditor would look for them,
    with the person's name on them.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            objective = await _objective(session, left, f"Reduce {PHRASE}")
            context = await _context(session, left)
            wording = "Quotations out within four working hours."
            model.answer["content"] = _proposal(objective.id, expected_result=wording)

            await service.ask(session, Settings(), context, PHRASE)
            await session.flush()

            row = (
                (
                    await session.execute(
                        select(AuditEvent).where(AuditEvent.action == "copilot.asked")
                    )
                )
                .scalars()
                .all()
            )[-1]
            detail = row.detail or {}
            assert detail["proposed"] == {
                "kind": "objective",
                "id": str(objective.id),
                "fields": ["expected_result"],
                "refused": False,
            }
            assert wording not in str(detail), "the proposed words are not stored"
            await session.rollback()


def test_the_api_offers_no_way_to_apply_one() -> None:
    """The structural assertion, read from the published contract.

    Not a comment and not a convention: `backend/openapi.json` is what the frontend generates its
    client from, and if an `apply` route ever exists it exists here. A test on the contract fails on
    the day the route is added, which is the only moment anybody could still be talked out of it.
    """
    from uboss.main import create_app

    paths = {
        path
        for path in create_app().openapi()["paths"]
        if "/copilot" in path
    }
    assert paths == {"/api/v1/copilot/ask", "/api/v1/copilot/search"}, (
        "the Copilot's whole surface is one question and one search"
    )


def test_nothing_in_the_preview_module_can_write() -> None:
    """Belt to the contract's braces, at the layer a future caller would reach for.

    A `POST /copilot/apply` is one obvious way this gets broken; another is an internal caller
    importing `preview` and passing something that saves. There is nothing to pass: the module
    exposes one coroutine, it returns a dataclass, and it never touches the session except to read.
    """
    import inspect

    source = inspect.getsource(preview)
    writes = ("session.add", "session.delete", "session.commit", "session.flush", "setattr")
    for forbidden in writes:
        assert forbidden not in source, f"{forbidden} has no business in a preview"
