"""Jobs — the approved workbook's Form 3, its sixteen step columns, WHO rules and typed inputs.

Read from `UBOSS_Complete_Builder_Forms_Organogram (1).xlsx`, sheet **"FORM 3 — JOB BUILDER |
EXACT JOB METHOD"**, rather than summarised. `PLAN.md` §8 lists the same sixteen step fields by
name, so unlike the Objective there is no conflict to resolve here: the sheet and the plan agree,
and both are implemented whole.

**A Job is not an Agent.** §8 opens with it: *"Job Builder defines reusable work; it is not a
runtime Agent."* This schema describes a method — who does what, in what order, with what inputs
and what happens when something is missing. What executes it is Gate 5's Agent and Gate 7's
runtime, and neither is here.

**WHO is a rule, not a person.** §8 lists six types: user, team, department, role, hierarchy
position or subtree, and a dynamic eligible group. A `who_person` column would work until the
first time somebody left, which is why `job_assignment_rules` is a table and the workbook's
free-text WHO columns stay on the step as the description they are.

**An input is typed, and says what may be done with it.** §8: *"INPUT fields include name,
schema/type, source, required status, validation, classification, retention and AI-access
permission."* That last one is the reason inputs are not just strings: an input a model may not
see has to be able to say so, and Gate 5's Agent reads it.

Revision: 0016
Parent:   0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The same lifecycle as an Objective. One vocabulary across the Builders, so a person who has
#: published one knows what the words mean on the next.
STATUSES: tuple[str, ...] = (
    "draft",
    "needs_review",
    "ready_to_publish",
    "published",
    "active",
    "paused",
    "archived",
)

#: PLAN §8's six WHO types, exactly.
WHO_TYPES: tuple[str, ...] = (
    "user",
    "team",
    "department",
    "role",
    "hierarchy_position",
    "hierarchy_subtree",
    "dynamic_group",
)

#: The workbook's "Input Status" list.
INPUT_REQUIREMENTS: tuple[str, ...] = ("Mandatory", "Optional", "Conditional")

#: PLAN §19 and the privacy module's vocabulary, not a new one.
CLASSIFICATIONS: tuple[str, ...] = (
    "internal",
    "confidential",
    "personal_data",
    "public",
)

#: What a model may do with an input. `none` is the default and the safe one.
AI_ACCESS: tuple[str, ...] = ("none", "read", "read_write")

#: Whether a person or software does a step. The same three the Objective's graph uses.
STEP_MODES: tuple[str, ...] = ("human", "ai_agent", "hybrid")


def upgrade() -> None:
    statuses = ", ".join(f"'{value}'" for value in STATUSES)
    who_types = ", ".join(f"'{value}'" for value in WHO_TYPES)
    requirements = ", ".join(f"'{value}'" for value in INPUT_REQUIREMENTS)
    classifications = ", ".join(f"'{value}'" for value in CLASSIFICATIONS)
    ai_access = ", ".join(f"'{value}'" for value in AI_ACCESS)
    modes = ", ".join(f"'{value}'" for value in STEP_MODES)

    # ------------------------------------------------------- the job (Form 3's header)

    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        #  "Objective Name" and "Department" are linked from Form 2 rather than retyped. Nullable
        #  because a job can be described before the objective it serves exists — teams do not
        #  work in the order a form designer imagines.
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  Which step of the objective's plan this job carries out. §8 group 1: "Identity and
        #  linked Objective step/version."
        sa.Column("objective_step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("department", sa.String(length=200), nullable=True),
        #  "Job ID / Name *"
        sa.Column("name", sa.String(length=300), nullable=False),
        #  The customer's own reference for this job, if they have one.
        sa.Column("external_ref", sa.String(length=120), nullable=True),
        #  "Job Owner *"
        sa.Column("owner_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  "Current Person *" and "Role *" — who does it today. Free text: the workbook asks the
        #  person filling it in, and they write what they call themselves.
        sa.Column("current_person", sa.String(length=200), nullable=True),
        sa.Column("current_role", sa.String(length=200), nullable=True),
        #  "Trigger *" and "Frequency *", from the workbook's own lists.
        sa.Column("trigger", sa.String(length=200), nullable=True),
        sa.Column("frequency", sa.String(length=200), nullable=True),
        #  "High-Level Work *"
        sa.Column("high_level_work", sa.Text(), nullable=True),
        #  "Job Start Requirement" — what must be true before it can begin.
        sa.Column("start_requirement", sa.Text(), nullable=True),
        #  "Job Completion Evidence" — how anybody knows it finished. §8 group 8.
        sa.Column("completion_evidence", sa.Text(), nullable=True),
        #  "Normal Completion Time" and "Time Unit"
        sa.Column("normal_completion_time", sa.String(length=60), nullable=True),
        sa.Column("time_unit", sa.String(length=40), nullable=True),
        # ── §8's groups that the sheet does not carry ──────────────────────────────────
        #  Group 2: purpose and expected output.
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("expected_output", sa.Text(), nullable=True),
        #  Group 8: quality and SLA.
        sa.Column("quality_checks", sa.Text(), nullable=True),
        sa.Column("sla_note", sa.String(length=300), nullable=True),
        #  Group 9: retry, failure, escalation. The workbook's per-step "If Missing / Wrong" is
        #  the narrow case; these are the job's own policy when the whole thing fails.
        sa.Column("retry_policy", sa.Text(), nullable=True),
        sa.Column("failure_action", sa.String(length=200), nullable=True),
        sa.Column("escalation_to", sa.String(length=200), nullable=True),
        #  Group 10: access and sharing.
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="department"),
        sa.Column("approver_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_jobs_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_jobs_tenant_objective",
            #  The job survives its objective being removed; it describes work that exists
            #  whether or not anybody is still tracking the objective it served.
            ondelete="SET NULL (objective_id)",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "objective_step_id"],
            ["objective_steps.tenant_id", "objective_steps.id"],
            name="fk_jobs_tenant_objective_step",
            ondelete="SET NULL (objective_step_id)",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_jobs_tenant_id"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_jobs_status_known"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_jobs_name_not_blank"),
        sa.CheckConstraint(
            "status NOT IN ('published', 'active', 'paused') OR published_version_id IS NOT NULL",
            name="ck_jobs_published_has_version",
        ),
        sa.CheckConstraint(
            "status <> 'ready_to_publish' OR submitted_by_membership_id IS NOT NULL",
            name="ck_jobs_submitted_has_submitter",
        ),
    )
    for column, constraint in (
        ("owner_membership_id", "fk_jobs_tenant_owner"),
        ("approver_membership_id", "fk_jobs_tenant_approver"),
        ("submitted_by_membership_id", "fk_jobs_tenant_submitter"),
        ("created_by_membership_id", "fk_jobs_tenant_creator"),
    ):
        op.execute(
            f"""
            ALTER TABLE jobs
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column})
            """
        )
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])
    op.create_index("ix_jobs_tenant_status", "jobs", ["tenant_id", "status"])
    op.create_index("ix_jobs_tenant_objective", "jobs", ["tenant_id", "objective_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_jobs_external_ref
            ON jobs (tenant_id, external_ref)
            WHERE external_ref IS NOT NULL;
        """
    )

    # ------------------------------------------- the sixteen-column step table

    op.create_table(
        "job_steps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  1. "Step" — 1-based, as the workbook numbers them.
        sa.Column("position", sa.Integer(), nullable=False),
        #  2-3. WHO
        sa.Column("who_person", sa.String(length=200), nullable=True),
        sa.Column("who_role", sa.String(length=200), nullable=True),
        #  4-5. WHEN
        sa.Column("when_trigger", sa.String(length=200), nullable=True),
        sa.Column("when_frequency", sa.String(length=200), nullable=True),
        #  6. WHAT
        sa.Column("what_exact_work", sa.Text(), nullable=True),
        #  7-8. INPUT
        sa.Column("input_exact", sa.Text(), nullable=True),
        sa.Column("input_found_where", sa.String(length=200), nullable=True),
        #  9. HOW — the workbook's "Method" list. This is the column that separates Form 3 from
        #  Form 2: the objective records *what* happens, the job records *how*.
        sa.Column("how_exact_method", sa.Text(), nullable=True),
        #  10. WHERE the work is performed
        sa.Column("where_performed", sa.String(length=200), nullable=True),
        #  11. The rule, formula or check. Free text on purpose — a spreadsheet formula, a
        #  tolerance, a policy clause. Turning it into structure would refuse most of them.
        sa.Column("rule_formula_check", sa.Text(), nullable=True),
        #  12-13. OUTPUT
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("output_destination", sa.String(length=200), nullable=True),
        #  14. Approval, from the workbook's "Approval Timing" list.
        sa.Column("approval", sa.String(length=200), nullable=True),
        #  15. "If Missing / Wrong" — the workbook's "Missing Action" list. This is the field
        #  that makes a job runnable rather than merely described: it says what to do when the
        #  input is not there, which is the case a written procedure always omits.
        sa.Column("if_missing_or_wrong", sa.String(length=300), nullable=True),
        #  16. Time
        sa.Column("time_taken", sa.String(length=100), nullable=True),
        #  §8 group 6: human, AI or hybrid, and dependencies. Not on the sheet — the sheet
        #  describes how a person does it today — so it defaults to `human`.
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="human"),
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
        sa.PrimaryKeyConstraint("id", name="pk_job_steps"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_job_steps_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_steps_tenant_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_job_steps_tenant_id"),
        sa.UniqueConstraint("tenant_id", "job_id", "position", name="uq_job_steps_position"),
        sa.CheckConstraint(f"mode IN ({modes})", name="ck_job_steps_mode_known"),
        sa.CheckConstraint("position >= 1", name="ck_job_steps_position_positive"),
    )
    op.create_index("ix_job_steps_tenant_id", "job_steps", ["tenant_id"])
    op.create_index("ix_job_steps_job", "job_steps", ["tenant_id", "job_id", "position"])

    op.create_table(
        "job_step_dependencies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("depends_on_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_step_dependencies"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_job_step_deps_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "step_id"],
            ["job_steps.tenant_id", "job_steps.id"],
            name="fk_job_step_deps_tenant_step",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "depends_on_step_id"],
            ["job_steps.tenant_id", "job_steps.id"],
            name="fk_job_step_deps_tenant_target",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "step_id", "depends_on_step_id", name="uq_job_step_deps_pair"
        ),
        sa.CheckConstraint("step_id <> depends_on_step_id", name="ck_job_step_deps_not_self"),
    )
    op.create_index("ix_job_step_dependencies_tenant_id", "job_step_dependencies", ["tenant_id"])
    op.create_index("ix_job_step_deps_step", "job_step_dependencies", ["tenant_id", "step_id"])

    # ------------------------------------------------- §8: multiple WHO assignment rules

    op.create_table(
        "job_assignment_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("who_type", sa.String(length=30), nullable=False),
        #  What it points at, in the terms of its own type: a membership, a role, an org unit, a
        #  position. Nullable because `dynamic_group` names a condition rather than a row.
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  A department name or group description where the target is not a row in this database.
        sa.Column("target_label", sa.String(length=300), nullable=True),
        #  Why this rule exists, and when it applies. §8 asks for *multiple* WHO rules, which is
        #  only useful if each can say what it covers.
        sa.Column("condition_note", sa.Text(), nullable=True),
        #  Whether everyone matched must act, or any one of them is enough.
        sa.Column("all_must_act", sa.Boolean(), nullable=False, server_default="false"),
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
        sa.PrimaryKeyConstraint("id", name="pk_job_assignment_rules"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_job_rules_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_rules_tenant_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "job_id", "position", name="uq_job_rules_position"),
        sa.CheckConstraint(f"who_type IN ({who_types})", name="ck_job_rules_who_type_known"),
        #  A rule must point at something. One that names neither a row nor a label would match
        #  everybody or nobody, and which of those it meant would be anybody's guess.
        sa.CheckConstraint(
            "target_id IS NOT NULL OR length(btrim(coalesce(target_label, ''))) > 0",
            name="ck_job_rules_has_a_target",
        ),
        sa.CheckConstraint("position >= 1", name="ck_job_rules_position_positive"),
    )
    op.create_index("ix_job_assignment_rules_tenant_id", "job_assignment_rules", ["tenant_id"])
    op.create_index(
        "ix_job_rules_job", "job_assignment_rules", ["tenant_id", "job_id", "position"]
    )

    # ------------------------------------------------- §8: typed INPUT definitions

    op.create_table(
        "job_inputs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #  The workbook's "Input Type" list — Text / Form, Email, Excel, PDF, API Data …
        sa.Column("input_type", sa.String(length=60), nullable=False),
        #  Where it comes from, in the words of whoever provides it.
        sa.Column("source", sa.String(length=300), nullable=True),
        #  "Mandatory", "Optional" or "Conditional", from the sheet's "Input Status".
        sa.Column("requirement", sa.String(length=20), nullable=False, server_default="Optional"),
        #  When "Conditional", the condition. Refused without one below — a conditional input
        #  with no condition is an optional input that nobody can reason about.
        sa.Column("condition_note", sa.Text(), nullable=True),
        sa.Column("validation_note", sa.Text(), nullable=True),
        #  PLAN §19's vocabulary, not a new one, so the privacy controls can act on it.
        sa.Column(
            "classification", sa.String(length=40), nullable=False, server_default="internal"
        ),
        sa.Column("retention_note", sa.String(length=300), nullable=True),
        #  What a model may do with it. `none` by default, because the safe answer is the one
        #  that has to be chosen rather than the one that happens.
        sa.Column("ai_access", sa.String(length=20), nullable=False, server_default="none"),
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
        sa.PrimaryKeyConstraint("id", name="pk_job_inputs"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_job_inputs_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_inputs_tenant_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "job_id", "position", name="uq_job_inputs_position"),
        #  Two inputs with one name is two things a step could mean, and the step would pick
        #  whichever the query happened to return first.
        sa.UniqueConstraint("tenant_id", "job_id", "name", name="uq_job_inputs_name"),
        sa.CheckConstraint(
            f"requirement IN ({requirements})", name="ck_job_inputs_requirement_known"
        ),
        sa.CheckConstraint(
            f"classification IN ({classifications})",
            name="ck_job_inputs_classification_known",
        ),
        sa.CheckConstraint(f"ai_access IN ({ai_access})", name="ck_job_inputs_ai_access_known"),
        sa.CheckConstraint(
            "requirement <> 'Conditional' OR length(btrim(coalesce(condition_note, ''))) > 0",
            name="ck_job_inputs_conditional_has_condition",
        ),
        #  Personal data a model may write back is a combination that needs a decision nobody has
        #  made yet, so the schema refuses it rather than letting it happen by default.
        sa.CheckConstraint(
            "NOT (classification = 'personal_data' AND ai_access = 'read_write')",
            name="ck_job_inputs_no_ai_write_on_personal_data",
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_job_inputs_name_not_blank"),
        sa.CheckConstraint("position >= 1", name="ck_job_inputs_position_positive"),
    )
    op.create_index("ix_job_inputs_tenant_id", "job_inputs", ["tenant_id"])
    op.create_index("ix_job_inputs_job", "job_inputs", ["tenant_id", "job_id", "position"])

    # ------------------------------------------------------------ immutable versions

    op.create_table(
        "job_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("published_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_job_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_job_versions_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_versions_tenant_job",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "job_id", "version_no", name="uq_job_versions_no"),
    )
    for column, constraint in (
        ("published_by_membership_id", "fk_job_versions_tenant_publisher"),
        ("approved_by_membership_id", "fk_job_versions_tenant_approver"),
    ):
        op.execute(
            f"""
            ALTER TABLE job_versions
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column})
            """
        )
    op.create_index("ix_job_versions_tenant_id", "job_versions", ["tenant_id"])
    op.create_index("ix_job_versions_job", "job_versions", ["tenant_id", "job_id", "version_no"])
    op.execute(
        """
        ALTER TABLE jobs
            ADD CONSTRAINT fk_jobs_published_version
            FOREIGN KEY (published_version_id)
            REFERENCES job_versions (id)
            ON DELETE RESTRICT
        """
    )

    # -------------------------------------------------------------------- triggers

    op.execute(
        """
        CREATE OR REPLACE FUNCTION job_versions_assign_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.job_id::text, 0));
            SELECT COALESCE(MAX(version_no), 0) + 1 INTO NEW.version_no
                FROM job_versions
                WHERE job_id = NEW.job_id;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER job_versions_assign_number
            BEFORE INSERT ON job_versions
            FOR EACH ROW EXECUTE FUNCTION job_versions_assign_number();
        """
    )
    op.execute(
        """
        CREATE TRIGGER job_versions_append_only
            BEFORE UPDATE OR DELETE ON job_versions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    #  The same cycle rule as the objective's plan. A job whose step waits for itself can never
    #  run, and the topological sort that orders it would not terminate.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION job_step_deps_refuse_cycle() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            found boolean;
        BEGIN
            WITH RECURSIVE upstream AS (
                SELECT NEW.depends_on_step_id AS id, 1 AS depth
                UNION ALL
                SELECT d.depends_on_step_id, u.depth + 1
                FROM job_step_dependencies d
                JOIN upstream u ON d.step_id = u.id
                WHERE u.depth < 200
            )
            SELECT EXISTS (SELECT 1 FROM upstream WHERE id = NEW.step_id) INTO found;

            IF found THEN
                RAISE EXCEPTION
                    'step % would wait for itself through the chain', NEW.step_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER job_step_deps_refuse_cycle
            BEFORE INSERT OR UPDATE ON job_step_dependencies
            FOR EACH ROW EXECUTE FUNCTION job_step_deps_refuse_cycle();
        """
    )

    for table in ("jobs", "job_steps", "job_assignment_rules", "job_inputs"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )

    for table in (
        "jobs",
        "job_steps",
        "job_step_dependencies",
        "job_assignment_rules",
        "job_inputs",
        "job_versions",
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

    op.execute("REVOKE UPDATE, DELETE ON job_versions FROM uboss_app;")


def downgrade() -> None:
    """Drops jobs and every published version with them.

    Reversing this loses approved records of how work is done. It exists so the migration is
    reversible in development; against real data it needs an export first.
    """
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS fk_jobs_published_version")
    for table in (
        "job_versions",
        "job_inputs",
        "job_assignment_rules",
        "job_step_dependencies",
        "job_steps",
        "jobs",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS job_versions_assign_number()")
    op.execute("DROP FUNCTION IF EXISTS job_step_deps_refuse_cycle()")
