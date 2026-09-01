"""Notifications — the rules that decide whether a bell is worth looking at.

A notification system fails in one direction: it becomes noise, people mute it, and then the one
that mattered arrives in a channel nobody reads. Every rule tested here exists to prevent that,
and the two that matter most are the ones a naive implementation gets wrong — folding repeats
into one line, and never telling somebody what they just did themselves.

Nine properties:

* a repeat of an unread fact folds in and counts, instead of stacking up;
* the same fact after it has been *read* starts a new line — an acknowledged problem recurring
  silently forever is the worse failure;
* nobody is told about their own action;
* `off` means off — no bell row, no mail;
* quiet hours defer email and never suppress the bell;
* quiet hours crossing midnight work, which the naive comparison gets exactly backwards;
* security is never quiet;
* a digest goes once a day and covers exactly what happened since the last one;
* an assigned task reaches the assignee's bell through the real task path.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.digest_worker import send_due
from uboss.modules.audit.models import OutboxEvent
from uboss.modules.notifications import policy
from uboss.modules.notifications import service as notify
from uboss.modules.notifications.models import (
    Category,
    Delivery,
    Notification,
    NotificationPreference,
    NotificationSettings,
)
from uboss.modules.runtime import service as runtime
from uboss.modules.runtime.models import Run, RunTrigger
from uboss.modules.tasks import service as tasks

pytestmark = pytest.mark.anyio


async def _raise(
    session: AsyncSession,
    workspace: Workspace,
    *,
    membership_id: uuid.UUID | None = None,
    category: str = Category.AGENT_RESULT,
    dedupe_key: str = "thing:1",
    title: str = "Something happened",
    **extra: object,
) -> notify.Raised:
    return await notify.raise_for(
        session,
        tenant_id=workspace.tenant_id,
        membership_id=membership_id or workspace.membership_id,
        category=category,
        event="test.event",
        title=title,
        deep_link="/todo",
        dedupe_key=dedupe_key,
        **extra,  # type: ignore[arg-type]
    )


async def _rows(
    session: AsyncSession, membership_id: uuid.UUID
) -> list[Notification]:
    return list(
        (
            await session.execute(
                select(Notification)
                .where(Notification.membership_id == membership_id)
                .order_by(Notification.created_at)
            )
        )
        .scalars()
        .all()
    )


async def test_a_repeat_folds_into_one_unread_line(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**The rule that stops a bell being noise.**

    Five failures of one job overnight are one line saying it failed five times, not five
    identical lines. Five identical lines is the shape people mute — and once muted, the one that
    mattered arrives somewhere nobody is looking.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            first = await _raise(session, left, title="Nightly close failed")
            assert first.deduped is False

            for _ in range(4):
                again = await _raise(session, left, title="Nightly close failed")
                assert again.deduped is True
                assert again.notification_id == first.notification_id

            rows = await _rows(session, left.membership_id)
            assert len(rows) == 1
            assert rows[0].occurrences == 5
            #  The newest wording wins, and `last_at` is when it last went wrong — which is what
            #  the drawer orders by.
            assert rows[0].last_at >= rows[0].created_at


async def test_the_same_fact_after_reading_starts_a_new_line(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The dedupe index is **partial** — `WHERE read_at IS NULL` — and this is why.

    Something recurring after you have acknowledged it is genuinely new information. Suppressing
    it would mean a problem somebody had already seen could recur silently forever, which is a
    worse failure than a duplicate line.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            await _raise(session, left)
            await notify.mark_all_read(session, left.membership_id)

            await _raise(session, left)

            rows = await _rows(session, left.membership_id)
            assert len(rows) == 2
            assert rows[0].read_at is not None
            assert rows[1].read_at is None
            assert await notify.unread_count(session, left.membership_id) == 1


async def test_nobody_is_told_about_their_own_action(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The commonest way a bell becomes noise is telling people what they just did.

    Checked in `raise_for` rather than at each call site, so no caller has to remember — there
    are a dozen of them and one forgetting is all it takes.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            raised = await _raise(
                session, left, actor_membership_id=left.membership_id
            )

            assert raised.notification_id is None
            assert raised.channels == frozenset()
            assert await _rows(session, left.membership_id) == []


async def test_off_means_off(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A person who chose silence gets it — no bell row and no mail.

    An unread row they never wanted is not silence, and is exactly what makes somebody stop
    trusting the preference screen.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            session.add(
                NotificationPreference(
                    tenant_id=left.tenant_id,
                    membership_id=left.membership_id,
                    category=Category.AGENT_RESULT,
                    in_app=True,
                    email=True,
                    delivery=Delivery.OFF,
                )
            )
            await session.flush()

            raised = await _raise(session, left, category=Category.AGENT_RESULT)

            assert raised.channels == frozenset()
            assert await _rows(session, left.membership_id) == []


async def test_quiet_hours_defer_email_and_never_hide_the_bell(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """**The distinction the whole feature turns on.**

    An in-app notification is not an interruption — it is a list that is there when somebody
    looks. Quiet hours are about not being *reached*, so mail is deferred to the digest and the
    bell fills up normally. A bell that also went quiet would hide the work that arrived
    overnight, which is exactly what people check it for in the morning.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            session.add(
                NotificationSettings(
                    tenant_id=left.tenant_id,
                    membership_id=left.membership_id,
                    quiet_hours_enabled=True,
                    quiet_from=time(22, 0),
                    quiet_to=time(7, 0),
                    timezone="Asia/Kolkata",
                )
            )
            await session.flush()

            #  02:30 IST — inside the window, and on the far side of midnight.
            middle_of_the_night = datetime(2026, 6, 1, 21, 0, tzinfo=UTC)
            raised = await _raise(
                session,
                left,
                category=Category.TASK_ASSIGNMENT,
                now=middle_of_the_night,
            )

            assert policy.Channel.IN_APP in raised.channels
            assert policy.Channel.EMAIL_DIGEST in raised.channels
            assert policy.Channel.EMAIL_NOW not in raised.channels
            assert len(await _rows(session, left.membership_id)) == 1


def test_quiet_hours_across_midnight() -> None:
    """The case a naive `start <= t <= end` gets exactly backwards.

    22:00 to 07:00 would then match *nothing at all*, and the feature would look switched off
    rather than broken — which is how it survives a review.
    """
    zone = "Asia/Kolkata"
    inside_late = datetime(2026, 6, 1, 17, 0, tzinfo=UTC)  # 22:30 IST
    inside_early = datetime(2026, 6, 1, 1, 0, tzinfo=UTC)  # 06:30 IST
    outside = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)  # 11:30 IST

    for moment in (inside_late, inside_early):
        assert policy.is_quiet(
            moment,
            enabled=True,
            start=time(22, 0),
            end=time(7, 0),
            timezone=zone,
        )
    assert not policy.is_quiet(
        outside, enabled=True, start=time(22, 0), end=time(7, 0), timezone=zone
    )
    #  A zero-length window is "no quiet hours", not "always quiet" — the alternative silences
    #  somebody's mail forever because two fields happened to match.
    assert not policy.is_quiet(
        inside_late, enabled=True, start=time(9, 0), end=time(9, 0), timezone=zone
    )


def test_security_is_never_quiet() -> None:
    """*"Somebody signed in from a new device"* at 2 a.m. is the one notification whose whole
    value is arriving at 2 a.m. A preference that could silence it would help an attacker."""
    at_night = datetime(2026, 6, 1, 17, 0, tzinfo=UTC)  # 22:30 IST
    channels = policy.channels_for(
        category=Category.SECURITY_ADMIN,
        chosen=None,
        now=at_night,
        quiet_hours_enabled=True,
        quiet_from=time(22, 0),
        quiet_to=time(7, 0),
        timezone="Asia/Kolkata",
    )
    assert policy.Channel.EMAIL_NOW in channels
    assert policy.Channel.EMAIL_DIGEST not in channels

    #  Every other category *is* deferred at the same instant — so the exemption is the security
    #  one, not a broken window.
    ordinary = policy.channels_for(
        category=Category.TASK_ASSIGNMENT,
        chosen=None,
        now=at_night,
        quiet_hours_enabled=True,
        quiet_from=time(22, 0),
        quiet_to=time(7, 0),
        timezone="Asia/Kolkata",
    )
    assert policy.Channel.EMAIL_DIGEST in ordinary


async def test_a_digest_goes_once_a_day_and_covers_what_happened_since(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Guarded by `last_digest_at`, not by a timer.

    The worker ticks four times an hour; without the guard a person would get four digests
    inside their digest hour, and a restarted worker would send another. The second call here is
    the assertion.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            session.add(
                NotificationSettings(
                    tenant_id=left.tenant_id,
                    membership_id=left.membership_id,
                    timezone="Asia/Kolkata",
                    digest_hour=9,
                )
            )
            await _raise(session, left, title="Yesterday's failure")
            await session.flush()

            #  09:30 IST.
            morning = datetime(2026, 6, 1, 4, 0, tzinfo=UTC)
            staged = await send_due(session, tenant_id=left.tenant_id, now=morning)
            assert staged == 1

            #  Ten minutes later, still inside the digest hour. Nothing more is owed.
            again = await send_due(
                session,
                tenant_id=left.tenant_id,
                now=morning + timedelta(minutes=10),
            )
            assert again == 0

            #  `audit.publish` stages the row; the sessionmaker sets `autoflush=False`, so it is
            #  not in the database until something flushes. The worker's own commit does this in
            #  production.
            await session.flush()

            events = list(
                (
                    await session.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.event_type == notify.DIGEST_EVENT
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1
            assert events[0].payload["lines"][0]["title"] == "Yesterday's failure"


async def test_an_assigned_task_reaches_the_assignee_through_the_real_path(
    owner_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """End to end through `tasks.create_for_step`, not by calling the notifier directly.

    The wiring is the part that breaks: a notification module that works in isolation and is
    never called is the commonest way this feature ships broken.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            job_id = uuid.uuid4()
            version_id = uuid.uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO jobs (id, tenant_id, name, status, owner_membership_id)
                    VALUES (:id, :tenant, 'Month end', 'draft', :owner)
                    """
                ),
                {
                    "id": job_id,
                    "tenant": left.tenant_id,
                    "owner": left.membership_id,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO job_versions
                        (id, tenant_id, job_id, snapshot, name, correlation_id)
                    VALUES (:id, :tenant, :job, CAST(:snapshot AS jsonb), 'Month end', 'test')
                    """
                ),
                {
                    "id": version_id,
                    "tenant": left.tenant_id,
                    "job": job_id,
                    "snapshot": json.dumps(
                        {
                            "steps": [
                                {
                                    "position": 1,
                                    "mode": "human",
                                    "what_exact_work": "Reconcile the ledger",
                                }
                            ],
                            "assignment_rules": [
                                {
                                    "position": 1,
                                    "who_type": "user",
                                    "target_id": str(colleague),
                                }
                            ],
                        }
                    ),
                },
            )
            await session.execute(
                text(
                    "UPDATE jobs SET status='published', published_version_id=:v "
                    "WHERE id=:id"
                ),
                {"v": version_id, "id": job_id},
            )

            started = await runtime.start(
                session,
                tenant_id=left.tenant_id,
                job_version_id=version_id,
                trigger=RunTrigger.MANUAL,
            )
            run = (
                await session.execute(select(Run).where(Run.id == started.run_id))
            ).scalar_one()
            step = await runtime.next_step(session, run.id)
            assert step is not None
            await runtime.begin_step(session, run, step)
            await runtime.wait_for_person(session, run, step)
            await tasks.create_for_step(session, run, step)

            rows = await _rows(session, colleague)
            assert len(rows) == 1
            assert rows[0].category == Category.TASK_ASSIGNMENT
            assert rows[0].action_required is True
            #  A path, never a full URL — the origin is configuration, so a deployment that
            #  moves domain does not have to rewrite everybody's history.
            assert rows[0].deep_link.startswith("/todo")
            assert await notify.action_required_count(session, colleague) == 1
