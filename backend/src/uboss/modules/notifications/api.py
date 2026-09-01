"""The bell — §12's drawer, and the preferences behind it.

**There is no `POST /notifications`.** A notification exists because something happened that the
product decided was worth telling somebody. A route that created one would be a way to put a line
in another person's bell with nothing behind it.

## Everything is scoped to the caller by the query

Not by the screen, and not by a filter the frontend applies. Every statement here carries
`membership_id == context.membership_id`, so a query parameter cannot widen it. A bell is theirs;
is deliberately no route to read somebody else's, not even for an administrator — that is what the
audit trail is for.

## Preferences have no `GET` that invents rows

`GET /notifications/preferences` returns what a person has actually chosen, merged with the
defaults from `policy.py` and labelled: `chosen` says whether this line is theirs or the product's.
The screen can then show "using the default" honestly rather than presenting a default as a
decision somebody made.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.errors import ValidationFailed
from uboss.core.idempotency import require_idempotency_key
from uboss.core.logging import get_logger
from uboss.core.permissions import Action
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership
from uboss.modules.notifications import policy, service
from uboss.modules.notifications.models import (
    Category,
    Delivery,
    Notification,
    NotificationPreference,
    NotificationSettings,
)

log = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])

#: §12's three tabs: *"All, Unread and Action required"*.
Tab = Literal["all", "unread", "action_required"]


class BellNotification(BaseModel):
    """One line in the drawer.

    Named for the bell rather than `NotificationRead`, because §10's supervisor configuration
    already has a `NotificationRead` and two schemas with one name make FastAPI fully-qualify
    both — which turns every generated type into a path. `test_contract` refuses that, and it
    was right to.
    """

    id: uuid.UUID
    category: str
    event: str
    title: str
    body: str | None = None
    deep_link: str
    action_required: bool
    #: How many times this same fact has happened. 1 for most; higher when repeats folded in,
    #: which is what turns five overnight failures into one line that says five.
    occurrences: int
    group_key: str | None = None
    actor_name: str | None = None
    created_at: str
    last_at: str
    read_at: str | None = None


class NotificationCounts(BaseModel):
    """What the bell badge reads. Two numbers, and neither is derived from the page on screen."""

    unread: int
    action_required: int


class PreferenceRead(BaseModel):
    category: str
    in_app: bool
    email: bool
    delivery: str
    #: False when this line is the product's default rather than something the person chose. The
    #: screen says so instead of presenting a default as a decision.
    chosen: bool


class PreferenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    in_app: bool
    email: bool
    delivery: str


class SettingsRead(BaseModel):
    quiet_hours_enabled: bool
    quiet_from: str | None = None
    quiet_to: str | None = None
    timezone: str
    digest_hour: int


class SettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quiet_hours_enabled: bool
    #: `HH:MM`. Required when quiet hours are on — enforced here and by a check constraint.
    quiet_from: str | None = None
    quiet_to: str | None = None
    timezone: str = Field(min_length=1, max_length=64)
    digest_hour: int = Field(ge=0, le=23)


# ── the drawer ───────────────────────────────────────────────────────────────────────────


@router.get("/counts", summary="What the bell shows")
async def counts(session: SessionDep, context: CurrentContext) -> NotificationCounts:
    await guard.authorise(session, context, Action.VIEW)
    return NotificationCounts(
        unread=await service.unread_count(session, context.membership_id),
        action_required=await service.action_required_count(
            session, context.membership_id
        ),
    )


@router.get("", summary="§12's drawer — All, Unread, Action required")
async def list_notifications(
    session: SessionDep,
    context: CurrentContext,
    tab: Tab = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[BellNotification]:
    """Newest activity first — ordered by `last_at`, not `created_at`.

    A fact that recurred an hour ago belongs at the top even if it first happened yesterday;
    ordering by creation would bury the thing that just went wrong under things that did not.
    """
    await guard.authorise(session, context, Action.VIEW)

    query = (
        select(Notification)
        .where(Notification.membership_id == context.membership_id)
        .order_by(Notification.last_at.desc())
        .limit(limit)
    )
    if tab == "unread":
        query = query.where(Notification.read_at.is_(None))
    elif tab == "action_required":
        query = query.where(
            Notification.read_at.is_(None), Notification.action_required.is_(True)
        )

    rows = list((await session.execute(query)).scalars().all())
    names = await _names(session, [row.actor_membership_id for row in rows])
    return [
        BellNotification(
            id=row.id,
            category=row.category,
            event=row.event,
            title=row.title,
            body=row.body,
            deep_link=row.deep_link,
            action_required=row.action_required,
            occurrences=row.occurrences,
            group_key=row.group_key,
            actor_name=(
                names.get(row.actor_membership_id)
                if row.actor_membership_id is not None
                else None
            ),
            created_at=row.created_at.isoformat(),
            last_at=row.last_at.isoformat(),
            read_at=row.read_at.isoformat() if row.read_at else None,
        )
        for row in rows
    ]


@router.post("/{notification_id}/read", status_code=204, summary="Mark one as read")
async def mark_read(
    notification_id: uuid.UUID,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> None:
    """Reading twice is not a conflict, so an already-read one is not an error.

    The statement is scoped to the caller, so this is also how "not mine" is refused — without a
    lookup that would tell somebody whether the id exists.
    """
    await guard.authorise(session, context, Action.VIEW)
    await service.mark_read(session, context.membership_id, notification_id)
    await session.commit()


@router.post("/read-all", status_code=204, summary="Clear the bell")
async def mark_all_read(
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> None:
    await guard.authorise(session, context, Action.VIEW)
    await service.mark_all_read(session, context.membership_id)
    await session.commit()


# ── preferences ──────────────────────────────────────────────────────────────────────────


@router.get("/preferences", summary="What I have asked to be told about")
async def read_preferences(
    session: SessionDep, context: CurrentContext
) -> list[PreferenceRead]:
    """All six categories, always — chosen ones and defaults, each labelled.

    Returning only the rows that exist would make a screen guess at the rest, and a screen that
    guesses is a screen that shows somebody a setting they never made.
    """
    await guard.authorise(session, context, Action.VIEW)
    rows = {
        row.category: row
        for row in (
            await session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.membership_id == context.membership_id
                )
            )
        )
        .scalars()
        .all()
    }
    answer: list[PreferenceRead] = []
    for category in Category:
        row = rows.get(category)
        if row is not None:
            answer.append(
                PreferenceRead(
                    category=category,
                    in_app=row.in_app,
                    email=row.email,
                    delivery=row.delivery,
                    chosen=True,
                )
            )
        else:
            default = policy.preference_for(category, None)
            answer.append(
                PreferenceRead(
                    category=category,
                    in_app=default.in_app,
                    email=default.email,
                    delivery=default.delivery,
                    chosen=False,
                )
            )
    return answer


@router.put("/preferences", summary="Choose what to be told about")
async def write_preference(
    body: PreferenceWrite,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> PreferenceRead:
    await guard.authorise(session, context, Action.VIEW)
    if body.category not in set(Category):
        raise ValidationFailed(f"'{body.category}' is not a notification category.")
    if body.delivery not in set(Delivery):
        raise ValidationFailed(f"'{body.delivery}' is not a delivery choice.")

    row = (
        await session.execute(
            select(NotificationPreference).where(
                NotificationPreference.membership_id == context.membership_id,
                NotificationPreference.category == body.category,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = NotificationPreference(
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            category=body.category,
        )
        session.add(row)
    row.in_app = body.in_app
    row.email = body.email
    row.delivery = body.delivery
    row.updated_at = datetime.now(UTC)

    await session.commit()
    return PreferenceRead(
        category=body.category,
        in_app=body.in_app,
        email=body.email,
        delivery=body.delivery,
        chosen=True,
    )


@router.get("/settings", summary="Quiet hours and the digest hour")
async def read_settings(
    session: SessionDep, context: CurrentContext
) -> SettingsRead:
    """The defaults when nothing has been chosen. No row is created by reading.

    **The default timezone is the person's own**, not a constant. It was `Asia/Kolkata` for
    everybody, so a person in Dubai who had never opened this screen was told their digest would
    arrive on Kolkata's clock — and the Settings screen showed them one zone in their profile and
    another here. The membership owns a person's timezone (`PATCH /auth/me`), and this reads it.
    """
    await guard.authorise(session, context, Action.VIEW)
    row = await _settings(session, context.membership_id)
    if row is None:
        membership = await session.get(Membership, context.membership_id)
        return SettingsRead(
            quiet_hours_enabled=False,
            quiet_from=None,
            quiet_to=None,
            timezone=(
                membership.timezone
                if membership and membership.timezone
                else "Asia/Kolkata"
            ),
            digest_hour=9,
        )
    return SettingsRead(
        quiet_hours_enabled=row.quiet_hours_enabled,
        quiet_from=row.quiet_from.isoformat()[:5] if row.quiet_from else None,
        quiet_to=row.quiet_to.isoformat()[:5] if row.quiet_to else None,
        timezone=row.timezone,
        digest_hour=row.digest_hour,
    )


@router.put("/settings", summary="Set quiet hours and the digest hour")
async def write_settings(
    body: SettingsWrite,
    session: SessionDep,
    context: CurrentContext,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SettingsRead:
    await guard.authorise(session, context, Action.VIEW)
    if body.quiet_hours_enabled and (not body.quiet_from or not body.quiet_to):
        raise ValidationFailed(
            "Quiet hours need a start and an end. Say when you do not want to be reached."
        )

    row = await _settings(session, context.membership_id)
    if row is None:
        row = NotificationSettings(
            tenant_id=context.tenant_id, membership_id=context.membership_id
        )
        session.add(row)

    row.quiet_hours_enabled = body.quiet_hours_enabled
    row.quiet_from = _time(body.quiet_from)
    row.quiet_to = _time(body.quiet_to)
    row.timezone = body.timezone
    row.digest_hour = body.digest_hour
    row.updated_at = datetime.now(UTC)

    await session.commit()
    return SettingsRead(
        quiet_hours_enabled=body.quiet_hours_enabled,
        quiet_from=body.quiet_from,
        quiet_to=body.quiet_to,
        timezone=body.timezone,
        digest_hour=body.digest_hour,
    )


# ── internals ────────────────────────────────────────────────────────────────────────────


async def _settings(
    session: AsyncSession, membership_id: uuid.UUID
) -> NotificationSettings | None:
    return (
        await session.execute(
            select(NotificationSettings).where(
                NotificationSettings.membership_id == membership_id
            )
        )
    ).scalar_one_or_none()


def _time(value: str | None) -> time | None:
    """`HH:MM` as a local time, or nothing.

    Rejected with a sentence rather than a 500: this arrives from a form field, and a person who
    typed something odd should be told what is expected.
    """
    if not value:
        return None
    try:
        hour, minute = value.split(":")[:2]
        return time(int(hour), int(minute))
    except (ValueError, IndexError) as bad:
        raise ValidationFailed(
            f"'{value}' is not a time. Use 24-hour HH:MM, such as 22:00."
        ) from bad


async def _names(
    session: AsyncSession, ids: list[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    wanted = [value for value in ids if value is not None]
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(Membership.id, Membership.display_name).where(
                Membership.id.in_(wanted)
            )
        )
    ).all()
    return {row[0]: row[1] for row in rows}
