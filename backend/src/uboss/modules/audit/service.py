"""Writing the governance record.

Two functions, both of which take the caller's session and **do not commit**. That is the whole
point: the audit row and the change it describes are written in one transaction, so they commit
together or not at all. A helper that committed on its own would produce audit rows for changes
that were rolled back, and — worse — lose audit rows for changes that succeeded.

Same for the outbox: an event that commits with the business data cannot describe something that
did not happen.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.logging import correlation_id
from uboss.modules.audit.models import AuditEvent, AuditOutcome, OutboxEvent

#: Keys whose values are never written to an audit row, whatever a caller passes. An audit trail
#: is read by more people than the data it describes; a secret recorded here has been copied
#: somewhere new and harder to clean up.
REDACTED_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "token",
        "raw_token",
        "token_hash",
        "api_key",
        "secret",
        "authorization",
        "cookie",
        "session",
    }
)

REDACTED = "[redacted]"


def scrub(detail: dict[str, Any]) -> dict[str, Any]:
    """Remove anything that must not be written down, at any depth.

    Matching is on the key name, case-insensitively, and it is a denylist — which is worth being
    honest about: a new secret-shaped field with an unusual name would pass through. The list is
    the second line. The first is not putting secrets in `detail` in the first place.
    """
    cleaned: dict[str, Any] = {}
    for key, value in detail.items():
        if key.lower() in REDACTED_KEYS:
            cleaned[key] = REDACTED
        elif isinstance(value, dict):
            cleaned[key] = scrub(value)
        else:
            cleaned[key] = value
    return cleaned


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str,
    resource_type: str,
    outcome: AuditOutcome = AuditOutcome.SUCCEEDED,
    resource_id: uuid.UUID | None = None,
    actor: SecurityContext | None = None,
    actor_membership_id: uuid.UUID | None = None,
    actor_label: str = "",
    detail: dict[str, Any] | None = None,
    denial_reason: str | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    """Add one audit row to the caller's transaction.

    `tenant_id` is passed explicitly rather than taken from the actor, because some events have
    no actor — a schedule firing, a session expiring — and every event still belongs to a tenant.

    `actor` is the usual way to name who acted. `actor_membership_id` and `actor_label` are for
    the sign-in path, which has to record an attempt *before* a security context exists — there
    is no verified caller yet, which is precisely what the row is about.

    Nothing is committed here. The caller commits, and the audit row goes with the change.
    """
    event = AuditEvent(
        tenant_id=tenant_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        actor_membership_id=actor.membership_id if actor else actor_membership_id,
        actor_label=actor_label or (actor.display_name if actor else "system"),
        correlation_id=correlation_id.get(),
        ip_address=ip_address,
        detail=scrub(detail or {}),
        denial_reason=denial_reason,
    )
    session.add(event)
    return event


async def publish(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_type: str,
    subject_type: str,
    subject_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    delay: timedelta | None = None,
) -> OutboxEvent:
    """Queue something for the outside world, in the caller's transaction.

    Delivery is **at least once**. A relay will read this row and publish it; if publishing
    succeeds but marking the row fails, it will be published again. Every consumer must therefore
    tolerate a duplicate. Nothing in this system claims exactly-once delivery, because nothing
    in it provides exactly-once delivery.
    """
    event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=scrub(payload or {}),
        correlation_id=correlation_id.get(),
        next_attempt_at=datetime.now(UTC) + delay if delay else datetime.now(UTC),
    )
    session.add(event)
    return event
