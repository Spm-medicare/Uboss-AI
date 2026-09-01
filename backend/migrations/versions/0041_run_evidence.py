"""What a run produced, and what it asked a model — 7.6's two missing tables.

`PLAN.md` §17 names the runtime's tables: *"runs, run steps, tasks, approvals, schedules, outputs,
evidence, model calls and tool calls."* Gate 7.1 built runs, run steps and run events; 7.2 and 7.3
built tasks, their evidence and approvals; 7.4 built schedules. Three were left, and this migration
adds the two that have something to record.

## `run_outputs` — what a run produced

`run_steps.result` is a JSONB blob, which is the right shape for a step's own bookkeeping and the
wrong one for evidence: nothing can be listed, counted, or opened from it, and a file a run produced
has nowhere to be. Form 3 gives every step an **Output** and an **Output Destination** by name, so
a produced thing already has a name in the design; this is where it gets a value.

A file is a join to `files`, never a second copy of one — the same rule `task_evidence` keeps.

## `model_calls` — what was asked, and what it cost

The gateway already writes an audit event for every call, including the refusals, and that stays:
*"we asked and got nothing"* and *"we never asked"* are different facts. But an audit event has no
`run_id`, so a model call made inside a run could not be attributed to it. *"What did this run cost,
and which of its steps used a model"* was unanswerable, which is most of what 7.6 is for.

**No prompt or response text.** The gateway's own comment gives the reason and it has not changed:
*"it can carry personal data, and an audit trail is not the place to duplicate it."* What a run
**read** is recorded as its inputs and the step results it consumed, not as a transcript.

## What is deliberately not here: `tool_calls`

§17 names them, and `integrations/` is an empty package — nothing external is wired until Gate 8,
which the Job Builder's own tools panel says on screen. A table with no producer is the defect this
audit already found twice: `job_step_dependencies` is constructed nowhere, and the Supervisor's
policy lists were sent as constants for months. So the table arrives with the integrations that
fill it, and 7.6's export names the gap instead of showing an empty section.

Revision: 0041
Parent:   0040
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "uboss_app"


def upgrade() -> None:
    #  A composite foreign key needs a unique constraint on exactly the columns it names, and
    #  `run_steps` has never been referenced before, so it never needed one. `runs` and `files`
    #  already carry theirs from the migrations that first pointed at them.
    op.create_unique_constraint("uq_run_steps_tenant_id", "run_steps", ["tenant_id", "id"])

    # ── run_outputs ──────────────────────────────────────────────────────────────────────
    op.create_table(
        "run_outputs",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        #  Null for an output of the run as a whole rather than of one step.
        sa.Column("run_step_id", UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        #  The design's own words. Form 3 column L is `Output` and column M is
        #  `Output Destination`, so a produced thing is already named before it exists.
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("destination", sa.String(200), nullable=True),
        sa.Column("output_format", sa.String(60), nullable=True),
        #  One of the two, or both: a value somebody can read, and a file they can open.
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("file_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "produced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_run_outputs_tenant", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_run_outputs_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_step_id"],
            ["run_steps.tenant_id", "run_steps.id"],
            name="fk_run_outputs_step",
            ondelete="CASCADE",
        ),
        #  A file is joined, never copied. The same rule `task_evidence` keeps, for the same
        #  reason: two copies of a file are two answers to "what was produced".
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["files.tenant_id", "files.id"],
            name="fk_run_outputs_file",
        ),
        #  An output with neither a value nor a file records that something was produced and does
        #  not say what, which is worse than not recording it.
        sa.CheckConstraint(
            "value_text IS NOT NULL OR file_id IS NOT NULL",
            name="ck_run_outputs_has_something",
        ),
        sa.UniqueConstraint("run_id", "position", name="uq_run_outputs_position"),
    )
    op.create_index("ix_run_outputs_tenant", "run_outputs", ["tenant_id"])
    op.create_index("ix_run_outputs_run", "run_outputs", ["run_id", "position"])

    # ── model_calls ──────────────────────────────────────────────────────────────────────
    op.create_table(
        "model_calls",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        #  Both null for a call made outside a run — an objective's analysis, say. The table is
        #  the runtime's record of model use, not only a run's.
        sa.Column("run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("run_step_id", UUID(as_uuid=True), nullable=True),
        sa.Column("task_kind", sa.String(60), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        #  `completed` or `unavailable`. Recorded separately from the token counts because a
        #  refusal has none, and a row with zeroes would read as a call that returned nothing.
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("actor_membership_id", UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_model_calls_tenant", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_model_calls_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_step_id"],
            ["run_steps.tenant_id", "run_steps.id"],
            name="fk_model_calls_step",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'unavailable')", name="ck_model_calls_outcome"
        ),
        #  A completed call reports what it used; an unavailable one says why. Neither shape is
        #  optional, because a row that is silent on both is a row nobody can act on.
        sa.CheckConstraint(
            "(outcome = 'completed' AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL)"
            " OR (outcome = 'unavailable' AND detail IS NOT NULL)",
            name="ck_model_calls_says_what_happened",
        ),
        #  A step is inside a run. A row naming a step and no run would be unattributable.
        sa.CheckConstraint(
            "run_step_id IS NULL OR run_id IS NOT NULL", name="ck_model_calls_step_has_run"
        ),
    )
    op.create_index("ix_model_calls_tenant", "model_calls", ["tenant_id"])
    op.create_index("ix_model_calls_run", "model_calls", ["run_id", "occurred_at"])
    op.create_index("ix_model_calls_when", "model_calls", ["tenant_id", "occurred_at"])

    # ── row-level security ───────────────────────────────────────────────────────────────
    #
    # The same two-layer boundary every table has: the backend authorises, and the database
    # refuses anything the bound tenant does not own. Neither substitutes for the other.
    #
    # `app_current_tenant()` rather than a raw cast of the setting. The two differ only on a
    # connection that never bound a tenant: the helper returns NULL and the comparison yields no
    # rows, while the cast raises on the empty string. Migration 0031 exists because 0029 used the
    # cast — *"the run tables' policies raised where every other table's returns nothing"* — and
    # this copied 0029 before noticing 0031 had corrected it. `test_nothing_is_visible_without_a_
    # bound_tenant` caught it, which is the whole reason that test walks every table.
    for table in ("run_outputs", "model_calls"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant())
            """
        )

    #  Insert and select only, on both. These are evidence, and evidence that can be updated is a
    #  record of what somebody last decided it should say — the reason `run_events` is append-only
    #  and the same reason here.
    for table in ("run_outputs", "model_calls"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION refuse_change()
            """
        )

    #  The relay reads outbox rows across tenants and has no business in either of these. Stated
    #  by omission — the grant simply is not made.


def downgrade() -> None:
    for table in ("model_calls", "run_outputs"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.drop_table(table)
    op.drop_constraint("uq_run_steps_tenant_id", "run_steps", type_="unique")
