"""The governance record: what happened, what must be published, and what must not happen twice.

Three tables that every other module writes to and none of them owns exclusively.

* **`audit_events`** — what changed, who changed it, and when. Append-only from the
  application's perspective (PLAN §30), and written in the *same transaction* as the change it
  describes. An audit row that can be committed separately from its change is an audit row that
  will eventually disagree with the data.
* **`outbox_events`** — something that must reach the outside world. Also committed with the
  business data (PLAN §28), so there is no window where the change happened and the notification
  did not, or vice versa. A relay publishes them afterwards and marks them done.
* **`idempotency_records`** — this operation already ran; here is what it returned. A retry
  after a dropped connection replays the first answer rather than performing the work again.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import PrimaryKey, TenantOwned


class AuditOutcome(enum.StrEnum):
    SUCCEEDED = "succeeded"
    #: A refused attempt is as important as a successful one. A run of `denied` rows against one
    #: resource is what an intrusion looks like from the inside.
    DENIED = "denied"
    FAILED = "failed"


class AuditEvent(Base, PrimaryKey, TenantOwned):
    """One recorded action.

    No `updated_at`, and no update path in the application: a row is written once. The database
    enforces it too — a trigger refuses UPDATE and DELETE, so "append-only" is a property of the
    table rather than a promise about the code.
    """

    __tablename__ = "audit_events"

    #: The database clock, not the application's, so events from two processes order correctly.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )

    #: A stable dotted name: `identity.session.signed_in`, `objective.version.published`.
    #: Queried and alerted on, so it must not be reworded casually.
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    #: What was acted on. `resource_id` is null for an action with no single target, such as a
    #: failed sign-in against an address that does not exist.
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )

    outcome: Mapped[str] = mapped_column(String(20), nullable=False)

    #: The membership that acted. Null for something the system did on its own — a schedule
    #: firing, a retry — and that distinction has to survive, so it is not filled with a
    #: placeholder.
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    #: Kept alongside the membership because a membership can be removed and the trail must
    #: still name someone.
    actor_label: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")

    #: Ties this row to the request and its log lines.
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    #: What changed, in a form a person can read on an audit screen. Never a raw password, token,
    #: API key or full request body — an audit trail is read by more people than the data it
    #: describes, and a secret written here has been copied somewhere new.
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    #: Set when the action was refused, naming the scope that withheld it. Written for an
    #: administrator; never returned to the person who was refused, because "the department
    #: blocked this" confirms the resource exists.
    denial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')", name="outcome_known"
        ),
        #  The two questions an audit screen actually asks: what happened to this thing, and
        #  what did this person do.
        Index("ix_audit_events_tenant_id_resource", "tenant_id", "resource_type", "resource_id"),
        Index("ix_audit_events_tenant_id_occurred_at", "tenant_id", "occurred_at"),
    )


class OutboxStatus(enum.StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    #: Exhausted its attempts. Visible rather than deleted — a silently dropped event is a
    #: notification nobody knows was never sent.
    DEAD = "dead"


class OutboxEvent(Base, PrimaryKey, TenantOwned):
    """Something that must reach the outside world, committed with the change that caused it.

    The pattern exists because two systems cannot be updated atomically. Writing the row in the
    same transaction as the business change means: if the change committed, the event exists; if
    it rolled back, the event does not. A relay then delivers it *at least once* — so every
    consumer must tolerate a duplicate.

    This is not exactly-once delivery, and it is not described as such anywhere.
    """

    __tablename__ = "outbox_events"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    #: A stable dotted name, same discipline as an audit action.
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)

    #: What it is about, so a consumer can order events per subject.
    subject_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: When the relay should next try. Backoff is written here rather than slept in the relay, so
    #: a restart does not reset every backoff to zero.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")

    #: The relay claim. `leased_until` is what releases it — a worker that dies holds nothing,
    #: and another picks the event up once the lease passes. `leased_by` names the worker for an
    #: operator looking at something stuck; it is not a lock.
    leased_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    leased_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'published', 'dead')", name="status_known"
        ),
        #  The relay's only query: what is due now. Partial, so the index stays small however
        #  many published rows accumulate behind it.
        Index(
            "ix_outbox_events_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )


class IdempotencyRecord(Base, PrimaryKey, TenantOwned):
    """This operation already ran; here is what it returned.

    Every retryable business mutation carries an `Idempotency-Key` derived from the logical
    operation. Authentication, credential and streaming endpoints use their own retry contracts.
    On a repeat, an eligible stored response is replayed instead of the work being done again.

    `request_fingerprint` is what makes it safe. The same key arriving with a *different* body
    is not a retry — it is a bug or an attack, and it is refused rather than silently answered
    with the earlier result.
    """

    __tablename__ = "idempotency_records"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    #: As supplied by the client.
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Method and path. Part of the uniqueness so the same key on two different endpoints does
    #: not collide.
    operation: Mapped[str] = mapped_column(String(200), nullable=False)

    #: SHA-256 of the canonical request body.
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Null while the first attempt is still running. A second request arriving in that window
    #: is told to retry rather than being allowed to run the operation concurrently.
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    #: Retention. Keys are kept long enough to cover any realistic retry and no longer — this is
    #: a table that would otherwise grow without bound.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "key", "operation", name="uq_idempotency_records_tenant_id_key_operation"
        ),
    )
