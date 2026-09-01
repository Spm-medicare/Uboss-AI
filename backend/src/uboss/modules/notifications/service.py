"""Raising a notification, and the bell that reads them back.

**Nothing here decides anything.** The judgements — which channels, quiet hours, the digest
window, what somebody gets before they have chosen — are in `policy.py`, pure and testable by
calling a function. This is the I/O half: read the preference, apply the policy, write the row,
stage the mail.

## One statement, not a read-then-write

`raise_for` inserts with `ON CONFLICT … DO UPDATE`. The alternative — SELECT, then INSERT or
UPDATE — is a race between two workers that both find nothing and both insert, and the partial
unique index then refuses one of them mid-transaction. Gate 7.4 learnt this the expensive way:
catching that violation leaves the failed row *pending* in the session, and the caller's own
commit re-issues it. A statement that simply folds has none of that.

The conflict target names the partial index's predicate — `WHERE read_at IS NULL` — so a repeat
folds into an unread row and starts a fresh one once the old has been read. That is the point of
the index being partial: something recurring after you have acknowledged it is genuinely new.

## Raising cannot fail the thing that caused it

`raise_for` is called from inside the transaction that assigned a task or decided an approval. It
must never be the reason that transaction fails, so it takes no locks, makes no external call,
and every branch that cannot proceed returns rather than raising. A notification is a courtesy;
the work it describes has already happened and is already recorded.

The one exception is a programming error — an unknown category, a deep link that is not a path —
which is a bug rather than a runtime condition and is left to fail loudly in tests.

## Email goes through the outbox, never directly

§12: *"Delivery uses a transactional outbox."* `audit.publish` stages a row in the caller's
transaction, so mail is queued if and only if the work committed. A `smtp` call here would send
mail for a transaction that then rolled back, which is the one delivery mistake nobody can undo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.logging import get_logger
from uboss.modules.audit import service as audit
from uboss.modules.notifications import policy
from uboss.modules.notifications.models import (
    Category,
    Notification,
    NotificationPreference,
    NotificationSettings,
)

log = get_logger(__name__)

#: Re-exported so a call site can name a category without a second import of the models module.
#: The vocabulary belongs with the thing that raises notifications, not only with the table.
__all__ = [
    "DIGEST_EVENT",
    "EMAIL_EVENT",
    "Category",
    "Raised",
    "action_required_count",
    "approval_decided",
    "approval_requested",
    "commented",
    "mark_all_read",
    "mark_read",
    "raise_for",
    "run_failed",
    "schedule_event",
    "task_assigned",
    "unread_count",
]

#: The outbox event a single immediate notification produces. One type rather than one per
#: category, because the publisher's job is the same either way — render this line and send it —
#: and six near-identical publishers would be six places for the footer to drift.
EMAIL_EVENT = "notifications.email"

#: The digest's own event. Separate because its payload is a list rather than one line, and a
#: publisher that had to guess which shape it was given would be a publisher with a bug waiting.
DIGEST_EVENT = "notifications.digest"


@dataclass(frozen=True, slots=True)
class Raised:
    """What `raise_for` did. Returned rather than logged only, so a test can assert on it."""

    notification_id: uuid.UUID | None
    channels: frozenset[str]
    #: True when this folded into an existing unread row instead of creating one.
    deduped: bool


async def raise_for(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    category: str,
    event: str,
    title: str,
    deep_link: str,
    dedupe_key: str,
    body: str | None = None,
    actor_membership_id: uuid.UUID | None = None,
    subject_type: str = "unknown",
    subject_id: uuid.UUID | None = None,
    action_required: bool = False,
    group_key: str | None = None,
    now: datetime | None = None,
) -> Raised:
    """Tell one person one thing, according to what they have asked for.

    Returns without writing anything when their preference is `off` — a person who chose silence
    gets it, and an unread row they never wanted is not silence.

    **Never notify somebody about their own action.** The most common way a notification system
    becomes noise is telling people what they just did; the actor is compared here rather than at
    each call site, so no caller has to remember.
    """
    if actor_membership_id is not None and actor_membership_id == membership_id:
        return Raised(notification_id=None, channels=frozenset(), deduped=False)

    moment = now or datetime.now(UTC)
    chosen, settings = await _preferences(session, membership_id, category)

    channels = policy.channels_for(
        category=category,
        chosen=chosen,
        now=moment,
        quiet_hours_enabled=settings.quiet_hours_enabled if settings else False,
        quiet_from=settings.quiet_from if settings else None,
        quiet_to=settings.quiet_to if settings else None,
        timezone=settings.timezone if settings else "Asia/Kolkata",
    )
    if not channels:
        log.info(
            "notification_suppressed", category=category, notification_event=event
        )
        return Raised(notification_id=None, channels=channels, deduped=False)

    notification_id: uuid.UUID | None = None
    deduped = False
    if policy.Channel.IN_APP in channels:
        notification_id, deduped = await _insert_or_fold(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            category=category,
            event=event,
            title=title,
            body=body,
            actor_membership_id=actor_membership_id,
            subject_type=subject_type,
            subject_id=subject_id,
            deep_link=deep_link,
            action_required=action_required,
            dedupe_key=dedupe_key,
            group_key=group_key,
        )

    if policy.Channel.EMAIL_NOW in channels:
        #  Staged, not sent. The row goes with the caller's commit, so mail is queued if and only
        #  if the work that caused it actually happened.
        #
        #  **The address is resolved now and carried in the payload.** The relay worker runs on a
        #  cross-tenant credential with no grant on `users` and no tenant bound, so it cannot look
        #  a recipient up later; widening that credential to let it try is exactly what 0008
        #  warned against. If the address cannot be resolved the mail is simply not staged — the
        #  bell row still exists, so nothing is lost.
        address = await email_of(session, membership_id)
        if address is not None:
            await audit.publish(
                session,
                tenant_id=tenant_id,
                event_type=EMAIL_EVENT,
                subject_type="membership",
                subject_id=membership_id,
                payload={
                    "email": address,
                    "category": category,
                    "event": event,
                    "title": title,
                    "body": body,
                    "deep_link": deep_link,
                },
            )

    #  `event` is structlog's own key for the log message, so the notification's event name is
    #  passed as `notification_event`. Colliding with it silently loses one of the two.
    log.info(
        "notification_raised",
        category=category,
        notification_event=event,
        channels=sorted(channels),
        deduped=deduped,
    )
    return Raised(
        notification_id=notification_id, channels=channels, deduped=deduped
    )


async def _insert_or_fold(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    category: str,
    event: str,
    title: str,
    body: str | None,
    actor_membership_id: uuid.UUID | None,
    subject_type: str,
    subject_id: uuid.UUID | None,
    deep_link: str,
    action_required: bool,
    dedupe_key: str,
    group_key: str | None,
) -> tuple[uuid.UUID, bool]:
    """Write the bell row, or fold into the unread one that is already there.

    One statement. `ON CONFLICT` names the partial index's predicate so it matches only unread
    rows — a repeat of something already read starts a new line, which is the whole reason the
    index is partial.

    `occurrences` is what turns five overnight failures into *"failed 5 times, last at 04:00"*.
    The title is refreshed too: the newest wording is the accurate one when a fact has moved on.
    """
    row = (
        await session.execute(
            text(
                """
                INSERT INTO notifications
                    (tenant_id, membership_id, category, event, title, body,
                     actor_membership_id, subject_type, subject_id, deep_link,
                     action_required, dedupe_key, group_key)
                VALUES
                    (:tenant, :membership, :category, :event, :title, :body,
                     :actor, :subject_type, :subject_id, :deep_link,
                     :action_required, :dedupe_key, :group_key)
                ON CONFLICT (membership_id, dedupe_key) WHERE read_at IS NULL
                DO UPDATE SET
                    occurrences = notifications.occurrences + 1,
                    last_at = now(),
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    action_required = notifications.action_required
                                      OR EXCLUDED.action_required
                RETURNING id, occurrences
                """
            ),
            {
                "tenant": tenant_id,
                "membership": membership_id,
                "category": category,
                "event": event,
                "title": title[:300],
                "body": body,
                "actor": actor_membership_id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "deep_link": deep_link[:500],
                "action_required": action_required,
                "dedupe_key": dedupe_key[:200],
                "group_key": group_key[:200] if group_key else None,
            },
        )
    ).one()
    return row.id, row.occurrences > 1


async def email_of(
    session: AsyncSession, membership_id: uuid.UUID
) -> str | None:
    """Where to write to, resolved while the tenant is still bound.

    Through `credentials.find_by_id`, because `uboss_app` has no privilege on `users` — migration
    0006 took it away and the reason has not changed. `None` when the membership or the account
    has gone, which is a state to skip rather than to fail on.
    """
    from uboss.modules.identity import credentials
    from uboss.modules.identity.models import Membership

    user_id = (
        await session.execute(
            select(Membership.user_id).where(Membership.id == membership_id)
        )
    ).scalar_one_or_none()
    if user_id is None:
        return None
    found = await credentials.find_by_id(session, user_id)
    return found.email if found is not None else None


async def _preferences(
    session: AsyncSession, membership_id: uuid.UUID, category: str
) -> tuple[policy.Preference | None, NotificationSettings | None]:
    """This person's choice for this category, and their quiet hours. Both may be absent.

    Absent is not a failure and not a default row waiting to be created — it means they have
    never decided, and `policy.preference_for` answers for them.
    """
    chosen = (
        await session.execute(
            select(NotificationPreference).where(
                NotificationPreference.membership_id == membership_id,
                NotificationPreference.category == category,
            )
        )
    ).scalar_one_or_none()
    settings = (
        await session.execute(
            select(NotificationSettings).where(
                NotificationSettings.membership_id == membership_id
            )
        )
    ).scalar_one_or_none()

    preference = (
        policy.Preference(
            in_app=chosen.in_app, email=chosen.email, delivery=chosen.delivery
        )
        if chosen is not None
        else None
    )
    return preference, settings


# ── reading the bell ─────────────────────────────────────────────────────────────────────


async def unread_count(session: AsyncSession, membership_id: uuid.UUID) -> int:
    """What the bell shows. Unread, mine — never a number derived from the page on screen."""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.membership_id == membership_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def action_required_count(
    session: AsyncSession, membership_id: uuid.UUID
) -> int:
    """§12's third tab. Unread *and* needing something done."""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.membership_id == membership_id,
                    Notification.read_at.is_(None),
                    Notification.action_required.is_(True),
                )
            )
        ).scalar_one()
    )


async def mark_read(
    session: AsyncSession, membership_id: uuid.UUID, notification_id: uuid.UUID
) -> bool:
    """Mark one as read. Returns whether it changed anything.

    Scoped to the reader by the statement, not by a prior lookup: a route that fetched the row
    and then updated it would be a route with a window between the two.
    """
    result = await session.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.membership_id == membership_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
        #  `RETURNING` rather than `rowcount`: the async result object does not expose a row
        #  count, and counting what came back is the same answer without a driver detail in it.
        .returning(Notification.id)
    )
    return len(result.all()) > 0


async def mark_all_read(session: AsyncSession, membership_id: uuid.UUID) -> int:
    """Clear the bell. Returns how many were marked."""
    result = await session.execute(
        update(Notification)
        .where(
            Notification.membership_id == membership_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
        .returning(Notification.id)
    )
    return len(result.all())


# ── the six categories, as the rest of the product calls them ────────────────────────────


async def task_assigned(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    title: str,
    kind: str,
    actor_membership_id: uuid.UUID | None = None,
) -> Raised:
    """Somebody has work. Named rather than raised inline so the wording exists once.

    Grouped by run: nine tasks from one run are nine things a person may act on individually,
    shown under one heading. Deduped by task, because being told twice about one task is noise.
    """
    return await raise_for(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        category=(
            Category.APPROVAL_INPUT
            if kind in {"approval", "input"}
            else Category.TASK_ASSIGNMENT
        ),
        event=f"task.{kind}_assigned",
        title=title,
        body=None,
        deep_link=f"/todo?task={task_id}",
        dedupe_key=f"task:{task_id}",
        group_key=f"run:{run_id}",
        subject_type="task",
        subject_id=task_id,
        actor_membership_id=actor_membership_id,
        #: Every assigned task needs doing. That is what being assigned one means.
        action_required=True,
    )


async def approval_requested(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    approval_id: uuid.UUID,
    task_id: uuid.UUID,
    question: str | None,
    requested_by: uuid.UUID | None,
) -> Raised:
    return await raise_for(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        category=Category.APPROVAL_INPUT,
        event="approval.requested",
        title="A decision is waiting on you",
        body=question,
        deep_link=f"/todo?tab=approvals&task={task_id}",
        dedupe_key=f"approval:{approval_id}",
        subject_type="approval",
        subject_id=approval_id,
        actor_membership_id=requested_by,
        action_required=True,
    )


async def approval_decided(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    approval_id: uuid.UUID,
    task_id: uuid.UUID,
    state: str,
    reason: str | None,
    decided_by: uuid.UUID,
) -> Raised:
    """The person who asked, told what was decided.

    Not `action_required`: it is a report. A rejection may well cause work, but *what* work is a
    judgement this code cannot make, and a tab that filled up with things needing no action is a
    tab people stop opening.
    """
    return await raise_for(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        category=Category.APPROVAL_INPUT,
        event=f"approval.{state}",
        title=f"Your request was {state.replace('_', ' ')}",
        body=reason,
        deep_link=f"/todo?task={task_id}",
        dedupe_key=f"approval-decided:{approval_id}",
        subject_type="approval",
        subject_id=approval_id,
        actor_membership_id=decided_by,
    )


async def run_failed(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    run_id: uuid.UUID,
    job_id: uuid.UUID,
    job_name: str,
    detail: str,
) -> Raised:
    """A run failed. Deduped **by job, not by run** — and that is the interesting choice.

    A schedule failing every hour produces one line that says it has now failed twelve times,
    rather than twelve identical lines. The run id is in the deep link, so the newest failure is
    still one click away; what is suppressed is the repetition, not the information.
    """
    return await raise_for(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        category=Category.AGENT_RESULT,
        event="run.failed",
        title=f"{job_name} failed",
        body=detail[:1000],
        deep_link=f"/todo?run={run_id}",
        dedupe_key=f"run-failed:{job_id}",
        group_key=f"job:{job_id}",
        subject_type="run",
        subject_id=run_id,
        action_required=True,
    )


async def schedule_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    job_id: uuid.UUID,
    job_name: str,
    event: str,
    title: str,
    body: str | None,
    action_required: bool = False,
) -> Raised:
    """A schedule did something worth saying — skipped, held for approval, could not run.

    No actor: nobody did this. `raise_for` takes `None` and the row says so, rather than naming
    whoever configured the schedule months ago.
    """
    return await raise_for(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        category=Category.SCHEDULE_LIFECYCLE,
        event=event,
        title=title,
        body=body,
        deep_link=f"/job-builder/{job_id}",
        dedupe_key=f"schedule:{job_id}:{event}",
        group_key=f"job:{job_id}",
        subject_type="job",
        subject_id=job_id,
        action_required=action_required,
    )


async def commented(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    task_id: uuid.UUID,
    author_membership_id: uuid.UUID,
    author_name: str,
    excerpt: str,
) -> Raised:
    """Somebody said something on a task this person holds or follows.

    Deduped by task *and* author, so a conversation is one line per person rather than one per
    sentence; `occurrences` then reads as "3 comments".
    """
    return await raise_for(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        category=Category.MENTION_COMMENT,
        event="task.commented",
        title=f"{author_name} commented",
        body=excerpt[:500],
        deep_link=f"/todo?task={task_id}",
        dedupe_key=f"comment:{task_id}:{author_membership_id}",
        group_key=f"task:{task_id}",
        subject_type="task",
        subject_id=task_id,
        actor_membership_id=author_membership_id,
    )
