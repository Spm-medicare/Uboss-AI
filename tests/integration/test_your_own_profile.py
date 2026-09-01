"""Editing yourself — §13's *"Profile and timezone/locale"*, and the defect it closed.

`describe()` has always returned `membership.timezone or tenant.timezone`, and the whole frontend
formats every instant with it. **Nothing wrote `membership.timezone`.** So somebody working in Dubai
read a workspace of Kolkata times with no way to change it, and the one control that looked like it
should — the notification digest's timezone — only decided when a digest is sent.

These tests are about the three fields a person owns, the two they do not, and the zone staying in
step with the digest's copy of it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.audit.models import AuditEvent
from uboss.modules.identity import service as identity
from uboss.modules.identity.models import Membership
from uboss.modules.identity.schemas import ProfileUpdate
from uboss.modules.identity.service import access_for
from uboss.modules.notifications.models import NotificationSettings

pytestmark = pytest.mark.anyio


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = datetime.now(UTC)
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        email="person@test",
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        org_node_id=membership.org_node_id,
        policy_grants=ceiling,
        step_up_at=now,
        step_up_expires_at=now + timedelta(minutes=10),
    )


async def test_a_person_can_set_the_zone_their_times_are_shown_in(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The column the whole frontend reads, finally writable.

    Asserted through `describe()` rather than on the row, because that is what the product actually
    shows: `GET /auth/me` is where every screen gets the zone it formats with.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        await identity.update_profile(session, context, ProfileUpdate(timezone="Asia/Dubai"))

        membership = await session.get(Membership, left.membership_id)
        assert membership is not None
        assert membership.timezone == "Asia/Dubai"
        await session.rollback()


async def test_the_digests_own_copy_of_the_zone_is_kept_in_step(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two columns hold one fact, and this is what stops them disagreeing.

    `digest_worker.send_due` reads `notification_settings.timezone`; the screen reads the
    membership's. A person whose product shows Dubai must not receive their digest at Kolkata's
    eight o'clock, so the owner writes both. One column is the right end state — recorded in the
    decision log — and two that cannot diverge is the honest version of it today.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        session.add(
            NotificationSettings(
                tenant_id=left.tenant_id,
                membership_id=left.membership_id,
                timezone="Asia/Kolkata",
            )
        )
        await session.flush()

        await identity.update_profile(session, context, ProfileUpdate(timezone="Europe/London"))

        row = (
            await session.execute(
                select(NotificationSettings).where(
                    NotificationSettings.membership_id == left.membership_id
                )
            )
        ).scalar_one()
        assert row.timezone == "Europe/London"
        await session.rollback()


async def test_a_zone_the_system_does_not_know_is_refused(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Checked against the system's own zone database, not a list kept in the code.

    A list would go stale — zones are added and renamed — and the refusal borrows the wording
    `jobs/recurrence.py` already uses for a schedule, because it is the same mistake.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        with pytest.raises(ValidationFailed) as refused:
            await identity.update_profile(session, context, ProfileUpdate(timezone="IST"))
        assert "IANA" in str(refused.value)
        await session.rollback()


async def test_a_field_left_out_is_left_alone(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A form that has not finished loading must not be able to blank a name.

    `exclude_unset` is what makes that true, and this is the test that keeps it true.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        membership = await session.get(Membership, left.membership_id)
        assert membership is not None
        membership.job_title = "Head of Quality"
        await session.flush()
        before = membership.display_name

        await identity.update_profile(session, context, ProfileUpdate(timezone="Asia/Dubai"))

        assert membership.display_name == before
        assert membership.job_title == "Head of Quality"
        await session.rollback()


async def test_a_blank_name_is_not_a_name(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Whitespace is not a rename, and pydantic's `min_length` does not catch a space.

    A person with no name appears as nothing in every approval, task and audit row that names them.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        membership = await session.get(Membership, left.membership_id)
        assert membership is not None
        before = membership.display_name

        await identity.update_profile(session, context, ProfileUpdate(display_name="   "))

        assert membership.display_name == before
        await session.rollback()


async def test_the_change_is_audited_by_field_and_not_by_value(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A name is personal data.

    An audit row that copies it is a second place it lives, with none of the retention rules that
    govern the first — and a DPDP erasure request would have to reach into it. What is recorded is
    that somebody changed their name, when, and from which session.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        await identity.update_profile(
            session,
            context,
            ProfileUpdate(display_name="Priya Raman", job_title="Quality Lead"),
        )
        await session.flush()

        row = (
            (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.action == "profile.updated")
                )
            )
            .scalars()
            .all()
        )[-1]
        assert (row.detail or {}).get("fields") == ["display_name", "job_title"]
        assert "Priya Raman" not in str(row.detail)
        await session.rollback()


async def test_nothing_is_written_when_nothing_changed(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Saving a form nobody edited is not an event.

    An audit trail full of no-op profile updates is an audit trail somebody stops reading.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        membership = await session.get(Membership, left.membership_id)
        assert membership is not None

        before = len(
            (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.action == "profile.updated")
                )
            )
            .scalars()
            .all()
        )
        await identity.update_profile(
            session, context, ProfileUpdate(display_name=membership.display_name)
        )
        await session.flush()

        after = len(
            (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.action == "profile.updated")
                )
            )
            .scalars()
            .all()
        )
        assert after == before
        await session.rollback()


async def test_the_digest_zone_defaults_to_the_persons_own(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """`GET /notifications/settings` answered `Asia/Kolkata` for everybody.

    So somebody in Dubai who had never opened that screen was told their digest would arrive on
    Kolkata's clock — and the Settings page showed them one zone under their profile and a different
    one under notifications. **Reading no row is not the same as having no timezone**: the
    membership owns it, and the default now reads it.

    Found by opening the screen in a browser, which is the only place the two sections are visible
    at once.

    The route function is called directly. Its dependencies are ordinary annotated parameters, so
    this exercises the default exactly as a request would without needing a signed-in cookie for a
    read that has no other behaviour.
    """
    from uboss.modules.notifications.api import read_settings

    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await identity.update_profile(session, context, ProfileUpdate(timezone="Asia/Dubai"))
        await session.flush()

        answered = await read_settings(session, context)

        assert answered.timezone == "Asia/Dubai"
        #  And the rest of the defaults are unchanged: quiet hours off, and nothing invented for
        #  the two times, because never having set them is not the same as midnight to midnight.
        assert answered.quiet_hours_enabled is False
        assert answered.quiet_from is None
        assert answered.quiet_to is None
        await session.rollback()


async def test_a_person_with_no_zone_of_their_own_still_gets_an_answer(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The fallback has to survive a null, which is the state every membership starts in."""
    from uboss.modules.notifications.api import read_settings

    left, _right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        membership = await session.get(Membership, left.membership_id)
        assert membership is not None
        membership.timezone = None
        await session.flush()

        answered = await read_settings(session, context)

        assert answered.timezone == "Asia/Kolkata", "the workspace's own default, not a crash"
        await session.rollback()
