"""A control that offers an action the server will refuse is a control that lies.

Three of the four Builder forms shipped one. `can_submit` is what the screen enables *Send for
approval* from, and on the Agent it was the status alone while `submit()` also demands an approver
and every gate; on the Supervisor it was `is_editable` alone while `submit()` demands an approver,
something supervised and a passing simulation gate. Neither screen could set an approver at all —
the Agent wrote a free-text label, the Supervisor had no control — so the button was permanently
enabled for a call that could only answer *"Name an approver — a person, not a role."*

`can_approve` compares the named approver against the signed-in membership, which settles the
question the repository disagreed with itself about: a role name can never match, so an approval
named by label alone can never be performed by anybody. The id is the approver. The label stays as
the note the workbook asked for.

These tests assert the flag and the call agree — in both directions. A flag that is merely always
false would satisfy the first half and is the failure this replaces, so each one also proves the
button turns on and the submission then succeeds.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import Workspace
from tests.integration.test_agent_publish import (
    _context as agent_context,
)
from tests.integration.test_agent_publish import (
    _five_passes,
    _grant,
    _ready_agent,
)
from tests.integration.test_supervisor_publish import (
    _context as supervisor_context,
)
from tests.integration.test_supervisor_publish import (
    _grant as supervisor_grant,
)
from tests.integration.test_supervisor_publish import (
    _ready,
    _scenarios,
)
from uboss.core.errors import ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.agents import agent_publish, agent_service
from uboss.modules.agents.agent_schemas import AgentUpdate
from uboss.modules.supervisors import publish as supervisor_publish


async def test_an_agent_without_a_named_person_says_it_cannot_be_submitted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The flag, the sentence and the call, all asking the same question.

    The screen's own gates are tests-and-permission, and the permission gate passes with no tools
    at all — so nothing else stops the button. `can_submit` is the only thing that can, and it was
    the status.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        #  `_context` binds the tenant before `_grant` writes, because row-level security refuses
        #  an insert into `role_permissions` on an unbound connection — and then again afterwards,
        #  so the context carries the permissions that were just granted.
        await agent_context(session, left)
        await _grant(session, left, "edit_draft", "publish")
        context = await agent_context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague
        )
        #  The approver goes first, and the tests are recorded after — because saving a design
        #  clears the sandbox results, so recording them first would leave the run reporting the
        #  test gate rather than the missing approver, and this test is about the approver.
        await agent_service.update(
            session,
            context,
            agent.id,
            AgentUpdate(
                expected_version=(await agent_service.read(session, context, agent.id)).version,
                main_approver_membership_id=None,
                main_approver_label="Department Head",
            ),
        )
        await session.flush()

        read = await agent_service.read(session, context, agent.id)
        await agent_publish.record_tests(
            session, context, agent.id, _five_passes(), expected_version=read.version
        )
        await session.flush()

        summary = await agent_publish.summary(session, context, agent.id)
        assert summary.can_submit is False, "a label is not somebody who can approve"
        assert "Name an approver" in summary.next_action

        current = await agent_service.read(session, context, agent.id)
        with pytest.raises(ValidationFailed) as refused:
            await agent_publish.submit(session, context, agent.id, current.version)
        assert "a person, not a role" in str(refused.value)
        await session.rollback()


async def test_an_agent_with_a_named_person_can_be_submitted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The other direction, which is what stops the fix being "always false"."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        #  `_context` binds the tenant before `_grant` writes, because row-level security refuses
        #  an insert into `role_permissions` on an unbound connection — and then again afterwards,
        #  so the context carries the permissions that were just granted.
        await agent_context(session, left)
        await _grant(session, left, "edit_draft", "publish")
        context = await agent_context(session, left)
        agent = await _ready_agent(
            session, context, left, approver_membership_id=colleague
        )
        read = await agent_service.read(session, context, agent.id)
        await agent_publish.record_tests(
            session, context, agent.id, _five_passes(), expected_version=read.version
        )
        await session.flush()
        await session.refresh(agent)

        summary = await agent_publish.summary(session, context, agent.id)
        assert summary.can_submit is True
        assert summary.next_action == "Send this for approval."

        await agent_publish.submit(session, context, agent.id, summary.version)
        await session.flush()
        await session.refresh(agent)
        assert agent.status == "ready_to_publish"
        await session.rollback()


async def test_a_supervisor_without_a_named_person_says_it_cannot_be_submitted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """The same shape, one form over — and this one had no approver control at all."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await supervisor_context(session, left)
        await supervisor_grant(session, left, "edit_draft", "publish")
        context = await supervisor_context(session, left)
        supervisor = await _ready(session, left, context, approver=colleague)
        await supervisor_publish.record_simulations(
            session, context, supervisor.id, _scenarios(), expected_version=supervisor.version
        )
        await session.flush()
        await session.refresh(supervisor)

        supervisor.approver_membership_id = None
        supervisor.version += 1
        await session.flush()

        summary = await supervisor_publish.summary(session, context, supervisor.id)
        assert summary.can_submit is False
        assert "Name an approver" in summary.next_action

        with pytest.raises(ValidationFailed) as refused:
            await supervisor_publish.submit(
                session, context, supervisor.id, supervisor.version
            )
        assert "a person, not a role" in str(refused.value)
        await session.rollback()


async def test_a_supervisor_with_a_named_person_can_be_submitted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Gate 6's deliverable, reachable.

    Also the reason `can_submit` could not simply gain the approver check on its own: it now
    carries the simulation gate too, so a supervisor whose scenarios have not passed says so
    instead of offering a button that the gate would refuse a moment later.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await supervisor_context(session, left)
        await supervisor_grant(session, left, "edit_draft", "publish")
        context = await supervisor_context(session, left)
        supervisor = await _ready(session, left, context, approver=colleague)

        #  Before the scenarios pass, the gate is the reason — not the approver.
        early = await supervisor_publish.summary(session, context, supervisor.id)
        assert early.can_submit is False

        await supervisor_publish.record_simulations(
            session, context, supervisor.id, _scenarios(), expected_version=supervisor.version
        )
        await session.flush()
        await session.refresh(supervisor)

        summary = await supervisor_publish.summary(session, context, supervisor.id)
        assert summary.can_submit is True

        await supervisor_publish.submit(session, context, supervisor.id, supervisor.version)
        await session.flush()
        await session.refresh(supervisor)
        assert supervisor.status == "ready_to_publish"
        assert supervisor.is_editable is False, "a submitted design holds still"
        await session.rollback()
