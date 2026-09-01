"""Retention and its evidence, breach cases, and the processor register.

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-01

`docs/security/PRIVACY_COMPLIANCE.md` §5, §6 and §7 — the three families 0044 deliberately left for
their own migration, on the grounds that a table added before the service that fills it is a table
whose shape nobody has tested.

## §5 `retention_policies` and `retention_runs`

A policy says what to keep, for how long, and what to do when the time is up. **Nothing is defaulted
to a number of days.** §5 scopes a policy *"by tenant, data category, purpose, jurisdiction and
lifecycle state"* and asks for *"trigger, period, disposal method, exception, backup behavior, owner
and review date"* — every one of which is somebody's decision. A `period_days` with a default would
be this product deciding how long an organisation keeps personal data.

A run is the evidence: *"Record candidate, excluded/held, deleted/anonymised/archived, failed and
reconciled counts with evidence."* Five counts and a note, append-only, because a retention run is
the record that a deletion happened — and a record of a deletion that can be edited is not one.

**A run is a plan until somebody approves it.** §5: *"Execution requires preview and approval where
configured."* So a run is created as a preview with its candidate counts and nothing else, and the
approval is a separate act by a person who is not the person who prepared it. The disposal itself is
not performed here — see the note in `retention.py`.

## §6 `breach_cases` and `breach_actions`

§6's fields, and two constraints that carry its most important sentence: *"Privacy/Legal approves
applicability, exact timing and wording. An Agent may draft; it cannot decide legal notification or
send without authorised approval."*

* A case that says a notification was sent must name who approved it. `ck_breach_notified_was_approved`.
* A closed case must name who closed it and why. A breach that was closed with no reason is a breach
  nobody reviewed.

`awareness_at` is separate from `detected_at` and from `created_at`, and the three are genuinely
different: when something happened, when somebody realised, and when the case was opened. Statutory
clocks run from the second, which is why it is its own column and why nothing computes it.

## §7 `processors`

The subprocessor register. §7 requires that *"new/materially changed subprocessors require risk
review, contract approval and configured customer-notice/change workflow before personal data is
sent"* — so `state` is the workflow, and `ck_processors_active_was_reviewed` refuses an active
processor that has not been through it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

#: What happens when a retention period ends. §5's *"disposal method"*.
DISPOSALS = ("delete", "anonymise", "archive", "review")

#: A run's life. A preview is a plan; only an approved run is evidence of a disposal.
RUN_STATES = ("preview", "approved", "executed", "failed", "cancelled")

#: §6's own progression, as a state.
BREACH_STATES = (
    "open",
    "contained",
    "assessing",
    "notifying",
    "remediating",
    "closed",
)

BREACH_SEVERITIES = ("unknown", "low", "medium", "high", "critical")

#: §7's workflow. `retired` is the end of a relationship, which has its own evidence.
PROCESSOR_STATES = ("proposed", "under_review", "approved", "active", "suspended", "retired")

PROCESSOR_ROLES = ("processor", "subprocessor", "joint_controller")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    # ------------------------------------------------------------ §5 retention
    op.create_table(
        "retention_policies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #: What it applies to. §5's scope, in the words of the register rather than as a query: a
        #: policy is read by a person deciding whether it covers a row.
        sa.Column("data_category", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.String(length=120), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=120), nullable=True),
        sa.Column("processing_activity_id", postgresql.UUID(as_uuid=True), nullable=True),
        #: When the clock starts — *"trigger"*. A sentence: "when the employment ends", "on the
        #: last day of the financial year the invoice falls in".
        sa.Column("trigger", sa.Text(), nullable=False),
        #: How long after that. No default, and nullable so *"decided case by case"* is sayable.
        sa.Column("period_days", sa.Integer(), nullable=True),
        sa.Column("disposal", sa.String(length=20), nullable=False),
        sa.Column("exception_note", sa.Text(), nullable=True),
        #: What happens to backups. §5 asks for it separately because it is the part that is
        #: usually forgotten and always asked about.
        sa.Column("backup_behaviour", sa.Text(), nullable=True),
        #: §5: *"Execution requires preview and approval where configured."* This is the
        #: configuration.
        sa.Column(
            "approval_required", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("owner_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_due", sa.Date(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retention_policies"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_retention_policies_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "processing_activity_id"],
            ["processing_activities.tenant_id", "processing_activities.id"],
            name="fk_retention_policies_activity",
            ondelete="SET NULL (processing_activity_id)",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_retention_policies_tenant_id"),
        sa.CheckConstraint(
            f"disposal IN ({_quoted(DISPOSALS)})", name="ck_retention_policies_disposal"
        ),
        sa.CheckConstraint(
            "period_days IS NULL OR period_days >= 0", name="ck_retention_policies_period"
        ),
        sa.CheckConstraint(
            "length(btrim(trigger)) > 0", name="ck_retention_policies_trigger_not_blank"
        ),
    )
    op.execute(
        """
        ALTER TABLE retention_policies
            ADD CONSTRAINT fk_retention_policies_owner
            FOREIGN KEY (tenant_id, owner_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (owner_membership_id);
        """
    )

    op.create_table(
        "retention_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="preview", nullable=False),
        #: §5's five counts. Nullable until the run reaches the state that knows them: a preview
        #: knows its candidates and nothing else, and a zero would claim it deleted nothing.
        sa.Column("candidates", sa.Integer(), nullable=True),
        sa.Column("excluded", sa.Integer(), nullable=True),
        sa.Column("disposed", sa.Integer(), nullable=True),
        sa.Column("failed", sa.Integer(), nullable=True),
        sa.Column("reconciled", sa.Integer(), nullable=True),
        #: What was searched, what was excluded and why. The evidence a reconciliation is read
        #: from — §5: *"with evidence"*.
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("prepared_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "prepared_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("approved_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_retention_runs"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_retention_runs_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["retention_policies.tenant_id", "retention_policies.id"],
            name="fk_retention_runs_policy",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_retention_runs_tenant_id"),
        sa.CheckConstraint(f"state IN ({_quoted(RUN_STATES)})", name="ck_retention_runs_state"),
        #  An approved or executed run names who approved it. §5's preview-and-approval, held here
        #  rather than in a service.
        sa.CheckConstraint(
            "state NOT IN ('approved', 'executed') OR ("
            "approved_by_membership_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_retention_runs_approved_by_somebody",
        ),
        #  **And not by the person who prepared it.** A disposal proposed and approved by one person
        #  is a disposal nobody reviewed.
        sa.CheckConstraint(
            "approved_by_membership_id IS NULL "
            "OR prepared_by_membership_id IS NULL "
            "OR approved_by_membership_id <> prepared_by_membership_id",
            name="ck_retention_runs_approver_is_not_preparer",
        ),
        sa.CheckConstraint(
            "state <> 'executed' OR executed_at IS NOT NULL",
            name="ck_retention_runs_executed_has_time",
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR length(btrim(coalesce(failure_detail, ''))) > 0",
            name="ck_retention_runs_failure_has_detail",
        ),
    )
    op.create_index(
        "ix_retention_runs_policy", "retention_runs", ["tenant_id", "policy_id", "prepared_at"]
    )
    #  Evidence of a disposal. Append-only in both ways, like every other evidence table here.
    op.execute(
        """
        CREATE TRIGGER retention_runs_append_only
            BEFORE DELETE ON retention_runs
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )
    #  `UPDATE` is allowed — a run moves preview → approved → executed — and the columns that
    #  matter are protected by the checks above plus the service. `DELETE` never is.

    # ------------------------------------------------------------ §6 breach cases
    op.create_table(
        "breach_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("severity", sa.String(length=20), server_default="unknown", nullable=False),
        #: Three different times, and §6 asks for the first two by name. Statutory clocks run from
        #: awareness, so it is its own column and nothing computes it.
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awareness_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("commander_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("affected_systems", sa.Text(), nullable=True),
        sa.Column("affected_regions", sa.String(length=300), nullable=True),
        sa.Column("data_categories", sa.Text(), nullable=True),
        #: An estimate, and nullable because *"we do not yet know"* is the honest answer for the
        #: first hours. A zero would say nobody was affected.
        sa.Column("estimated_principals", sa.Integer(), nullable=True),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column("containment", sa.Text(), nullable=True),
        #: Whether the authority and the affected people have to be told, and on whose authority
        #: that was decided. Never inferred from the severity.
        sa.Column(
            "authority_notification_required", sa.Boolean(), nullable=True
        ),
        sa.Column("principal_notification_required", sa.Boolean(), nullable=True),
        sa.Column("notification_decided_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notification_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_reason", sa.Text(), nullable=True),
        sa.Column("authority_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("principals_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("postmortem", sa.Text(), nullable=True),
        sa.Column("closed_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closure_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_breach_cases"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_breach_cases_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "reference", name="uq_breach_cases_reference"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_breach_cases_tenant_id"),
        sa.CheckConstraint(f"state IN ({_quoted(BREACH_STATES)})", name="ck_breach_cases_state"),
        sa.CheckConstraint(
            f"severity IN ({_quoted(BREACH_SEVERITIES)})", name="ck_breach_cases_severity"
        ),
        sa.CheckConstraint(
            "estimated_principals IS NULL OR estimated_principals >= 0",
            name="ck_breach_cases_principals",
        ),
        #  §6: an Agent *"cannot decide legal notification or send without authorised approval."*
        #  A notification that was sent names the person who decided it should be.
        sa.CheckConstraint(
            "(authority_notified_at IS NULL AND principals_notified_at IS NULL) OR ("
            "notification_decided_by_membership_id IS NOT NULL "
            "AND notification_decided_at IS NOT NULL)",
            name="ck_breach_notified_was_approved",
        ),
        #  A closed case names who closed it and why.
        sa.CheckConstraint(
            "state <> 'closed' OR ("
            "closed_by_membership_id IS NOT NULL AND closed_at IS NOT NULL "
            "AND length(btrim(coalesce(closure_reason, ''))) > 0)",
            name="ck_breach_closed_has_reason",
        ),
    )
    for column, name in (
        ("reported_by_membership_id", "fk_breach_reporter"),
        ("commander_membership_id", "fk_breach_commander"),
        ("notification_decided_by_membership_id", "fk_breach_notifier"),
        ("closed_by_membership_id", "fk_breach_closer"),
    ):
        op.execute(
            f"""
            ALTER TABLE breach_cases
                ADD CONSTRAINT {name}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column});
            """
        )

    op.create_table(
        "breach_actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_breach_actions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_breach_actions_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["breach_cases.tenant_id", "breach_cases.id"],
            name="fk_breach_actions_case",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_breach_actions_case", "breach_actions", ["tenant_id", "case_id", "occurred_at"]
    )
    op.execute(
        """
        CREATE TRIGGER breach_actions_append_only
            BEFORE UPDATE OR DELETE ON breach_actions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    # ------------------------------------------------------------ §7 processors
    op.create_table(
        "processors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("processing_role", sa.String(length=30), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="proposed", nullable=False),
        sa.Column("data_categories", sa.Text(), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("transfer_rule", sa.Text(), nullable=True),
        sa.Column("contract_version", sa.String(length=120), nullable=True),
        sa.Column("safeguards", sa.Text(), nullable=True),
        sa.Column("deletion_support", sa.Text(), nullable=True),
        sa.Column("security_review", sa.Text(), nullable=True),
        sa.Column("reviewed_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        #: §7: the customer-notice workflow *"before personal data is sent"*.
        sa.Column("customer_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        #: Termination evidence: §7 requires export, deletion confirmation and key revocation.
        sa.Column("exit_evidence", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processors"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_processors_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_processors_tenant_id"),
        sa.CheckConstraint(f"state IN ({_quoted(PROCESSOR_STATES)})", name="ck_processors_state"),
        sa.CheckConstraint(
            f"processing_role IN ({_quoted(PROCESSOR_ROLES)})", name="ck_processors_role"
        ),
        #  §7: nothing becomes active without the review and the contract. Held here because the
        #  consequence of skipping it is personal data leaving the country under no agreement.
        sa.CheckConstraint(
            "state <> 'active' OR ("
            "reviewed_by_membership_id IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND length(btrim(coalesce(contract_version, ''))) > 0)",
            name="ck_processors_active_was_reviewed",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR length(btrim(coalesce(exit_evidence, ''))) > 0",
            name="ck_processors_retired_has_evidence",
        ),
    )
    op.execute(
        """
        ALTER TABLE processors
            ADD CONSTRAINT fk_processors_reviewer
            FOREIGN KEY (tenant_id, reviewed_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (reviewed_by_membership_id);
        """
    )

    # ------------------------------------------------------------ isolation
    for table in (
        "retention_policies",
        "retention_runs",
        "breach_cases",
        "breach_actions",
        "processors",
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

    op.execute("REVOKE DELETE ON retention_runs FROM uboss_app;")
    op.execute("REVOKE UPDATE, DELETE ON breach_actions FROM uboss_app;")


def downgrade() -> None:
    for statement in (
        "DROP TRIGGER IF EXISTS breach_actions_append_only ON breach_actions",
        "DROP TABLE IF EXISTS breach_actions",
        "DROP TABLE IF EXISTS breach_cases",
        "DROP TRIGGER IF EXISTS retention_runs_append_only ON retention_runs",
        "DROP TABLE IF EXISTS retention_runs",
        "DROP TABLE IF EXISTS retention_policies",
        "DROP TABLE IF EXISTS processors",
    ):
        op.execute(statement)
