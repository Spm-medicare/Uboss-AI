"""Objectives — the workbook's Form 2, and what governing it needs.

`docs/architecture/OBJECTIVE_FIELDS.md` records why this is two field sets rather than one. In
short: the approved workbook's *"FORM 2 — OBJECTIVE BUILDER | EXISTING WORKFLOW"* is the floor of
what must be captured, and `PLAN.md` §6 says a new interface may reorganise those fields but never
remove them. §7 adds what the workbook never had — an owner and approver, a visibility policy, AI
preferences.

**The step table is the process as it stands today.** Fourteen columns, exactly the workbook's,
including its `Other` on every closed list. It is deliberately *not* the execution graph Claude
proposes in 3.2: comparing the two is the point of the product, and one table could not hold both.

**A published version is immutable, and the trigger says so.** PLAN §30: *"Published versions are
immutable."* Enforced here rather than in the service, because 3.3's approval path and a future
import would each have to remember, and one of them would not.

Revision: 0013
Parent:   0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: PLAN §7's views/statuses, in order. `draft` is where everything starts and `archived` is the
#: only terminal state — a published objective is never deleted, only archived.
STATUSES: tuple[str, ...] = (
    "draft",
    "analyzing",
    "needs_review",
    "ready_to_publish",
    "published",
    "active",
    "paused",
    "archived",
)

#: §7 group 1. Not on the workbook sheet; the release gate needed it, so it is here.
PRIORITIES: tuple[str, ...] = ("low", "normal", "high", "critical")

#: §7 group 7. Who can see the objective once it exists.
VISIBILITIES: tuple[str, ...] = ("owner", "department", "company")

#: §7 group 8. How much the product may do without asking.
AI_ASSISTANCE: tuple[str, ...] = ("none", "propose_only", "propose_and_draft")


def upgrade() -> None:
    statuses = ", ".join(f"'{value}'" for value in STATUSES)
    priorities = ", ".join(f"'{value}'" for value in PRIORITIES)
    visibilities = ", ".join(f"'{value}'" for value in VISIBILITIES)
    assistance = ", ".join(f"'{value}'" for value in AI_ASSISTANCE)

    op.create_table(
        "objectives",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        # ── the workbook's heading block ────────────────────────────────────────────────
        #  "Objective Name *"
        sa.Column("title", sa.String(length=300), nullable=False),
        #  "Department *". A free string with the workbook's list offered, not a foreign key to
        #  `org_units`: a team writes "Sales" before anybody has built the tree, and refusing the
        #  objective until they do would stop the work this product exists to capture.
        sa.Column("department", sa.String(length=200), nullable=True),
        #  "Objective Owner *" — chosen from the people in this workspace, so it is a membership.
        sa.Column("owner_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  "Expected Final Result *"
        sa.Column("expected_result", sa.Text(), nullable=True),
        #  "Current Workload" and its "Unit"
        sa.Column("workload_count", sa.String(length=60), nullable=True),
        sa.Column("workload_unit", sa.String(length=40), nullable=True),
        #  "Target Completion Time". A date, not a duration: the workbook offers a unit, and the
        #  old build resolved it to a date, which is the form a schedule can actually use.
        sa.Column("target_date", sa.Date(), nullable=True),
        # ── PLAN §7's additions ─────────────────────────────────────────────────────────
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("baseline", sa.Text(), nullable=True),
        sa.Column("success_measures", sa.Text(), nullable=True),
        sa.Column("included_work", sa.Text(), nullable=True),
        sa.Column("excluded_work", sa.Text(), nullable=True),
        sa.Column("stakeholders", sa.Text(), nullable=True),
        sa.Column("geography", sa.String(length=200), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("urgency", sa.String(length=200), nullable=True),
        sa.Column("budget_note", sa.Text(), nullable=True),
        sa.Column("policy_constraints", sa.Text(), nullable=True),
        sa.Column("dependencies", sa.Text(), nullable=True),
        sa.Column("risk_note", sa.Text(), nullable=True),
        #  Governance. The approver is separate from the owner on purpose: PLAN §16 forbids
        #  self-approval, and a single column could not express the distinction.
        sa.Column("approver_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="department"),
        sa.Column("handles_sensitive_data", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sensitive_data_note", sa.Text(), nullable=True),
        #  AI preferences. `propose_only` is the default because §7's whole design is that Claude
        #  proposes and a person decides — the safer default is also the described one.
        sa.Column(
            "ai_assistance", sa.String(length=30), nullable=False, server_default="propose_only"
        ),
        sa.Column("human_checkpoints", sa.Text(), nullable=True),
        # ── bookkeeping ─────────────────────────────────────────────────────────────────
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  The version a person is looking at when they save. PLAN §28's optimistic concurrency.
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        #  Set when a version is published from this draft.
        sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_objectives"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_objectives_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_objectives_tenant_id"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_objectives_status_known"),
        sa.CheckConstraint(f"priority IN ({priorities})", name="ck_objectives_priority_known"),
        sa.CheckConstraint(
            f"visibility IN ({visibilities})", name="ck_objectives_visibility_known"
        ),
        sa.CheckConstraint(
            f"ai_assistance IN ({assistance})", name="ck_objectives_assistance_known"
        ),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_objectives_title_not_blank"),
        #  A published objective must point at the version it published. Without this a row could
        #  claim to be published with nothing immutable behind it — the claim nobody could check.
        sa.CheckConstraint(
            "status NOT IN ('published', 'active', 'paused') OR published_version_id IS NOT NULL",
            name="ck_objectives_published_has_version",
        ),
        sa.CheckConstraint(
            "target_date IS NULL OR start_date IS NULL OR target_date >= start_date",
            name="ck_objectives_dates_ordered",
        ),
    )
    for column, constraint in (
        ("owner_membership_id", "fk_objectives_tenant_owner"),
        ("approver_membership_id", "fk_objectives_tenant_approver"),
        ("created_by_membership_id", "fk_objectives_tenant_creator"),
    ):
        op.execute(
            f"""
            ALTER TABLE objectives
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column})
            """
        )
    op.create_index("ix_objectives_tenant_id", "objectives", ["tenant_id"])
    op.create_index("ix_objectives_tenant_status", "objectives", ["tenant_id", "status"])
    op.create_index("ix_objectives_tenant_owner", "objectives", ["tenant_id", "owner_membership_id"])

    # ------------------------------------------------- the workbook's step table

    op.create_table(
        "objective_current_steps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  "Step" — 1-based, as the workbook numbers them.
        sa.Column("position", sa.Integer(), nullable=False),
        #  The workbook's fourteen columns, in its own order and its own words. Every one of them
        #  is free text: seven have a suggested list, and every list ends in "Other", so refusing
        #  a value outside it would refuse something the workbook explicitly allows.
        sa.Column("who_person", sa.String(length=200), nullable=True),
        sa.Column("who_role", sa.String(length=200), nullable=True),
        sa.Column("when_trigger", sa.String(length=200), nullable=True),
        sa.Column("when_frequency", sa.String(length=200), nullable=True),
        sa.Column("what_exact_work", sa.Text(), nullable=True),
        sa.Column("input_used", sa.Text(), nullable=True),
        sa.Column("input_received_from", sa.String(length=200), nullable=True),
        sa.Column("where_done", sa.String(length=200), nullable=True),
        sa.Column("output_produced", sa.Text(), nullable=True),
        sa.Column("output_sent_to", sa.String(length=200), nullable=True),
        sa.Column("time_taken", sa.String(length=100), nullable=True),
        sa.Column("current_problem", sa.String(length=200), nullable=True),
        sa.Column("approval", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_objective_current_steps"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_current_steps_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        #  CASCADE: a step has no meaning without its objective, and an objective is archived
        #  rather than deleted, so this only fires on a genuine purge.
        sa.ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_current_steps_tenant_objective",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "objective_id", "position", name="uq_current_steps_position"
        ),
        sa.CheckConstraint("position >= 1", name="ck_current_steps_position_positive"),
    )
    op.create_index(
        "ix_objective_current_steps_tenant_id", "objective_current_steps", ["tenant_id"]
    )
    op.create_index(
        "ix_current_steps_objective",
        "objective_current_steps",
        ["tenant_id", "objective_id", "position"],
    )

    # ---------------------------------------------------------- immutable versions

    op.create_table(
        "objective_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  1, 2, 3 … per objective. Assigned by trigger, like a revision number, and for the same
        #  reason: a gap would be indistinguishable from a version somebody removed.
        sa.Column("version_no", sa.Integer(), nullable=False),
        #  The whole objective as it was at publish, steps included. PLAN §30 allows JSON for
        #  snapshots specifically — the searchable fields are normalised on `objectives`, and
        #  this is the frozen copy nothing queries by.
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        #  Denormalised so a version list reads without joining or opening the snapshot.
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("published_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_objective_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_objective_versions_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_versions_tenant_objective",
            #  RESTRICT, not CASCADE. A published version is evidence: deleting the objective
            #  must not take the record of what was approved with it.
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "objective_id", "version_no", name="uq_versions_objective_no"
        ),
    )
    for column, constraint in (
        ("published_by_membership_id", "fk_versions_tenant_publisher"),
        ("approved_by_membership_id", "fk_versions_tenant_approver"),
    ):
        op.execute(
            f"""
            ALTER TABLE objective_versions
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column})
            """
        )
    op.create_index("ix_objective_versions_tenant_id", "objective_versions", ["tenant_id"])
    op.create_index(
        "ix_versions_objective", "objective_versions", ["tenant_id", "objective_id", "version_no"]
    )
    op.execute(
        """
        ALTER TABLE objectives
            ADD CONSTRAINT fk_objectives_published_version
            FOREIGN KEY (published_version_id)
            REFERENCES objective_versions (id)
            ON DELETE RESTRICT
        """
    )

    # -------------------------------------------------------------------- triggers

    op.execute(
        """
        CREATE OR REPLACE FUNCTION objective_versions_assign_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.objective_id::text, 0));
            SELECT COALESCE(MAX(version_no), 0) + 1 INTO NEW.version_no
                FROM objective_versions
                WHERE objective_id = NEW.objective_id;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER objective_versions_assign_number
            BEFORE INSERT ON objective_versions
            FOR EACH ROW EXECUTE FUNCTION objective_versions_assign_number();
        """
    )
    #  PLAN §30: "Published versions are immutable." In the database, so that 3.3's approval path
    #  and any later importer cannot forget.
    op.execute(
        """
        CREATE TRIGGER objective_versions_append_only
            BEFORE UPDATE OR DELETE ON objective_versions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    for table in ("objectives", "objective_current_steps"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )

    for table in ("objectives", "objective_current_steps", "objective_versions"):
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

    #  Immutable means immutable: the privilege is withheld as well as the trigger set, so an
    #  attempt fails at the boundary rather than inside it, and the intent reads in the grant.
    op.execute("REVOKE UPDATE, DELETE ON objective_versions FROM uboss_app;")


def downgrade() -> None:
    """Drops objectives and every published version with them.

    Reversing this loses approved, immutable records of what a company committed to. It exists so
    the migration is reversible in development; against real data it needs an export first.
    """
    op.execute(
        "ALTER TABLE objectives DROP CONSTRAINT IF EXISTS fk_objectives_published_version"
    )
    op.execute("DROP TABLE IF EXISTS objective_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS objective_current_steps CASCADE")
    op.execute("DROP TABLE IF EXISTS objectives CASCADE")
    op.execute("DROP FUNCTION IF EXISTS objective_versions_assign_number()")
