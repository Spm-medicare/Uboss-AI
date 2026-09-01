"""What the privacy routes accept and return.

Two audiences, and the shapes say which is which. A **person** reads their own consent history and
their own requests; an **administrator** reads the register, the notices, the holds and everybody's
requests. The read models carry no `compliant` flag and no score, because §9 forbids the badge:
*"Show control status, evidence, gap, owner and review date."*
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.privacy.models import (
    ConsentState,
    NoticeState,
    ProcessingBasis,
    ProcessingRole,
    RequestDecision,
    RequestKind,
    RequestState,
)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── §2 the register ────────────────────────────────────────────────────────────────────────


class ActivityCreate(_Payload):
    """Six required fields, because a row without them answers nothing.

    `basis` has no default here either. A schema that defaulted it would put the manufactured
    consent one layer further from the service that refuses it.
    """

    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=8000)
    accountable_role: ProcessingRole
    basis: ProcessingBasis
    principal_category: str = Field(min_length=1, max_length=200)
    data_categories: str = Field(min_length=1, max_length=8000)

    source: str | None = Field(default=None, max_length=4000)
    recipients: str | None = Field(default=None, max_length=4000)
    ai_access: bool = False
    region: str | None = Field(default=None, max_length=120)
    transfer_rule: str | None = Field(default=None, max_length=4000)
    retention_summary: str | None = Field(default=None, max_length=4000)
    deletion_path: str | None = Field(default=None, max_length=4000)
    owner_membership_id: uuid.UUID | None = None
    effective_from: date | None = None
    review_due: date | None = None
    evidence_note: str | None = Field(default=None, max_length=4000)


class ActivityUpdate(_Payload):
    """Every field optional; a field left out is left alone."""

    expected_version: int

    name: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = Field(default=None, min_length=1, max_length=8000)
    accountable_role: ProcessingRole | None = None
    basis: ProcessingBasis | None = None
    principal_category: str | None = Field(default=None, min_length=1, max_length=200)
    data_categories: str | None = Field(default=None, min_length=1, max_length=8000)
    source: str | None = Field(default=None, max_length=4000)
    recipients: str | None = Field(default=None, max_length=4000)
    ai_access: bool | None = None
    region: str | None = Field(default=None, max_length=120)
    transfer_rule: str | None = Field(default=None, max_length=4000)
    retention_summary: str | None = Field(default=None, max_length=4000)
    deletion_path: str | None = Field(default=None, max_length=4000)
    effective_from: date | None = None
    review_due: date | None = None
    evidence_note: str | None = Field(default=None, max_length=4000)


class ActivityRead(BaseModel):
    id: uuid.UUID
    name: str
    purpose: str
    accountable_role: ProcessingRole
    basis: ProcessingBasis
    principal_category: str
    data_categories: str
    source: str | None
    recipients: str | None
    ai_access: bool
    region: str | None
    transfer_rule: str | None
    retention_summary: str | None
    deletion_path: str | None
    owner_name: str | None
    effective_from: date | None
    review_due: date | None
    evidence_note: str | None
    archived_at: datetime | None
    version: int
    updated_at: datetime


# ── §3 notices ─────────────────────────────────────────────────────────────────────────────


class NoticeCreate(_Payload):
    name: str = Field(min_length=1, max_length=200)
    processing_activity_id: uuid.UUID | None = None


class NoticeVersionWrite(_Payload):
    """§3's itemised content. Every required field is one the contract itemises."""

    language: str = Field(default="en", min_length=2, max_length=16)
    body: str = Field(min_length=1, max_length=40000)
    data_items: str = Field(min_length=1, max_length=8000)
    purpose: str = Field(min_length=1, max_length=8000)
    basis: ProcessingBasis
    rights_route: str = Field(min_length=1, max_length=4000)
    privacy_contact: str = Field(min_length=1, max_length=300)
    recipients: str | None = Field(default=None, max_length=4000)
    retention_summary: str | None = Field(default=None, max_length=4000)


class NoticeVersionRead(BaseModel):
    id: uuid.UUID
    notice_id: uuid.UUID
    version_no: int
    language: str
    state: NoticeState
    body: str
    data_items: str
    purpose: str
    basis: ProcessingBasis
    recipients: str | None
    retention_summary: str | None
    rights_route: str
    privacy_contact: str
    author_name: str | None
    reviewed_by_name: str | None
    effective_from: datetime | None
    retired_at: datetime | None
    created_at: datetime


class NoticeRead(BaseModel):
    id: uuid.UUID
    name: str
    processing_activity_id: uuid.UUID | None
    version: int
    versions: list[NoticeVersionRead]


# ── §3 consent ─────────────────────────────────────────────────────────────────────────────


class ConsentGrant(_Payload):
    """What proves it is required. §3: *"affirmative evidence, channel, language"*."""

    notice_version_id: uuid.UUID
    purpose: str = Field(default="", max_length=8000)
    channel: str = Field(min_length=1, max_length=60)
    evidence: str = Field(min_length=1, max_length=4000)
    membership_id: uuid.UUID | None = None
    principal_email: str | None = Field(default=None, max_length=320)
    processing_activity_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class ConsentWithdraw(_Payload):
    channel: str = Field(min_length=1, max_length=60)
    evidence: str = Field(min_length=1, max_length=4000)


class ConsentRead(BaseModel):
    id: uuid.UUID
    state: ConsentState
    purpose: str
    channel: str
    evidence: str
    language: str
    notice_version_id: uuid.UUID
    withdraws_id: uuid.UUID | None
    expires_at: datetime | None
    occurred_at: datetime
    recorded_by_name: str | None


# ── §5 legal holds ─────────────────────────────────────────────────────────────────────────


class HoldCreate(_Payload):
    name: str = Field(min_length=1, max_length=200)
    scope: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)
    authority: str = Field(min_length=1, max_length=300)


class HoldRelease(_Payload):
    expected_version: int
    reason: str = Field(min_length=1, max_length=4000)


class HoldRead(BaseModel):
    id: uuid.UUID
    name: str
    scope: str
    reason: str
    authority: str
    placed_by_name: str | None
    placed_at: datetime
    released_at: datetime | None
    released_by_name: str | None
    release_reason: str | None
    version: int


# ── §4 requests ────────────────────────────────────────────────────────────────────────────


class RequestSubmit(_Payload):
    """`due_at` comes from the caller, which means from the approved register.

    Nothing computes a statutory deadline: §4 takes the SLA from *"the approved effective-date
    register"* and DR-011 is still open.
    """

    kind: RequestKind
    details: str = Field(min_length=1, max_length=8000)
    principal_email: str | None = Field(default=None, max_length=320)
    on_behalf_of_membership_id: uuid.UUID | None = None
    due_at: datetime | None = None


class IdentityCheck(_Payload):
    expected_version: int
    how: str = Field(min_length=1, max_length=4000)


class Acknowledge(_Payload):
    expected_version: int
    assigned_to_membership_id: uuid.UUID | None = None
    due_at: datetime | None = None


class DiscoveryNote(_Payload):
    expected_version: int
    found: str = Field(min_length=1, max_length=8000)


class ExemptionReview(_Payload):
    expected_version: int
    note: str = Field(min_length=1, max_length=8000)
    legal_hold_id: uuid.UUID | None = None


class Decide(_Payload):
    expected_version: int
    decision: RequestDecision
    reason: str = Field(min_length=1, max_length=8000)


class DeliveryNote(_Payload):
    expected_version: int
    note: str = Field(min_length=1, max_length=4000)


class CloseRequest(_Payload):
    expected_version: int
    note: str = Field(default="", max_length=4000)


class EscalateRequest(_Payload):
    expected_version: int
    reason: str = Field(min_length=1, max_length=4000)


class ActionRead(BaseModel):
    id: uuid.UUID
    kind: str
    detail: str
    actor_name: str | None
    occurred_at: datetime


class RequestRead(BaseModel):
    id: uuid.UUID
    reference: str
    kind: RequestKind
    state: RequestState
    principal_email: str
    details: str
    requested_by_name: str | None
    identity_check: str | None
    verified_at: datetime | None
    assigned_to_name: str | None
    due_at: datetime | None
    decision: RequestDecision | None
    decision_reason: str | None
    decided_by_name: str | None
    decided_at: datetime | None
    legal_hold_id: uuid.UUID | None
    exemption_note: str | None
    delivery_note: str | None
    delivered_at: datetime | None
    closed_at: datetime | None
    version: int
    created_at: datetime


class RequestDetail(RequestRead):
    """One request with its trail — §4's evidence, in order."""

    trail: list[ActionRead]
