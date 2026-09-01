"""Schedule firings — the ledger that makes a scheduler safe to run twice.

Gate 4 gave a schedule its configuration and a preview. `recurrence.py` already answers *when*,
purely and testably. What has been missing is the thing that turns an answer into a run — and the
hard part of that is not the timer, it is **exactly once**.

## Why a row per occurrence

A scheduler is a loop that asks "what is due?" and acts. Every such loop is eventually run twice
at once: a second worker is started by mistake, a deploy overlaps, a container is restarted before
its lease expired. Without a record of what has already been fired, both workers see the same
occurrence and both start a run — and a nightly reconciliation that ran twice is worse than one
that did not run at all, because the second one looks legitimate.

`uq_schedule_firings_occurrence` is that record. One row per `(schedule_id, due_at)`, inserted
**before** the run is started. The second worker's insert is refused by the database rather than
by a lock somebody has to remember to take.

## `due_at` is an instant, and it is the occurrence's identity

Stored UTC, computed from the schedule's local intent by `recurrence.occurrences`. Two firings of
an hourly schedule an hour apart are two different rows; the two 02:30s on the day a clock goes
back are also two different rows, which is exactly what `ambiguous_policy = both` means and why
the identity cannot be a local date.

## The states, and why `skipped` carries a reason

A schedule that did not run is the thing people ask about, and "it did not run" is never a useful
answer. `skipped` always says which rule skipped it — the overlap policy, the concurrency
ceiling, the skip calendar, a missing published version — so the schedule page answers the
question rather than posing it.

`awaiting_approval` is §8's `requires_approval_per_run`: the occurrence is due, nothing has been
started, and a person has to release it. It is a state rather than a silently-skipped run,
because a run that quietly did not happen is indistinguishable from a scheduler that is broken.

## What is deliberately absent

**No `attempts`.** A firing that failed to start is not retried by rewriting this row; the next
tick sees the same occurrence already recorded and leaves it alone. Catch-up is `missed_run_policy`
and it is computed, not stored.

**No `DELETE` grant.** A schedule's history is evidence of what ran and what did not. Turning a
schedule off must not erase the record of it having fired.

Revision: 0034
Parent:   0033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `due` is the moment after the row is claimed and before the run exists — a crash there leaves
#: a visible row rather than a silent gap.
STATES = ("due", "started", "skipped", "failed", "awaiting_approval")


def upgrade() -> None:
    #  The composite key the firing's foreign key needs. `job_schedules` was created with a
    #  primary key on `id` alone, and a `(tenant_id, id)` reference needs a unique constraint on
    #  exactly those columns — the pattern every tenant-owned parent in this schema follows, so
    #  that a child cannot reference a parent belonging to another workspace.
    op.create_unique_constraint(
        "uq_job_schedules_tenant_id", "job_schedules", ["tenant_id", "id"]
    )
    op.create_table(
        "schedule_firings",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", pg.UUID(as_uuid=True), nullable=False),
        #: The occurrence this row *is*. UTC, and the identity of the firing.
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        #: When the scheduler actually got to it. Later than `due_at` by however long the worker
        #: was busy or down — and the gap between the two is the only honest measure of whether
        #: the scheduler is keeping up.
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="due"),
        #: Which rule skipped it, or what failed. Never null on `skipped` or `failed`: "it did not
        #: run" is the answer nobody can act on.
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=True),
        #: The version this occurrence ran. Recorded per firing rather than read from the Job,
        #: because a schedule can be pinned and the Job's published version can move underneath.
        sa.Column("job_version_id", pg.UUID(as_uuid=True), nullable=True),
        #: True when this occurrence was made up for after the scheduler had been down — so a
        #: report that ran at 09:14 for an 03:00 slot says why.
        sa.Column(
            "was_missed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("state IN " + str(STATES), name="ck_schedule_firings_state"),
        sa.CheckConstraint(
            "state NOT IN ('skipped', 'failed') "
            "OR (detail IS NOT NULL AND btrim(detail) <> '')",
            name="ck_schedule_firings_skip_has_reason",
        ),
        #: A started firing points at its run. Without this a row can claim a run happened with
        #: nothing to open.
        sa.CheckConstraint(
            "(state = 'started') = (run_id IS NOT NULL)",
            name="ck_schedule_firings_started_has_run",
        ),
        #: **Exactly once.** The whole reason this table exists.
        sa.UniqueConstraint(
            "schedule_id", "due_at", name="uq_schedule_firings_occurrence"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_schedule_firings_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "schedule_id"],
            ["job_schedules.tenant_id", "job_schedules.id"],
            name="fk_schedule_firings_schedule",
            ondelete="CASCADE",
        ),
        #: `SET NULL` rather than cascade: a run may be cleaned up one day, and the record that
        #: the schedule fired must outlive it.
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_schedule_firings_run",
            ondelete="SET NULL",
        ),
    )
    #  The scheduler's own query: what is still owed, oldest first.
    op.create_index(
        "ix_schedule_firings_state",
        "schedule_firings",
        ["tenant_id", "state", "due_at"],
    )
    #  The schedule page's: this schedule's history, newest first.
    op.create_index(
        "ix_schedule_firings_schedule",
        "schedule_firings",
        ["tenant_id", "schedule_id", "due_at"],
    )

    op.execute("ALTER TABLE schedule_firings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE schedule_firings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY schedule_firings_tenant ON schedule_firings
        USING (tenant_id = app_current_tenant())
        WITH CHECK (tenant_id = app_current_tenant())
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON schedule_firings TO uboss_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS schedule_firings_tenant ON schedule_firings")
    op.drop_index("ix_schedule_firings_schedule", table_name="schedule_firings")
    op.drop_index("ix_schedule_firings_state", table_name="schedule_firings")
    op.drop_table("schedule_firings")
    op.drop_constraint("uq_job_schedules_tenant_id", "job_schedules", type_="unique")
