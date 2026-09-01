"""The privacy lifecycle: what is processed, what was told to whom, and what people asked for.

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-01

`PLAN.md` §19.1 and `docs/security/PRIVACY_COMPLIANCE.md` §2 to §4. Five families, and the contract's
own instruction decides the size of this migration:

> Do not implement all future tables in Gate 1. Add only what the current slice processes while
> preserving these contracts.

The slice here is the one §9 lists first in *"Required Gate 8 evidence"*: an approved role and
data-flow inventory, a notice with consent and withdrawal where consent applies, and an
access/correction/erasure/grievance request carried through exemption and legal-hold handling.
Retention execution, breach cases and the subprocessor register follow in their own migrations, for
the same reason each builder got its own: a table added before the service that fills it is a table
whose shape nobody has tested.

## `processing_activities` — the inventory

§2's list, one row per processing activity, and every column on it is a question the register has to
answer. **`basis` is not defaulted.** DPDP allows consent and it allows certain legitimate uses; a
column defaulting to `consent` would manufacture a basis for activities that have another one, which
§3 forbids in as many words — *"the system must not manufacture consent to hide another basis."*

## `privacy_notices` and their versions

A notice is a document with a life: drafted, reviewed by somebody other than its author, made
effective, later retired. The wording that was in force when somebody's data was collected must stay
readable years later, so versions are append-only: a trigger refuses `UPDATE` and `DELETE`, and the
privilege is withheld from `uboss_app` as well.

`language` is on the version rather than the notice, because §3 requires *"language variants"* and a
Hindi translation of the same notice is the same notice.

## `consent_records` — evidence, not a flag

A boolean on a person would answer *"do they consent"* and nothing else. §3 asks for the principal,
the purpose, the notice version, affirmative evidence, the channel, the language, the time and the
state — because a consent nobody can reconstruct is a consent that cannot be relied on. Withdrawal
writes its own row rather than editing the grant: *"withdrawal … creates immutable evidence"*, and
the history of a decision is part of the decision.

## `data_principal_requests` — §4's lifecycle, with its refusals

The states are §4's own diagram. Three rules are held by the schema rather than by a service:

* A decided request records who decided it and why. A rejection with no reason is not a decision.
* **The requester cannot be the decision-maker.** §4: *"Requestor cannot approve their own
  administrative decision."* The check is `decided_by <> requested_by` — enforced here because a
  service check is one code path and this is every code path.
* A due date is stored, never computed from a statutory number in code. §4 says the SLA comes from
  *"the approved effective-date register"*, and DR-011 is still an open decision — so the product
  carries the date somebody set and never invents a deadline the law may not give it.

## `legal_holds`

An erasure request that quietly destroyed something the law requires to be kept would be the worst
failure this module can have. A hold is a row with a reason, an authority and dates, and the request
lifecycle reads it before it fulfils anything.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

#: §19.1: *"The approved DPA, customer instructions and data-flow inventory decide the role."* Both
#: are real and neither is a default.
ROLES = ("data_fiduciary", "data_processor")

#: DPDP's own two shapes. `legitimate_use` covers the Act's specified uses; which ones apply to a
#: given activity is counsel's answer, recorded in the register, not the product's.
BASES = ("consent", "legitimate_use", "legal_obligation", "contract")

NOTICE_STATES = ("draft", "in_review", "effective", "retired")

CONSENT_STATES = ("granted", "withdrawn")

#: §4's supported requests, plus the door a jurisdiction pack comes through.
REQUEST_KINDS = (
    "access",
    "correction",
    "completion",
    "update",
    "erasure",
    "grievance",
    "nomination",
)

#: §4's diagram, verbatim in order.
REQUEST_STATES = (
    "submitted",
    "verifying",
    "acknowledged",
    "discovering",
    "reviewing_exemptions",
    "fulfilled",
    "partially_fulfilled",
    "rejected",
    "closed",
    "escalated",
)

DECISIONS = ("fulfil", "partially_fulfil", "reject")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    # ------------------------------------------------------------ §2 the inventory
    op.create_table(
        "processing_activities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #: The specific purpose. Not a category — §2 says *"specific purpose"*, and "business
        #: operations" is not one.
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("accountable_role", sa.String(length=30), nullable=False),
        sa.Column("basis", sa.String(length=30), nullable=False),
        sa.Column("principal_category", sa.String(length=200), nullable=False),
        sa.Column("data_categories", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("recipients", sa.Text(), nullable=True),
        #: Whether a model may see this data at all. §8's first rule is minimisation, and the
        #: register is where the answer is written down.
        sa.Column("ai_access", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("transfer_rule", sa.Text(), nullable=True),
        sa.Column("retention_summary", sa.Text(), nullable=True),
        sa.Column("deletion_path", sa.Text(), nullable=True),
        sa.Column("owner_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("review_due", sa.Date(), nullable=True),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_activities"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_processing_activities_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_processing_activities_tenant_id"),
        sa.CheckConstraint(
            f"accountable_role IN ({_quoted(ROLES)})", name="ck_processing_activities_role"
        ),
        sa.CheckConstraint(f"basis IN ({_quoted(BASES)})", name="ck_processing_activities_basis"),
        sa.CheckConstraint(
            "length(btrim(purpose)) > 0", name="ck_processing_activities_purpose_not_blank"
        ),
    )
    op.execute(
        """
        ALTER TABLE processing_activities
            ADD CONSTRAINT fk_processing_activities_owner
            FOREIGN KEY (tenant_id, owner_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (owner_membership_id);
        """
    )

    # ------------------------------------------------------------ §3 notices
    op.create_table(
        "privacy_notices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #: What this notice is *for* — the processing activity it describes. Null for a general
        #: notice that covers several.
        sa.Column("processing_activity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_privacy_notices"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_privacy_notices_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "processing_activity_id"],
            ["processing_activities.tenant_id", "processing_activities.id"],
            name="fk_privacy_notices_activity",
            ondelete="SET NULL (processing_activity_id)",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_privacy_notices_tenant_id"),
    )

    op.create_table(
        "privacy_notice_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=16), server_default="en", nullable=False),
        sa.Column("state", sa.String(length=20), server_default="draft", nullable=False),
        #: §3's itemised content. Held as columns rather than one blob because each one is a
        #: question a reviewer checks separately, and a blob is what nobody reviews.
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("data_items", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("basis", sa.String(length=30), nullable=False),
        sa.Column("recipients", sa.Text(), nullable=True),
        sa.Column("retention_summary", sa.Text(), nullable=True),
        sa.Column("rights_route", sa.Text(), nullable=False),
        sa.Column("privacy_contact", sa.String(length=300), nullable=False),
        sa.Column("author_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_privacy_notice_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_privacy_notice_versions_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "notice_id"],
            ["privacy_notices.tenant_id", "privacy_notices.id"],
            name="fk_privacy_notice_versions_notice",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "notice_id", "language", "version_no", name="uq_notice_versions_no"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notice_versions_tenant_id"),
        sa.CheckConstraint(f"state IN ({_quoted(NOTICE_STATES)})", name="ck_notice_versions_state"),
        sa.CheckConstraint(f"basis IN ({_quoted(BASES)})", name="ck_notice_versions_basis"),
        #  Reviewed by somebody, and not by the person who wrote it. §3 makes review independent,
        #  and this is the same rule every publish path in this product already keeps.
        sa.CheckConstraint(
            "state IN ('draft', 'in_review') OR ("
            "reviewed_by_membership_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_notice_versions_effective_was_reviewed",
        ),
        sa.CheckConstraint(
            "reviewed_by_membership_id IS NULL "
            "OR author_membership_id IS NULL "
            "OR reviewed_by_membership_id <> author_membership_id",
            name="ck_notice_versions_review_is_independent",
        ),
        sa.CheckConstraint(
            "state <> 'effective' OR effective_from IS NOT NULL",
            name="ck_notice_versions_effective_has_date",
        ),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION privacy_notice_versions_assign_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.notice_id::text, 0));
            SELECT COALESCE(MAX(version_no), 0) + 1 INTO NEW.version_no
                FROM privacy_notice_versions
                WHERE notice_id = NEW.notice_id AND language = NEW.language;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER privacy_notice_versions_assign_number
            BEFORE INSERT ON privacy_notice_versions
            FOR EACH ROW EXECUTE FUNCTION privacy_notice_versions_assign_number();
        """
    )
    #  Not append-only: a draft is edited, and a version moves draft → in_review → effective →
    #  retired. What must not change is the *wording of an effective version*, and that is held by
    #  the trigger below rather than by refusing every update.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION privacy_notice_versions_freeze_effective() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF OLD.state IN ('effective', 'retired') THEN
                IF NEW.body <> OLD.body
                   OR NEW.data_items <> OLD.data_items
                   OR NEW.purpose <> OLD.purpose
                   OR NEW.basis <> OLD.basis
                   OR COALESCE(NEW.recipients, '') <> COALESCE(OLD.recipients, '')
                   OR COALESCE(NEW.retention_summary, '') <> COALESCE(OLD.retention_summary, '')
                   OR NEW.rights_route <> OLD.rights_route
                   OR NEW.privacy_contact <> OLD.privacy_contact THEN
                    RAISE EXCEPTION
                        'the wording of a notice that has been in force cannot be changed; '
                        'publish a new version instead';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER privacy_notice_versions_freeze_effective
            BEFORE UPDATE ON privacy_notice_versions
            FOR EACH ROW EXECUTE FUNCTION privacy_notice_versions_freeze_effective();
        """
    )

    # ------------------------------------------------------------ §3 consent
    op.create_table(
        "consent_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #: Who consented. A membership when it is somebody in the workspace; the email is kept as
        #: well, because a person can leave and the evidence has to survive them.
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("principal_email", sa.String(length=320), nullable=True),
        sa.Column("processing_activity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notice_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        #: How it was given, and what proves it. §3: *"affirmative evidence, channel, language"*.
        sa.Column("channel", sa.String(length=60), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), server_default="en", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        #: The grant this row withdraws, when it is a withdrawal. A withdrawal writes its own row.
        sa.Column("withdraws_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recorded_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_consent_records"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_consent_records_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "notice_version_id"],
            ["privacy_notice_versions.tenant_id", "privacy_notice_versions.id"],
            name="fk_consent_records_notice_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "processing_activity_id"],
            ["processing_activities.tenant_id", "processing_activities.id"],
            name="fk_consent_records_activity",
            ondelete="SET NULL (processing_activity_id)",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_consent_records_tenant_id"),
        sa.CheckConstraint(f"state IN ({_quoted(CONSENT_STATES)})", name="ck_consent_state"),
        sa.CheckConstraint(
            "membership_id IS NOT NULL OR principal_email IS NOT NULL",
            name="ck_consent_names_somebody",
        ),
        sa.CheckConstraint("length(btrim(evidence)) > 0", name="ck_consent_has_evidence"),
        #  A withdrawal names what it withdraws; a grant does not.
        sa.CheckConstraint(
            "(state = 'withdrawn') = (withdraws_id IS NOT NULL)",
            name="ck_consent_withdrawal_names_grant",
        ),
    )
    op.execute(
        """
        ALTER TABLE consent_records
            ADD CONSTRAINT fk_consent_records_withdraws
            FOREIGN KEY (tenant_id, withdraws_id)
            REFERENCES consent_records (tenant_id, id)
            ON DELETE RESTRICT;
        """
    )
    op.create_index(
        "ix_consent_records_principal",
        "consent_records",
        ["tenant_id", "membership_id", "occurred_at"],
    )
    #  Evidence. §3: *"withdrawal … creates immutable evidence"*, and a grant is evidence for the
    #  same reason — so neither can be edited or removed.
    op.execute(
        """
        CREATE TRIGGER consent_records_append_only
            BEFORE UPDATE OR DELETE ON consent_records
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    # ------------------------------------------------------------ §5 legal holds
    op.create_table(
        "legal_holds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #: What it covers, in words. A hold is read by a person deciding an erasure request, and a
        #: machine-readable scope nobody can explain is worse than a sentence they can.
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        #: Who says so. §5: *"conflicting legal retention duties require an authorised decision."*
        sa.Column("authority", sa.String(length=300), nullable=False),
        sa.Column("placed_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "placed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_legal_holds"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_legal_holds_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_legal_holds_tenant_id"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_legal_holds_has_reason"),
        sa.CheckConstraint(
            "released_at IS NULL OR length(btrim(coalesce(release_reason, ''))) > 0",
            name="ck_legal_holds_release_has_reason",
        ),
    )

    # ------------------------------------------------------------ §4 requests
    op.create_table(
        "data_principal_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=30), server_default="submitted", nullable=False),
        #: Who asked. A membership when they are in the workspace, and the email always, because a
        #: request can outlive the account and a response has to reach somebody.
        sa.Column("requested_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("principal_email", sa.String(length=320), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        #: How identity was proved, and by whom. §4 asks for *"proportionate identity
        #: verification"* — proportionate is a judgement, so what is recorded is what was done.
        sa.Column("identity_check", sa.Text(), nullable=True),
        sa.Column("verified_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_to_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        #: Set from the tenant's approved register, never computed from a statutory number here.
        #: DR-011 is an open decision and the product must not invent a deadline for it.
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        #: The hold that stopped part of this being fulfilled, when one did.
        sa.Column("legal_hold_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exemption_note", sa.Text(), nullable=True),
        #: What was sent, how, and when it was collected. §4: *"secure short-lived delivery"*.
        sa.Column("delivery_note", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_data_principal_requests"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_data_principal_requests_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "legal_hold_id"],
            ["legal_holds.tenant_id", "legal_holds.id"],
            name="fk_data_principal_requests_hold",
            ondelete="SET NULL (legal_hold_id)",
        ),
        sa.UniqueConstraint("tenant_id", "reference", name="uq_data_principal_requests_reference"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_data_principal_requests_tenant_id"),
        sa.CheckConstraint(f"kind IN ({_quoted(REQUEST_KINDS)})", name="ck_requests_kind"),
        sa.CheckConstraint(f"state IN ({_quoted(REQUEST_STATES)})", name="ck_requests_state"),
        sa.CheckConstraint(
            f"decision IS NULL OR decision IN ({_quoted(DECISIONS)})", name="ck_requests_decision"
        ),
        #  A decision carries its reason and its author. §4: every rejection and partial response
        #  *"records authority, reason and evidence"*.
        sa.CheckConstraint(
            "decision IS NULL OR ("
            "length(btrim(coalesce(decision_reason, ''))) > 0 "
            "AND decided_by_membership_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_requests_decision_has_reason",
        ),
        #  **The requester does not decide their own request.** §4, held by the table because a
        #  service check is one code path and this is all of them.
        sa.CheckConstraint(
            "decided_by_membership_id IS NULL "
            "OR requested_by_membership_id IS NULL "
            "OR decided_by_membership_id <> requested_by_membership_id",
            name="ck_requests_decider_is_not_requester",
        ),
        sa.CheckConstraint(
            "state NOT IN ('fulfilled', 'partially_fulfilled', 'rejected', 'closed') "
            "OR decision IS NOT NULL",
            name="ck_requests_finished_was_decided",
        ),
    )
    for column, name in (
        ("requested_by_membership_id", "fk_requests_requester"),
        ("verified_by_membership_id", "fk_requests_verifier"),
        ("assigned_to_membership_id", "fk_requests_assignee"),
        ("decided_by_membership_id", "fk_requests_decider"),
    ):
        op.execute(
            f"""
            ALTER TABLE data_principal_requests
                ADD CONSTRAINT {name}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column});
            """
        )
    op.create_index(
        "ix_data_principal_requests_state",
        "data_principal_requests",
        ["tenant_id", "state", "due_at"],
    )

    #  Every step, in order, and none of them rewritable. This is the evidence §4 asks for at each
    #  transition — *"immutable evidence"* — and it is the answer to "who did what, when" a year
    #  later.
    op.create_table(
        "request_actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_request_actions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_request_actions_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["data_principal_requests.tenant_id", "data_principal_requests.id"],
            name="fk_request_actions_request",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_request_actions_request", "request_actions", ["tenant_id", "request_id", "occurred_at"]
    )
    op.execute(
        """
        CREATE TRIGGER request_actions_append_only
            BEFORE UPDATE OR DELETE ON request_actions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    # ------------------------------------------------------------ isolation
    for table in (
        "processing_activities",
        "privacy_notices",
        "privacy_notice_versions",
        "consent_records",
        "legal_holds",
        "data_principal_requests",
        "request_actions",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL
                USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant());
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO uboss_app;")

    #  Two independent refusals on the two evidence tables, as everywhere else in this schema.
    op.execute("REVOKE UPDATE, DELETE ON consent_records FROM uboss_app;")
    op.execute("REVOKE UPDATE, DELETE ON request_actions FROM uboss_app;")


def downgrade() -> None:
    for statement in (
        "DROP TRIGGER IF EXISTS request_actions_append_only ON request_actions",
        "DROP TABLE IF EXISTS request_actions",
        "DROP TABLE IF EXISTS data_principal_requests",
        "DROP TABLE IF EXISTS legal_holds",
        "DROP TRIGGER IF EXISTS consent_records_append_only ON consent_records",
        "DROP TABLE IF EXISTS consent_records",
        "DROP TRIGGER IF EXISTS privacy_notice_versions_freeze_effective "
        "ON privacy_notice_versions",
        "DROP TRIGGER IF EXISTS privacy_notice_versions_assign_number ON privacy_notice_versions",
        "DROP TABLE IF EXISTS privacy_notice_versions",
        "DROP FUNCTION IF EXISTS privacy_notice_versions_assign_number()",
        "DROP FUNCTION IF EXISTS privacy_notice_versions_freeze_effective()",
        "DROP TABLE IF EXISTS privacy_notices",
        "DROP TABLE IF EXISTS processing_activities",
    ):
        op.execute(statement)
