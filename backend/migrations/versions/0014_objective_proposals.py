"""The analysis run, the execution graph it proposes, and the events that actually happened.

PLAN §7: *"Claude proposes an execution graph with Human, AI Agent, Hybrid, Approval and Output
blocks. Users may add, edit, delete, duplicate, merge, reorder, change dependencies, compare
AI/human changes and rerun only a selected section."* And §6 puts a **real analysis timeline**
between approving the analysis and editing its output.

Three things this schema exists to make true:

**The timeline is real.** `objective_analysis_events` holds one row per stage, written as that
stage actually starts and finishes. `docs/delivery/WORK_BREAKDOWN.md` names the six:
`validate → context → workstreams → propose → policy → review`. A progress animation driven by a
timer would be indistinguishable on screen and would be a lie — `ui/README.md` forbids fake
progress, and this is the table that makes the honest version cheap.

**A proposal is never the graph.** The model's answer lands in `objective_proposals.output` and
stays there. Steps are created from it in the same transaction, marked `source = 'ai'`, and from
that moment they are ordinary editable rows. What the model said is kept unchanged beside them,
which is the only way §7's *"compare AI/human changes"* can be answered later.

**A dependency cannot close a loop.** The same trigger discipline as `org_units` and
`reporting_edges`: a cycle in an execution graph is a plan that can never start, and a topological
sort that never terminates.

Revision: 0014
Parent:   0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Where an analysis run has got to.
PROPOSAL_STATUSES: tuple[str, ...] = ("running", "succeeded", "failed", "superseded")

#: The six stages, in order. From `docs/delivery/WORK_BREAKDOWN.md`, not invented here.
STAGES: tuple[str, ...] = (
    "validate",
    "context",
    "workstreams",
    "propose",
    "policy",
    "review",
)

STAGE_STATES: tuple[str, ...] = ("running", "done", "failed", "skipped")

#: PLAN §7's block kinds, exactly. A closed list, because the runtime routes work by it: a
#: `human` block becomes somebody's to-do and an `ai_agent` block becomes a run.
STEP_KINDS: tuple[str, ...] = ("human", "ai_agent", "hybrid", "approval", "output")

#: Who put the step there. The distinction is what makes "compare AI/human changes" answerable.
STEP_SOURCES: tuple[str, ...] = ("ai", "human")


def upgrade() -> None:
    statuses = ", ".join(f"'{value}'" for value in PROPOSAL_STATUSES)
    stages = ", ".join(f"'{value}'" for value in STAGES)
    stage_states = ", ".join(f"'{value}'" for value in STAGE_STATES)
    kinds = ", ".join(f"'{value}'" for value in STEP_KINDS)
    sources = ", ".join(f"'{value}'" for value in STEP_SOURCES)

    # ------------------------------------------------------------------ the run

    op.create_table(
        "objective_proposals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        #  The stage it is on, or the one it failed at. Read by the screen while it runs.
        sa.Column("stage", sa.String(length=30), nullable=True),
        #  What the objective looked like when the analysis started. Kept because the person will
        #  keep editing, and "the plan was proposed for this" has to stay answerable.
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        #  The model's answer, exactly as it validated. Never edited — the steps created from it
        #  are, and comparing the two is what §7's "compare AI/human changes" means.
        sa.Column("output", postgresql.JSONB(), nullable=True),
        #  Which model, and what it cost. Recorded rather than assumed, so an audit can answer
        #  "which model produced this" after policy changes.
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        #  In the person's words, and shown to them. Null unless `status = 'failed'`.
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("requested_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_objective_proposals"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_proposals_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_proposals_tenant_objective",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_proposals_tenant_id"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_proposals_status_known"),
        sa.CheckConstraint(
            f"stage IS NULL OR stage IN ({stages})", name="ck_proposals_stage_known"
        ),
        #  A failed run must say why. Without this a row could report failure with nothing a
        #  person could read, which is the same as reporting nothing.
        sa.CheckConstraint(
            "(status <> 'failed') OR (failure_detail IS NOT NULL)",
            name="ck_proposals_failure_has_reason",
        ),
        sa.CheckConstraint(
            "(status = 'running') OR (finished_at IS NOT NULL)",
            name="ck_proposals_finished_when_over",
        ),
    )
    op.execute(
        """
        ALTER TABLE objective_proposals
            ADD CONSTRAINT fk_proposals_tenant_requester
            FOREIGN KEY (tenant_id, requested_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (requested_by_membership_id)
        """
    )
    op.create_index("ix_objective_proposals_tenant_id", "objective_proposals", ["tenant_id"])
    op.create_index(
        "ix_proposals_objective", "objective_proposals", ["tenant_id", "objective_id"]
    )
    #  One analysis at a time per objective. Two concurrent runs would each write steps, and the
    #  person would be looking at a graph made of halves of two different plans.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_proposals_one_running
            ON objective_proposals (objective_id)
            WHERE status = 'running';
        """
    )

    # ------------------------------------------------------- the real timeline

    op.create_table(
        "objective_analysis_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        #  One line a person can read. Not a log line — this is shown on screen.
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_objective_analysis_events"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_analysis_events_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["objective_proposals.tenant_id", "objective_proposals.id"],
            name="fk_analysis_events_tenant_proposal",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"stage IN ({stages})", name="ck_analysis_events_stage_known"),
        sa.CheckConstraint(f"state IN ({stage_states})", name="ck_analysis_events_state_known"),
    )
    op.create_index(
        "ix_objective_analysis_events_tenant_id", "objective_analysis_events", ["tenant_id"]
    )
    op.create_index(
        "ix_analysis_events_proposal",
        "objective_analysis_events",
        ["tenant_id", "proposal_id", "at"],
    )

    # --------------------------------------------------- the execution graph

    op.create_table(
        "objective_steps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  The run that first proposed this step, or null once a person adds one by hand.
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        #  Who or what does it. A role rather than a person: an objective is published once and
        #  run many times, and the person in a seat changes.
        sa.Column("responsible_role", sa.String(length=200), nullable=True),
        #  Which of the workbook's current-process steps this replaces. Null when the proposal
        #  introduces work that did not exist — a check nobody was doing, for instance.
        sa.Column("replaces_current_step", sa.Integer(), nullable=True),
        #  Why the model put it there, in its own words. Shown beside the step, so a person
        #  reviewing a plan can see the reasoning rather than only the conclusion.
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="ai"),
        #  True once a person has changed an AI-proposed step. This is the "compare AI/human
        #  changes" flag: `source = 'ai' AND edited` is precisely a step the model proposed and a
        #  human corrected.
        sa.Column("edited", sa.Boolean(), nullable=False, server_default="false"),
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
        sa.PrimaryKeyConstraint("id", name="pk_objective_steps"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_objective_steps_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_objective_steps_tenant_objective",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["objective_proposals.tenant_id", "objective_proposals.id"],
            name="fk_objective_steps_tenant_proposal",
            #  SET NULL rather than CASCADE: deleting a superseded proposal must not take the
            #  steps a person has since edited. They stop knowing which run proposed them, which
            #  is a smaller loss than losing the work.
            ondelete="SET NULL (proposal_id)",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_objective_steps_tenant_id"),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_objective_steps_kind_known"),
        sa.CheckConstraint(f"source IN ({sources})", name="ck_objective_steps_source_known"),
        sa.CheckConstraint("position >= 1", name="ck_objective_steps_position_positive"),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name="ck_objective_steps_title_not_blank"
        ),
    )
    op.create_index("ix_objective_steps_tenant_id", "objective_steps", ["tenant_id"])
    op.create_index(
        "ix_objective_steps_objective", "objective_steps", ["tenant_id", "objective_id", "position"]
    )

    op.create_table(
        "objective_step_dependencies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  The step that waits.
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  The step it waits for.
        sa.Column("depends_on_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_objective_step_dependencies"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_step_deps_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "step_id"],
            ["objective_steps.tenant_id", "objective_steps.id"],
            name="fk_step_deps_tenant_step",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "depends_on_step_id"],
            ["objective_steps.tenant_id", "objective_steps.id"],
            name="fk_step_deps_tenant_target",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "step_id", "depends_on_step_id", name="uq_step_deps_pair"
        ),
        sa.CheckConstraint(
            "step_id <> depends_on_step_id", name="ck_step_deps_not_self"
        ),
    )
    op.create_index(
        "ix_objective_step_dependencies_tenant_id", "objective_step_dependencies", ["tenant_id"]
    )
    op.create_index(
        "ix_step_deps_step", "objective_step_dependencies", ["tenant_id", "step_id"]
    )

    # -------------------------------------------------------------- triggers

    #  A plan that waits for itself can never start, and the topological sort that orders the run
    #  would not terminate. Refused in the database for the same reason as every other cycle in
    #  this schema: a bulk path — an imported plan, a duplicated section — can be written around
    #  a check in the service.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION step_deps_refuse_cycle() RETURNS trigger
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
                FROM objective_step_dependencies d
                JOIN upstream u ON d.step_id = u.id
                --  A depth guard as well as the equality test below. If a loop were already in
                --  the table from some future bug, the walk would not end and this trigger would
                --  hang every write to it.
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
        CREATE TRIGGER step_deps_refuse_cycle
            BEFORE INSERT OR UPDATE ON objective_step_dependencies
            FOR EACH ROW EXECUTE FUNCTION step_deps_refuse_cycle();
        """
    )

    op.execute(
        """
        CREATE TRIGGER objective_steps_set_updated_at
            BEFORE UPDATE ON objective_steps
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    #  The timeline is evidence of what happened, so it is append-only like the audit trail. A
    #  stage that could be rewritten afterwards is a stage nobody can rely on.
    op.execute(
        """
        CREATE TRIGGER objective_analysis_events_append_only
            BEFORE UPDATE OR DELETE ON objective_analysis_events
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    for table in (
        "objective_proposals",
        "objective_analysis_events",
        "objective_steps",
        "objective_step_dependencies",
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

    op.execute("REVOKE UPDATE, DELETE ON objective_analysis_events FROM uboss_app;")


def downgrade() -> None:
    """Drops the analyses and the graphs they proposed. The objectives themselves stay."""
    op.execute("DROP TABLE IF EXISTS objective_step_dependencies CASCADE")
    op.execute("DROP TABLE IF EXISTS objective_steps CASCADE")
    op.execute("DROP TABLE IF EXISTS objective_analysis_events CASCADE")
    op.execute("DROP TABLE IF EXISTS objective_proposals CASCADE")
    op.execute("DROP FUNCTION IF EXISTS step_deps_refuse_cycle()")
