"""Runs — the first thing in Gate 7, because nothing else in the gate exists without it.

Every gate so far produced immutable versions nobody could execute. `ObjectiveVersion`,
`JobVersion`, `AgentVersion` and `SupervisorVersion` are published and pinned and inert; the
sidebar has said `SOON` beside *To-do list* since Gate 1 because there was nothing to put in it.
This is the table that turns a published version into something that happens.

## Three tables, and why they are three

**`runs`** — one execution of one pinned version. It carries `job_version_id`, never `job_id`:
`CLAUDE.md` says *"Operation runs only approved, immutable `WorkflowVersion` and `AgentVersion`
objects"*, and a run that read the draft would change under itself the moment somebody edited the
Job. A foreign key to the version table is that rule expressed where it cannot be forgotten.

**`run_steps`** — one row per step of that version. It is the unit a person is assigned, a
supervisor watches, a retry replays and a screen shows. Kept separate from `runs` rather than as
JSON inside it, because every one of those is a query: *"what is assigned to me"*, *"which steps
are waiting on approval"*, *"which step failed"*. JSON would make each of them a scan.

**`run_events`** — append-only, the same shape and the same trigger as `audit_events`. What
happened, in order, with the correlation id of the request that caused it. This is what a run's
evidence is made of in 7.6, and evidence that can be rewritten is not evidence.

## What makes it durable

`workflow_id` is written **before** the workflow starts and is unique per tenant. A crash between
the row and the start leaves a row in `pending` that a reconciler can finish or fail; a crash the
other way round is impossible, because Temporal is asked to start with that exact id and a second
attempt with the same id is refused rather than duplicated.

`attempt` on a step counts activity attempts, so a retry is visible rather than silent. And every
external effect a step performs is keyed on `(run_id, step_id)` — the same rule the browser client
already keeps, applied to the runtime, so a replayed activity does not send a second email.

## What is deliberately absent

**No status enum for "cancelled by whom".** Cancellation is an event in `run_events` with an
actor, like every other decision. A column would record that it happened and lose who did it.

**No `output` column on `runs`.** A run's result is the result of its last step, and a second
place to write it is a second place for the two to disagree.

Revision: 0029
Parent:   0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: What a run can be. `pending` exists for the gap between the row and the workflow start — see
#: the module docstring. `waiting` is a run whose current step needs a person.
RUN_STATES = ("pending", "running", "waiting", "succeeded", "failed", "cancelled")

#: What one step can be. `skipped` is a step a condition ruled out, which is not a failure and
#: must not be counted as one.
STEP_STATES = ("pending", "running", "waiting", "succeeded", "failed", "skipped", "cancelled")

#: Who or what started a run. Recorded because "why did this run" is the first question asked
#: about an unexpected one, and a schedule and a person are different answers.
TRIGGERS = ("manual", "schedule", "supervisor", "api")


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        #  The version, not the job. See the module docstring — this is the immutability boundary.
        sa.Column("job_version_id", pg.UUID(as_uuid=True), nullable=False),
        #  Denormalised so the list of runs for a Job does not have to join through versions.
        #  Safe to denormalise because a version's job never changes.
        sa.Column("job_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workflow_id",
            sa.String(200),
            nullable=False,
            comment="Temporal's id for this run. Written before the workflow starts.",
        ),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("trigger", sa.String(20), nullable=False),
        #  Null for a scheduled run: nobody started it, and naming the person who wrote the
        #  schedule would be recording an approval nobody gave.
        sa.Column("started_by_membership_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        #  The reason, in the words a person will read. Null while it is going.
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "state IN " + str(RUN_STATES).replace("'", "'"), name="ck_runs_state"
        ),
        sa.CheckConstraint(
            "trigger IN " + str(TRIGGERS).replace("'", "'"), name="ck_runs_trigger"
        ),
        #  A finished run has a finish time and an unfinished one does not. Without this a row can
        #  say `succeeded` with no `finished_at`, and every duration on every screen becomes a
        #  guess.
        sa.CheckConstraint(
            "(state IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL)",
            name="ck_runs_finished_at_matches_state",
        ),
        #  A failure says why. A `failed` row with no detail is a support ticket.
        sa.CheckConstraint(
            "state <> 'failed' OR failure_detail IS NOT NULL",
            name="ck_runs_failure_has_detail",
        ),
        #  What makes the composite foreign keys below possible: a child cannot point at a row in
        #  another tenant, because the key it points at carries the tenant. The pattern every
        #  table in this schema uses.
        sa.UniqueConstraint("tenant_id", "id", name="uq_runs_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_version_id"],
            ["job_versions.tenant_id", "job_versions.id"],
            name="fk_runs_job_version",
            ondelete="RESTRICT",
        ),
    )
    #  Unique per tenant rather than globally: the id embeds the tenant, and a global constraint
    #  would let one customer's run id collide with another's and reveal that it had.
    op.create_index("uq_runs_workflow_id", "runs", ["tenant_id", "workflow_id"], unique=True)
    op.create_index("ix_runs_tenant_state", "runs", ["tenant_id", "state"])
    op.create_index("ix_runs_tenant_job", "runs", ["tenant_id", "job_id", "created_at"])

    op.create_table(
        "run_steps",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False),
        #  1-based, and its order is the version's order. Not the step's own id from the snapshot:
        #  a run is a sequence, and a sequence is addressed by position.
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        #  human, ai_agent or hybrid — §9's work mode, copied from the version so the run does not
        #  have to re-read a snapshot to know who does this step.
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        #  Counts activity attempts, so a retry is visible rather than silent.
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        #  What the step produced, as the step described it. `jsonb` because its shape is the
        #  step's, not this table's.
        sa.Column("result", pg.JSONB(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "state IN " + str(STEP_STATES).replace("'", "'"), name="ck_run_steps_state"
        ),
        sa.CheckConstraint("position >= 1", name="ck_run_steps_position"),
        sa.CheckConstraint("attempt >= 0", name="ck_run_steps_attempt"),
        sa.CheckConstraint(
            "state <> 'failed' OR failure_detail IS NOT NULL",
            name="ck_run_steps_failure_has_detail",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        #  Composite, so a step cannot be attached to a run in another tenant even if somebody
        #  writes the id by hand. The pattern every table in this schema uses.
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_run_steps_run",
            ondelete="CASCADE",
        ),
    )
    op.create_index("uq_run_steps_position", "run_steps", ["run_id", "position"], unique=True)
    op.create_index("ix_run_steps_tenant_state", "run_steps", ["tenant_id", "state"])

    op.create_table(
        "run_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False),
        #  Null for an event about the run itself rather than one of its steps.
        sa.Column("run_step_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("detail", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        #  Who, when it was a person. Null for the runtime's own events, which is most of them.
        sa.Column("actor_membership_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_run_events_run",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_run_events_run", "run_events", ["run_id", "occurred_at"])

    # ── row-level security ───────────────────────────────────────────────────────────────
    #
    # The same two-layer boundary every table has: the backend authorises, and the database
    # refuses anything the bound tenant does not own. Neither substitutes for the other.
    for table in ("runs", "run_steps", "run_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )

    op.execute("GRANT SELECT, INSERT, UPDATE ON runs TO uboss_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON run_steps TO uboss_app")
    #  Insert and select only. `run_events` is the evidence, and evidence that can be updated is
    #  a record of what somebody last decided it should say.
    op.execute("GRANT SELECT, INSERT ON run_events TO uboss_app")
    op.execute(
        """
        CREATE TRIGGER trg_run_events_append_only
        BEFORE UPDATE OR DELETE ON run_events
        FOR EACH ROW EXECUTE FUNCTION refuse_change()
        """
    )

    #  The relay reads outbox rows across tenants; run events are a tenant's own and it has no
    #  business in them. Stated by omission — the grant simply is not made.


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_run_events_append_only ON run_events")
    op.drop_table("run_events")
    op.drop_table("run_steps")
    op.drop_table("runs")
