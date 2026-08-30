"""`PLAN.md` §10's form groups 4 to 9 — order, dependency, quality, budget, escalation, reports.

Groups 1 to 3 are migration 0023 (identity, and the two scopes). Group 10 is the publish gate and
belongs with the thing it guards, in 6.4. These six are what a Supervisor *does* once it has a
scope, and §10's capability list corroborates every one of them:

> Start eligible dependency-ready work … Track SLA, deadline, cost, tokens and concurrency …
> Detect quality/policy problems … Escalate to configured people … Combine results into an
> Objective report … Notify handlers and stakeholders.

**Execution order needed no column.** §10 group 4 asks for it, and `supervisor_supervised.position`
already is it — the order the supervised set is listed in. A second column would have been a
second answer to one question.

**The schedule reuses the Job's recurrence, it does not copy it.** `jobs/recurrence.py` already
solves timezones, DST gaps and ambiguity, missed runs and overlap, and it is pure — no database
anywhere in it. `supervisor_schedules` therefore carries the same columns so the same code reads
them. A second implementation of DST handling is a second set of bugs at the clock change.

**Where the plan names no vocabulary, none is invented.** §10 says *"routing policy"* and does not
say what the choices are, so `routing_policy` is free text and
`docs/architecture/SUPERVISOR_FIELDS.md` records that as an open question rather than a finished
field — the same treatment `agents.model_policy_key` got for the same reason.

**Nothing here executes anything.** The runtime is Gate 7. These are the governed settings a run
will be bound by; a Supervisor cannot start, pause or retry anything yet, and 6.5 shows those
controls disabled and labelled rather than working.

Revision: 0024
Parent:   0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the values `jobs/recurrence.py` parses at this revision, and nothing more. Written out
#: rather than imported, because a migration must keep meaning what it meant when it ran — but
#: written out *correctly*: the first draft of this list invented `yearly`, `strict`, `second` and
#: `queue_one`, none of which the module understands. A column that can hold a value the reader
#: cannot parse is the exact drift this table was built to avoid, and a test now compares the two.
FREQUENCIES: tuple[str, ...] = ("hourly", "daily", "weekly", "monthly")
DST_POLICIES: tuple[str, ...] = ("skip", "shift")
AMBIGUOUS_POLICIES: tuple[str, ...] = ("first", "both")
MISSED_RUN_POLICIES: tuple[str, ...] = ("skip", "run_once", "run_all")
OVERLAP_POLICIES: tuple[str, ...] = ("skip", "queue", "allow")

#: What a quality gate does when it does not hold. §10 group 6 pairs gates with evidence, and a
#: gate with no stated consequence is an observation rather than a gate.
ON_FAILURE: tuple[str, ...] = ("block", "escalate", "flag_and_continue")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    # ---------------------------------------------------------------- groups 4, 5, 7 and 8
    for column in (
        #  Group 4 — the trigger. The workbook's list, so text rather than an enum: every one of
        #  its lists ends in `Other`.
        sa.Column("trigger", sa.String(length=120), nullable=True),
        #  Group 5 — routing. §10 names no choices, so this is free text until somebody approves
        #  a vocabulary. Recorded as an open question rather than filled with guesses.
        sa.Column("routing_policy", sa.Text(), nullable=True),
        sa.Column("max_concurrency", sa.Integer(), nullable=True),
        #  Group 7 — *"Track SLA, deadline, cost, tokens and concurrency."* Null means the
        #  workspace policy decides; a number here is this Supervisor's own ceiling and a run
        #  never raises it.
        sa.Column("cost_cap_minor_units", sa.Integer(), nullable=True),
        sa.Column("cost_cap_currency", sa.String(length=3), nullable=True),
        sa.Column("token_cap", sa.Integer(), nullable=True),
        sa.Column("sla_minutes", sa.Integer(), nullable=True),
        sa.Column("deadline_minutes", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        #  A retry with no wait is a retry that hits a struggling system harder. Null means the
        #  workspace default rather than zero, which would mean "immediately".
        sa.Column("retry_backoff_seconds", sa.Integer(), nullable=True),
        #  Group 8 — who approves, and who hears about a failure. A membership where the person
        #  is known, a label where a role was named.
        sa.Column("approver_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approver_label", sa.String(length=200), nullable=True),
        sa.Column("escalation_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("escalation_label", sa.String(length=200), nullable=True),
    ):
        op.add_column("supervisors", column)

    for column, constraint in (
        ("approver_membership_id", "fk_supervisors_approver"),
        ("escalation_membership_id", "fk_supervisors_escalation"),
    ):
        op.execute(
            f"""
            ALTER TABLE supervisors
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column});
            """
        )

    for name, expression in (
        ("ck_supervisors_concurrency", "max_concurrency IS NULL OR max_concurrency >= 1"),
        ("ck_supervisors_token_cap", "token_cap IS NULL OR token_cap > 0"),
        ("ck_supervisors_sla", "sla_minutes IS NULL OR sla_minutes > 0"),
        ("ck_supervisors_deadline", "deadline_minutes IS NULL OR deadline_minutes > 0"),
        ("ck_supervisors_retries", "max_retries IS NULL OR max_retries >= 0"),
        (
            "ck_supervisors_backoff",
            "retry_backoff_seconds IS NULL OR retry_backoff_seconds >= 0",
        ),
        (
            "ck_supervisors_cost_cap",
            "cost_cap_minor_units IS NULL OR cost_cap_minor_units >= 0",
        ),
        #  A cost is a number and a currency, or it is neither. "12" with no currency is not a cap.
        (
            "ck_supervisors_cost_currency",
            "(cost_cap_minor_units IS NULL) = (cost_cap_currency IS NULL)",
        ),
        #  A deadline inside the SLA is two promises that contradict each other.
        (
            "ck_supervisors_deadline_after_sla",
            "sla_minutes IS NULL OR deadline_minutes IS NULL OR deadline_minutes >= sla_minutes",
        ),
    ):
        op.create_check_constraint(name, "supervisors", expression)

    # ---------------------------------------------------------------- group 4: the schedule
    op.create_table(
        "supervisor_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Off until somebody turns it on. §8's schedule made the same choice for the same reason:
        #  a schedule that starts firing because a form was saved is a schedule nobody agreed to.
        sa.Column("auto_run", sa.Boolean(), nullable=False, server_default="false"),
        #  The same columns as `job_schedules`, so `jobs/recurrence.py` reads them unchanged.
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("at_time", sa.Time(), nullable=False),
        sa.Column("weekdays", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("monthday", sa.Integer(), nullable=True),
        sa.Column("dst_policy", sa.String(length=10), nullable=False, server_default="shift"),
        sa.Column(
            "ambiguous_policy", sa.String(length=10), nullable=False, server_default="first"
        ),
        sa.Column("skip_dates", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("weekdays_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "missed_run_policy", sa.String(length=20), nullable=False, server_default="skip"
        ),
        #  The plan's decision table: *"Schedule overlap | Queue one run."* `job_schedules`
        #  defaults to `skip` instead, which is a divergence from that recommendation worth
        #  raising rather than copying.
        sa.Column(
            "overlap_policy", sa.String(length=20), nullable=False, server_default="queue"
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_schedules"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sup_schedules_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_schedules_supervisor",
            ondelete="CASCADE",
        ),
        #  One schedule per Supervisor. Two would be two answers to "when does this run".
        sa.UniqueConstraint(
            "tenant_id", "supervisor_id", name="uq_sup_schedules_supervisor"
        ),
        sa.CheckConstraint(
            f"frequency IN ({_quoted(FREQUENCIES)})", name="ck_sup_schedules_frequency"
        ),
        sa.CheckConstraint(
            f"dst_policy IN ({_quoted(DST_POLICIES)})", name="ck_sup_schedules_dst"
        ),
        sa.CheckConstraint(
            f"ambiguous_policy IN ({_quoted(AMBIGUOUS_POLICIES)})",
            name="ck_sup_schedules_ambiguous",
        ),
        sa.CheckConstraint(
            f"missed_run_policy IN ({_quoted(MISSED_RUN_POLICIES)})",
            name="ck_sup_schedules_missed",
        ),
        sa.CheckConstraint(
            f"overlap_policy IN ({_quoted(OVERLAP_POLICIES)})", name="ck_sup_schedules_overlap"
        ),
        sa.CheckConstraint('"interval" >= 1', name="ck_sup_schedules_interval"),
        sa.CheckConstraint(
            "monthday IS NULL OR (monthday >= 1 AND monthday <= 31)",
            name="ck_sup_schedules_monthday",
        ),
    )

    # ---------------------------------------------------------------- group 5: dependencies
    op.create_table(
        "supervisor_dependencies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Both sides are rows of the supervised set, so a dependency can only ever be between two
        #  things this Supervisor actually watches.
        sa.Column("supervised_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("depends_on_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_dependencies"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sup_deps_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_deps_supervisor",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supervised_id"],
            ["supervisor_supervised.id"],
            name="fk_sup_deps_supervised",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_id"],
            ["supervisor_supervised.id"],
            name="fk_sup_deps_depends_on",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "supervised_id", "depends_on_id", name="uq_sup_deps_pair"
        ),
        sa.CheckConstraint(
            "supervised_id <> depends_on_id", name="ck_sup_deps_not_itself"
        ),
    )

    # ---------------------------------------------------------------- group 6: quality gates
    op.create_table(
        "supervisor_quality_gates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #  What has to hold. Free text: §10 names no expression language and inventing one would
        #  be inventing a product.
        sa.Column("condition", sa.Text(), nullable=False),
        #  §10 pairs quality with *evidence*. What proves the gate held, in the same words a
        #  reviewer would use.
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("on_failure", sa.String(length=30), nullable=False, server_default="escalate"),
        sa.Column("position", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_quality_gates"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sup_gates_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_gates_supervisor",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "supervisor_id", "name", name="uq_sup_gates_name"),
        sa.CheckConstraint(
            f"on_failure IN ({_quoted(ON_FAILURE)})", name="ck_sup_gates_on_failure"
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_sup_gates_name_not_blank"),
        sa.CheckConstraint(
            "length(btrim(condition)) > 0", name="ck_sup_gates_condition_not_blank"
        ),
        sa.CheckConstraint("position >= 1", name="ck_sup_gates_position"),
    )

    # ---------------------------------------------------------------- group 8: escalation
    op.create_table(
        "supervisor_escalations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Free text, because §10 prints no list of situations the way Form 4 section B does. A
        #  closed set here would be six situations somebody invented.
        sa.Column("situation", sa.String(length=200), nullable=False),
        sa.Column("required_action", sa.Text(), nullable=False),
        sa.Column("escalate_to_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("escalate_to_label", sa.String(length=200), nullable=True),
        #  How long before it escalates. Null means immediately.
        sa.Column("after_minutes", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_escalations"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sup_esc_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_esc_supervisor",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "supervisor_id", "situation", name="uq_sup_esc_situation"
        ),
        sa.CheckConstraint(
            "length(btrim(situation)) > 0", name="ck_sup_esc_situation_not_blank"
        ),
        sa.CheckConstraint(
            "length(btrim(required_action)) > 0", name="ck_sup_esc_action_not_blank"
        ),
        #  An escalation that names nobody is a rule with no addressee.
        sa.CheckConstraint(
            "escalate_to_membership_id IS NOT NULL OR escalate_to_label IS NOT NULL",
            name="ck_sup_esc_names_somebody",
        ),
        sa.CheckConstraint(
            "after_minutes IS NULL OR after_minutes >= 0", name="ck_sup_esc_after"
        ),
        sa.CheckConstraint("position >= 1", name="ck_sup_esc_position"),
    )
    op.execute(
        """
        ALTER TABLE supervisor_escalations
            ADD CONSTRAINT fk_sup_esc_escalate_to
            FOREIGN KEY (tenant_id, escalate_to_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (escalate_to_membership_id);
        """
    )

    # ---------------------------------------------------------------- group 9: notifications
    op.create_table(
        "supervisor_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  What happened. Free text for the same reason as a situation.
        sa.Column("event", sa.String(length=200), nullable=False),
        #  Where it goes. §10 says *"Notify handlers and stakeholders"* and names no channels, so
        #  this is text until a channel catalogue exists — Gate 7 brings the outbox that would
        #  define one.
        sa.Column("channel", sa.String(length=60), nullable=True),
        #  Whether every handler hears about it, alongside anyone named below. Handlers are who
        #  §10 says to notify, so this defaults on.
        sa.Column(
            "to_handlers", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("recipient_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_label", sa.String(length=200), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_notifications"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sup_notify_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_notify_supervisor",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "supervisor_id", "event", name="uq_sup_notify_event"),
        sa.CheckConstraint("length(btrim(event)) > 0", name="ck_sup_notify_event_not_blank"),
        #  A notification going to nobody is a setting that does nothing.
        sa.CheckConstraint(
            "to_handlers OR recipient_membership_id IS NOT NULL OR recipient_label IS NOT NULL",
            name="ck_sup_notify_has_a_recipient",
        ),
        sa.CheckConstraint("position >= 1", name="ck_sup_notify_position"),
    )
    op.execute(
        """
        ALTER TABLE supervisor_notifications
            ADD CONSTRAINT fk_sup_notify_recipient
            FOREIGN KEY (tenant_id, recipient_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (recipient_membership_id);
        """
    )

    #  ------------------------------------------------------------- no circular dependency
    #
    #  The same rule as the Job's steps and the Objective's plan, for the same reason: a set of
    #  agents that each wait for the next can never start, and the topological order that would
    #  schedule them does not terminate. Refused at the point of writing rather than found by a
    #  run that hangs.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION supervisor_deps_refuse_cycle() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            found boolean;
        BEGIN
            WITH RECURSIVE upstream AS (
                SELECT NEW.depends_on_id AS id, 1 AS depth
                UNION ALL
                SELECT d.depends_on_id, u.depth + 1
                  FROM supervisor_dependencies d
                  JOIN upstream u ON d.supervised_id = u.id
                 WHERE u.depth < 100
            )
            SELECT EXISTS (SELECT 1 FROM upstream WHERE id = NEW.supervised_id) INTO found;

            IF found THEN
                RAISE EXCEPTION
                    'that dependency would create a cycle: nothing in it could ever start';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER supervisor_deps_refuse_cycle
            BEFORE INSERT OR UPDATE ON supervisor_dependencies
            FOR EACH ROW EXECUTE FUNCTION supervisor_deps_refuse_cycle();
        """
    )

    for table in (
        "supervisor_schedules",
        "supervisor_dependencies",
        "supervisor_quality_gates",
        "supervisor_escalations",
        "supervisor_notifications",
    ):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
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


def downgrade() -> None:
    for table in (
        "supervisor_notifications",
        "supervisor_escalations",
        "supervisor_quality_gates",
        "supervisor_dependencies",
        "supervisor_schedules",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS supervisor_deps_refuse_cycle()")

    for name in (
        "ck_supervisors_concurrency",
        "ck_supervisors_token_cap",
        "ck_supervisors_sla",
        "ck_supervisors_deadline",
        "ck_supervisors_retries",
        "ck_supervisors_backoff",
        "ck_supervisors_cost_cap",
        "ck_supervisors_cost_currency",
        "ck_supervisors_deadline_after_sla",
    ):
        op.execute(f"ALTER TABLE supervisors DROP CONSTRAINT IF EXISTS {name}")
    op.execute("ALTER TABLE supervisors DROP CONSTRAINT IF EXISTS fk_supervisors_approver")
    op.execute("ALTER TABLE supervisors DROP CONSTRAINT IF EXISTS fk_supervisors_escalation")
    for column in (
        "trigger",
        "routing_policy",
        "max_concurrency",
        "cost_cap_minor_units",
        "cost_cap_currency",
        "token_cap",
        "sla_minutes",
        "deadline_minutes",
        "max_retries",
        "retry_backoff_seconds",
        "approver_membership_id",
        "approver_label",
        "escalation_membership_id",
        "escalation_label",
    ):
        op.drop_column("supervisors", column)
