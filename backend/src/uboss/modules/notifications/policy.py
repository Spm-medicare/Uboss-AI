"""What to do with one notification for one person — the decisions, with no I/O.

Pure functions over plain values. Every rule §12 asks for that involves a *judgement* lives here
rather than inside the service, for the reason the runtime keeps the same split: quiet hours
across midnight, a digest window, a default nobody has chosen yet — these are testable by calling
a function, and a rule that only existed inside a database transaction would be a rule provable
only by writing rows.

## Defaults are here, not in the schema

A person with no preference row has never decided, and this is what they get until they do. The
alternative — writing six rows for every new member — is six rows to migrate whenever a category
is added, and a stored `false` nobody chose is indistinguishable from one they did.

The defaults are deliberately conservative about email and generous about the bell. In-app costs
a person nothing to ignore; email arrives whether or not they are working. So everything shows in
the bell, and only the two categories that mean *somebody is waiting on you* — a task, an
approval — mail by default.

## Quiet hours suppress email, never the bell

An in-app notification is not an interruption; it is a list that is there when somebody looks.
Quiet hours are about not being *reached*, so they hold back mail and let the bell fill up
normally. A bell that also went quiet would hide work that arrived overnight, which is precisely
what somebody checks the bell for in the morning.

**Security is never quiet.** *"Somebody signed in from a new device"* at 2 a.m. is the one thing
whose whole value is arriving at 2 a.m., and a preference that could silence it would be a
preference that helps an attacker.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from uboss.modules.notifications.models import Category, Delivery


@dataclass(frozen=True, slots=True)
class Preference:
    """One person's answer for one category, defaulted where they have not given one."""

    in_app: bool
    email: bool
    delivery: str


#: What somebody gets before they choose anything. Email only where the category means a person
#: is waiting on them; the bell for everything, because a list nobody has to read costs nothing.
DEFAULTS: dict[str, Preference] = {
    Category.TASK_ASSIGNMENT: Preference(
        in_app=True, email=True, delivery=Delivery.IMMEDIATE
    ),
    Category.APPROVAL_INPUT: Preference(
        in_app=True, email=True, delivery=Delivery.IMMEDIATE
    ),
    Category.AGENT_RESULT: Preference(
        in_app=True, email=False, delivery=Delivery.IMMEDIATE
    ),
    Category.SCHEDULE_LIFECYCLE: Preference(
        in_app=True, email=False, delivery=Delivery.DIGEST
    ),
    Category.MENTION_COMMENT: Preference(
        in_app=True, email=False, delivery=Delivery.IMMEDIATE
    ),
    #: Immediate and by mail, and not because it is urgent to the product — because it is urgent
    #: to the person. A sign-in they did not make is worth waking somebody for.
    Category.SECURITY_ADMIN: Preference(
        in_app=True, email=True, delivery=Delivery.IMMEDIATE
    ),
}

#: The one category quiet hours may not silence. Its whole value is arriving at the moment it is
#: least convenient.
NEVER_QUIET = frozenset({Category.SECURITY_ADMIN})


class Channel(enum.StrEnum):
    """Where one notification is going, once every rule has been applied."""

    #: Written to `notifications` — the bell.
    IN_APP = "in_app"
    #: Staged on the outbox now.
    EMAIL_NOW = "email_now"
    #: Left for the digest to collect.
    EMAIL_DIGEST = "email_digest"


def preference_for(
    category: str, chosen: Preference | None
) -> Preference:
    """What this person gets for this category. Their choice, or the default."""
    if chosen is not None:
        return chosen
    #: An unknown category is not silently dropped — it goes to the bell and nowhere else. A
    #: category added in code before it is added here should be visible, not invisible.
    return DEFAULTS.get(
        category, Preference(in_app=True, email=False, delivery=Delivery.IMMEDIATE)
    )


def channels_for(
    *,
    category: str,
    chosen: Preference | None,
    now: datetime,
    quiet_hours_enabled: bool,
    quiet_from: time | None,
    quiet_to: time | None,
    timezone: str,
) -> frozenset[str]:
    """Every channel this notification should take. Possibly none.

    `OFF` means off: no bell, no mail. A person who chose silence gets it, and the notification is
    simply not raised — which is why this can legitimately return nothing.
    """
    preference = preference_for(category, chosen)
    if preference.delivery == Delivery.OFF:
        return frozenset()

    taking: set[str] = set()
    if preference.in_app:
        taking.add(Channel.IN_APP)

    if preference.email:
        quiet = category not in NEVER_QUIET and is_quiet(
            now,
            enabled=quiet_hours_enabled,
            start=quiet_from,
            end=quiet_to,
            timezone=timezone,
        )
        if preference.delivery == Delivery.DIGEST or quiet:
            #  Quiet hours do not cancel mail; they defer it. The digest is what "I will read it
            #  in the morning" looks like, and dropping it instead would lose the message.
            taking.add(Channel.EMAIL_DIGEST)
        else:
            taking.add(Channel.EMAIL_NOW)

    return frozenset(taking)


def is_quiet(
    now: datetime,
    *,
    enabled: bool,
    start: time | None,
    end: time | None,
    timezone: str,
) -> bool:
    """Whether `now` falls inside somebody's quiet hours, in their own timezone.

    **The window usually crosses midnight**, and that is the case a naive `start <= t <= end`
    gets exactly backwards: 22:00 to 07:00 would then match nothing at all, and the feature would
    appear to be off rather than broken. So a window whose end is before its start is read as
    spanning midnight, which is what a person means when they type those two times.
    """
    if not enabled or start is None or end is None:
        return False
    if start == end:
        #  A zero-length window. Read as "no quiet hours" rather than "always quiet": the
        #  alternative silences somebody's mail forever because two fields happened to match.
        return False

    try:
        local = now.astimezone(ZoneInfo(timezone))
    except (ZoneInfoNotFoundError, ValueError):
        #  An unknown zone must not silence anything. Failing open on *delivery* is the safe
        #  direction — the failure a person notices is mail that did not arrive.
        return False

    at = local.timetz().replace(tzinfo=None)
    if start < end:
        return start <= at < end
    #  Crosses midnight: 22:00 to 07:00 is "at or after 22:00, or before 07:00".
    return at >= start or at < end


def digest_is_due(
    now: datetime,
    *,
    digest_hour: int,
    timezone: str,
    last_digest_at: datetime | None,
) -> bool:
    """Whether this person's digest hour has arrived and today's has not been sent.

    Guarded by `last_digest_at` rather than by a timer: a worker that ticks every few minutes
    would otherwise send a digest on each tick within the hour, and a restarted worker would send
    another. Comparing against the last one makes the answer the same however often it is asked.
    """
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return False

    local = now.astimezone(zone)
    if local.hour < digest_hour:
        return False
    if last_digest_at is None:
        #  Never sent. Due, but only for today's window — not for every day since they joined.
        return True
    return last_digest_at.astimezone(zone).date() < local.date()
