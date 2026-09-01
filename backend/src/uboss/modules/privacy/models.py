"""The privacy lifecycle's tables — §19.1 and `docs/security/PRIVACY_COMPLIANCE.md` §2 to §5.

Five families, and each one exists because the contract asks a question a boolean cannot answer:

* `ProcessingActivity` — what is processed, for what purpose, on what basis, by whom, where, for how
  long. §2's register.
* `PrivacyNotice` / `PrivacyNoticeVersion` — what people were told, in the words that were in force
  at the time. Versioned, independently reviewed, and frozen once effective.
* `ConsentRecord` — evidence of a grant or a withdrawal. Append-only, because a consent nobody can
  reconstruct is a consent that cannot be relied on.
* `LegalHold` — why something must be kept, on whose authority.
* `DataPrincipalRequest` / `RequestAction` — §4's lifecycle and every step of it.

**Nothing here decides what the law requires.** Every statutory judgement — which basis applies, how
long a response may take, whether an exemption is available — is a value somebody records, not a
constant in code. `PLAN.md` §19.1: *"Never claim legal compliance from code or tests alone."*
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class ProcessingRole(enum.StrEnum):
    """Who is accountable for one activity.

    §19.1: *"The approved DPA, customer instructions and data-flow inventory decide the role;
    product copy or code must not assume one universal role."* So both exist, and neither is a
    default.
    """

    DATA_FIDUCIARY = "data_fiduciary"
    DATA_PROCESSOR = "data_processor"


class ProcessingBasis(enum.StrEnum):
    """Why this processing is lawful.

    Consent is one basis among several, and §3 is explicit that the product *"must not manufacture
    consent to hide another basis"*. Which basis applies to a given activity is counsel's answer,
    recorded here; the product's job is to make recording the truth possible.
    """

    CONSENT = "consent"
    LEGITIMATE_USE = "legitimate_use"
    LEGAL_OBLIGATION = "legal_obligation"
    CONTRACT = "contract"


class NoticeState(enum.StrEnum):
    """§3: *"Draft → independent review/approval → effective/retired"*."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    EFFECTIVE = "effective"
    RETIRED = "retired"


class ConsentState(enum.StrEnum):
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


class RequestKind(enum.StrEnum):
    """§4's supported requests.

    *"access; correction, completion and update; erasure; grievance; nomination; and rights
    introduced by an enabled jurisdiction pack."* The first six are DPDP's; a seventh arrives with a
    pack, which is a change to this enum and to the register, not a free-text field.
    """

    ACCESS = "access"
    CORRECTION = "correction"
    COMPLETION = "completion"
    UPDATE = "update"
    ERASURE = "erasure"
    GRIEVANCE = "grievance"
    NOMINATION = "nomination"


class RequestState(enum.StrEnum):
    """§4's own diagram, in order.

    `ESCALATED` is a state and not a failure: §4 ends *"Close / Escalate"*, and a request nobody can
    escalate is a request that stalls silently.
    """

    SUBMITTED = "submitted"
    VERIFYING = "verifying"
    ACKNOWLEDGED = "acknowledged"
    DISCOVERING = "discovering"
    REVIEWING_EXEMPTIONS = "reviewing_exemptions"
    FULFILLED = "fulfilled"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    REJECTED = "rejected"
    CLOSED = "closed"
    ESCALATED = "escalated"

    @classmethod
    def finished(cls) -> frozenset[RequestState]:
        """The states a decision must already exist in."""
        return frozenset(
            {cls.FULFILLED, cls.PARTIALLY_FULFILLED, cls.REJECTED, cls.CLOSED}
        )


class RequestDecision(enum.StrEnum):
    """§4: *"Fulfil / Partially fulfil / Reject with approved reason"*."""

    FULFIL = "fulfil"
    PARTIALLY_FULFIL = "partially_fulfil"
    REJECT = "reject"


class ActionKind(enum.StrEnum):
    """One step of a request, for the trail.

    Named rather than free text so the trail can be read as a sequence — and so a step nobody
    thought about is a change to this list rather than a new spelling of an old one.
    """

    SUBMITTED = "submitted"
    IDENTITY_CHECKED = "identity_checked"
    ACKNOWLEDGED = "acknowledged"
    ASSIGNED = "assigned"
    DISCOVERY_STARTED = "discovery_started"
    DISCOVERY_RECORDED = "discovery_recorded"
    EXEMPTION_REVIEWED = "exemption_reviewed"
    HOLD_APPLIED = "hold_applied"
    DECIDED = "decided"
    DELIVERED = "delivered"
    CLOSED = "closed"
    ESCALATED = "escalated"
    NOTE = "note"


class ProcessingActivity(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """One processing activity, with every question §2 asks about it.

    The columns are the contract's own list. Two are worth pointing at:

    `basis` has no default, so an activity cannot come into existence claiming consent it does not
    have. And `ai_access` is a fact recorded here rather than inferred from whether a model happens
    to read the table — §8's first rule is minimisation, and minimisation you cannot state is
    minimisation you cannot check.
    """

    __tablename__ = "processing_activities"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    accountable_role: Mapped[str] = mapped_column(String(30), nullable=False)
    basis: Mapped[str] = mapped_column(String(30), nullable=False)
    principal_category: Mapped[str] = mapped_column(String(200), nullable=False)
    data_categories: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipients: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_access: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transfer_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    deletion_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "owner_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_processing_activities_owner",
            ondelete="SET NULL (owner_membership_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_processing_activities_tenant_id"),
    )


class PrivacyNotice(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """A notice as a named thing. Its wording lives in versions."""

    __tablename__ = "privacy_notices"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    processing_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "processing_activity_id"],
            ["processing_activities.tenant_id", "processing_activities.id"],
            name="fk_privacy_notices_activity",
            ondelete="SET NULL (processing_activity_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_privacy_notices_tenant_id"),
    )


class PrivacyNoticeVersion(Base, PrimaryKey, TenantOwned):
    """What a notice said, in one language, at one version.

    **The wording of an effective version cannot change.** A draft is edited freely; the moment a
    version has been in force, migration 0044's trigger refuses any change to its words. Somebody
    reading a consent record three years from now has to be able to read exactly what the person
    agreed to, and *"we updated the wording"* is the failure that makes a consent unusable.

    Reviewed by somebody other than the author, and the table refuses otherwise. §3 calls it
    *"independent review/approval"*; every publish path in this product already keeps the same rule.

    No `Timestamps` mixin: `created_at`, `effective_from` and `retired_at` are the three times that
    mean something here, and an `updated_at` on a row whose words are frozen would invite the
    question it cannot answer.
    """

    __tablename__ = "privacy_notice_versions"

    notice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")

    body: Mapped[str] = mapped_column(Text, nullable=False)
    data_items: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str] = mapped_column(String(30), nullable=False)
    recipients: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rights_route: Mapped[str] = mapped_column(Text, nullable=False)
    privacy_contact: Mapped[str] = mapped_column(String(300), nullable=False)

    author_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    reviewed_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "notice_id"],
            ["privacy_notices.tenant_id", "privacy_notices.id"],
            name="fk_privacy_notice_versions_notice",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "notice_id", "language", "version_no", name="uq_notice_versions_no"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_notice_versions_tenant_id"),
    )

    @property
    def is_editable(self) -> bool:
        """Draft or in review. After that the words are evidence."""
        return self.state in (NoticeState.DRAFT, NoticeState.IN_REVIEW)


class ConsentRecord(Base, PrimaryKey, TenantOwned):
    """One consent event — a grant, or a withdrawal of a named grant.

    Append-only in two independent ways, like every other evidence table here: a trigger refuses
    `UPDATE` and `DELETE`, and the privilege was never granted to `uboss_app`.

    A withdrawal is a *new row* pointing at the grant it withdraws, never an edit of it. §3:
    *"withdrawal is as discoverable as grant and creates immutable evidence"* — and the history of a
    decision is part of the decision.

    `principal_email` sits beside `membership_id` because a person can leave and the evidence has to
    survive them. The membership goes null when they are deleted; what they agreed to does not.
    """

    __tablename__ = "consent_records"

    membership_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    principal_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    processing_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    notice_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(60), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdraws_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    recorded_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "notice_version_id"],
            ["privacy_notice_versions.tenant_id", "privacy_notice_versions.id"],
            name="fk_consent_records_notice_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "processing_activity_id"],
            ["processing_activities.tenant_id", "processing_activities.id"],
            name="fk_consent_records_activity",
            ondelete="SET NULL (processing_activity_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_consent_records_tenant_id"),
        Index("ix_consent_records_principal", "tenant_id", "membership_id", "occurred_at"),
    )


class LegalHold(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """Why something must be kept, and on whose authority.

    §5: *"an erasure request never silently destroys records that law requires to be retained"*, and
    *"conflicting legal retention duties require an authorised decision."* A hold is that decision,
    written down: what it covers, why, who says so, and — when it ends — why it ended.

    The scope is a sentence rather than a query. A hold is read by a person deciding an erasure
    request, and a machine-readable scope nobody can explain is worse than a sentence they can act
    on. When this needs to be enforced automatically it should get a real predicate, not a guess
    parsed out of prose.
    """

    __tablename__ = "legal_holds"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    authority: Mapped[str] = mapped_column(String(300), nullable=False)
    placed_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_legal_holds_tenant_id"),)

    @property
    def is_active(self) -> bool:
        return self.released_at is None


class DataPrincipalRequest(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """One person's request about their own data — §4's whole lifecycle.

    Three rules are held by migration 0044's constraints rather than by this class, because a
    service check is one code path and a constraint is all of them:

    * a decided request names its decider and its reason;
    * **the requester is never the decider** — §4: *"Requestor cannot approve their own
      administrative decision"*;
    * a finished state cannot exist without a decision.

    `due_at` is set from the tenant's approved register and never computed here. §4 says the SLA
    comes from *"the approved effective-date register"*, DR-011 is an open decision, and a product
    that invented a statutory deadline would be making a legal claim in code.
    """

    __tablename__ = "data_principal_requests"

    #: Short, human, quotable in an email. Generated per tenant.
    reference: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="submitted")

    requested_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    principal_email: Mapped[str] = mapped_column(String(320), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)

    identity_check: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    legal_hold_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    exemption_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    delivery_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "legal_hold_id"],
            ["legal_holds.tenant_id", "legal_holds.id"],
            name="fk_data_principal_requests_hold",
            ondelete="SET NULL (legal_hold_id)",
        ),
        UniqueConstraint("tenant_id", "reference", name="uq_data_principal_requests_reference"),
        UniqueConstraint("tenant_id", "id", name="uq_data_principal_requests_tenant_id"),
        Index("ix_data_principal_requests_state", "tenant_id", "state", "due_at"),
    )

    @property
    def is_open(self) -> bool:
        return self.state not in RequestState.finished()


class RequestAction(Base, PrimaryKey, TenantOwned):
    """One step somebody took on a request. Append-only.

    §4 asks for evidence at every transition, and this is it: what happened, who did it, when, and
    the correlation id tying it to the request that caused it. The same shape as `audit_events` and
    `run_events`, for the same reason.
    """

    __tablename__ = "request_actions"

    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["data_principal_requests.tenant_id", "data_principal_requests.id"],
            name="fk_request_actions_request",
            ondelete="RESTRICT",
        ),
        Index("ix_request_actions_request", "tenant_id", "request_id", "occurred_at"),
    )
